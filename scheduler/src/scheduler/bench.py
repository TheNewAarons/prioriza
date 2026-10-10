"""Benchmark del programador: tamaños, horizontes, técnicas de rendimiento y voraz (P9).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Para cada tamaño de población y horizonte genera una corrida sintética cuya oferta cubre
exactamente el horizonte (``horizon_weeks`` del generador = semanas del plan; ver
``docs/decisions.md`` §11 y la formulación §11.2), entrena el modelo de inasistencias de esa
corrida, corre la voraz ``priority`` (y ``fifo`` como contexto) y la política ``optimized``
con todas las técnicas y, si se pide, con cada técnica apagada; además corre ``optimized``
sin sobrecupo, que es la comparación justa con la voraz en el orden lexicográfico de la
formulación §9.5. Escribe ``results/scheduler-benchmark.json``. Todo es determinista salvo
los tiempos de reloj, que dependen de la máquina y de su carga.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer
from noshow.data import load_run  # type: ignore[import-untyped]
from noshow.train import TrainConfig, save, train  # type: ignore[import-untyped]
from shared.db.enums import NoShowScenario
from shared.disclaimer import DISCLAIMER
from synthetic.config import RunConfig  # type: ignore[import-untyped]
from synthetic.io import write_parquet  # type: ignore[import-untyped]
from synthetic.pipeline import generate  # type: ignore[import-untyped]
from synthetic.targets import load_assumptions, load_targets  # type: ignore[import-untyped]
from synthetic.validate import calibration_report  # type: ignore[import-untyped]

from scheduler.adapters import instance_from_run
from scheduler.config import OverbookingConfig, SchedulerConfig
from scheduler.instance import SchedulingInstance
from scheduler.plan import SchedulePlan, code_version, greedy_schedule, solve
from scheduler.prepare import prepare

SIZES = (1_000, 10_000, 50_000)
WEEKS = (2, 4)
TECHNIQUES = (
    "hints",
    "objective_cut",
    "symmetry_breaking",
    "prune_overbooking_levels",
    "overbooking_hint",
    "warm_start_frontier",
)
# Variante "all": todas las técnicas (configuración por defecto). "without_<t>": solo esa
# apagada. "none": todas apagadas.
VARIANTS: dict[str, dict[str, bool]] = {
    "all": {},
    **{f"without_{t}": {t: False} for t in TECHNIQUES},
    "none": dict.fromkeys(TECHNIQUES, False),
}

app = typer.Typer(
    help="Benchmark del programador CP-SAT con poblaciones sintéticas. " + DISCLAIMER,
    add_completion=False,
)


def ensure_run(work_dir: Path, size: int, seed: int, scenario: str, weeks: int) -> dict[str, Any]:
    """Genera (o regenera, es determinista) la corrida sintética con oferta de ``weeks`` semanas."""
    cfg = RunConfig(
        size=size, seed=seed, scenario=NoShowScenario(scenario), horizon_weeks=weeks, as_of=None
    )
    targets, assumptions = load_targets(), load_assumptions()
    ds = generate(cfg, targets, assumptions)
    report = calibration_report(ds, targets, assumptions)
    run_dir: Path = write_parquet(ds, work_dir / "synthetic", report)
    failed = [c.name for c in report.checks if c.severity == "strict" and not c.passed]
    return {
        "run_dir": run_dir,
        "run_id": str(ds.run["id"]),
        "supply_horizon_weeks": weeks,
        "calibration_passed": bool(report.passed),
        "calibration_strict_failed": failed,
    }


def train_model(work_dir: Path, run_dir: Path, seed: int) -> str:
    """Entrena el modelo de inasistencias de la corrida; devuelve su versión."""
    output = train(load_run(run_dir), TrainConfig(seed=seed))
    save(output, work_dir / "models", work_dir / "noshow" / f"{run_dir.name}.json")
    return str(output.results["model_version"])


def size_stats(instance: SchedulingInstance, config: SchedulerConfig) -> dict[str, Any]:
    """Tamaño del problema antes y después de preprocesar compatibilidades (§4, §8.2)."""
    prep = prepare(instance, config)
    by_queue: dict[tuple[str, str], int] = {}
    for q in prep.queue:
        by_queue[q] = by_queue.get(q, 0) + 1
    same_queue = sum(n * len(prep.queue_blocks.get(q, [])) for q, n in by_queue.items())
    in_horizon = [b for b, ok in enumerate(prep.block_in_horizon) if ok]
    return {
        "entries": len(instance.entries),
        "blocks_cne": sum(1 for b in in_horizon if prep.block(b).is_cne),
        "blocks_or": sum(1 for b in in_horizon if not prep.block(b).is_cne),
        "capacity_cne_units": sum(prep.capacity[b] for b in in_horizon if prep.block(b).is_cne),
        "capacity_or_min": sum(prep.capacity[b] for b in in_horizon if not prep.block(b).is_cne),
        "ges_obligated": len(prep.obligation),
        "pairs_all": len(instance.entries) * len(in_horizon),
        "pairs_same_queue": same_queue,
        "pairs_compatible": len(prep.pair_entry),
        "entries_with_pairs": len(prep.pairs_of_entry),
    }


def plan_metrics(plan: SchedulePlan) -> dict[str, Any]:
    """Métricas de resultado comparables entre políticas."""
    rep = plan.report
    out: dict[str, Any] = {
        "scheduled": rep["summary"]["scheduled"],
        "scheduled_cne": rep["summary"]["scheduled_cne"],
        "scheduled_or": rep["summary"]["scheduled_or"],
        "q1_scheduled": rep["summary"]["q1_scheduled"],
        "overbooked_flags": rep["summary"]["overbooked_flags"],
        "ges_obligated": rep["ges"]["obligated"],
        "ges_met": rep["ges"]["met"],
        "ges_on_time": rep["ges"]["on_time"],
        "sum_coef": int(plan.assignments["coef"].sum()),
    }
    return out


def solver_metrics(plan: SchedulePlan, wall: float, time_limit: float) -> dict[str, Any]:
    """Tiempo, estado y brecha de la política ``optimized``."""
    s = plan.report["solver"]
    subs = s["subproblems"]
    phases = [p for sub in subs for p in sub["phases"]]
    det_plan = s["time"]["plan"]["deterministic_time"]
    det_total = det_plan + s["time"]["discarded_first_pass"]["deterministic_time"]
    tech = [sub["techniques"] for sub in subs]
    return {
        # Reloj de todo ``solve`` (preparación, voraz por subproblema, CP-SAT, verificación e
        # informe), mediana de las repeticiones; depende de la máquina y de su carga.
        "solve_wall_s": wall,
        "solve_wall_within_time_limit": wall <= time_limit,
        # Tiempo determinista de CP-SAT (reproducible). ``time_limit`` es el presupuesto de todo
        # el plan, primera pasada y expansión de frontera juntas (§8.5); el total puede
        # excederlo poco porque CP-SAT revisa el límite por lotes (``budget.overrun``).
        "deterministic_time_plan": det_plan,
        "deterministic_time_total": det_total,
        "deterministic_plan_within_time_limit": det_plan <= time_limit,
        "budget": s["budget"],
        "solver_time": s["time"],
        "status": s["status"],
        "status_by_phase": s["status_by_phase"],
        "gap": s["gap"],
        "gap_by_phase": s["gap_by_phase"],
        "subproblems": len(subs),
        "candidates": plan.report["summary"]["candidates"],
        "pairs_in_model": sum(sub["pairs"] for sub in subs),
        "largest_subproblem_pairs": max((sub["pairs"] for sub in subs), default=0),
        "max_variables": max((p["variables"] for p in phases), default=0),
        "max_constraints": max((p["constraints"] for p in phases), default=0),
        "frontier": plan.report["frontier"],
        "overbooking_levels_nominal": sum(t["overbooking_levels_nominal"] for t in tech),
        "overbooking_levels_kept": sum(t["overbooking_levels_kept"] for t in tech),
        "symmetry_block_classes": sum(t["symmetry_block_classes"] for t in tech),
        "symmetry_blocks_in_classes": sum(t["symmetry_blocks_in_classes"] for t in tech),
        "symmetry_entry_classes": sum(t["symmetry_entry_classes"] for t in tech),
        "symmetry_entries_in_classes": sum(t["symmetry_entries_in_classes"] for t in tech),
        "warnings_worse_than_baseline": sum(
            1 for w in plan.report["warnings"] if "worse_than_baseline" in w
        ),
    }


COMPARED = (
    "scheduled",
    "scheduled_cne",
    "scheduled_or",
    "q1_scheduled",
    "ges_met",
    "ges_on_time",
    "sum_coef",
)


def compare(optimized: dict[str, Any], greedy: dict[str, Any]) -> dict[str, Any]:
    """Diferencias ``optimized - priority`` tal cual y el orden lexicográfico de §9.5.

    El orden ``(p1 agendados, GES cumplidas, suma de c_ib)`` solo es comparable si ``optimized``
    corrió sin sobrecupo, como la voraz; con sobrecupo, las diferencias se leen una a una.
    """
    delta = {k: optimized[k] - greedy[k] for k in COMPARED}
    relative = {k: (delta[k] / greedy[k] if greedy[k] else None) for k in COMPARED}
    lex_opt = (optimized["q1_scheduled"], optimized["ges_met"], optimized["sum_coef"])
    lex_greedy = (greedy["q1_scheduled"], greedy["ges_met"], greedy["sum_coef"])
    return {
        "delta": delta,
        "relative": relative,
        "lexicographic_optimized": list(lex_opt),
        "lexicographic_priority": list(lex_greedy),
        "optimized_not_worse_lexicographic": lex_opt >= lex_greedy,
    }


def bench_cell(
    work_dir: Path,
    size: int,
    weeks: int,
    seed: int,
    scenario: str,
    time_limit: float,
    variants: list[str],
    repeats: int,
    log: Callable[[str], None],
) -> dict[str, Any]:
    """Una celda (tamaño, horizonte): datos, voraces y variantes de ``optimized``."""
    t0 = time.perf_counter()
    run = ensure_run(work_dir, size, seed, scenario, weeks)
    t_gen = time.perf_counter() - t0
    run_dir: Path = run.pop("run_dir")
    t0 = time.perf_counter()
    run["noshow_model_version"] = train_model(work_dir, run_dir, seed)
    t_train = time.perf_counter() - t0
    config = SchedulerConfig(horizon_weeks=weeks, time_limit_s=time_limit)
    t0 = time.perf_counter()
    instance, _ = instance_from_run(run_dir, config, models_dir=work_dir / "models", seed=seed)
    t_inst = time.perf_counter() - t0
    log(f"n={size} semanas={weeks} corrida={run['run_id']} ({t_gen:.1f}+{t_train:.1f} s)")

    greedy: dict[str, Any] = {}
    for order in ("priority", "fifo"):
        t0 = time.perf_counter()
        plan = greedy_schedule(instance, config, order)
        wall = time.perf_counter() - t0
        greedy[order] = {"wall_time_s": wall, **plan_metrics(plan)}
        log(f"  {order:30s} agendadas={greedy[order]['scheduled']} ({wall:.1f} s)")

    results: dict[str, Any] = {}
    for name in variants:
        flags = VARIANTS[name]
        cfg = config.model_copy(update={"solver": config.solver.model_copy(update=flags)})
        walls: list[float] = []
        opt: SchedulePlan | None = None
        for _ in range(repeats if name == "all" else 1):
            t0 = time.perf_counter()
            opt = solve(instance, cfg)
            walls.append(time.perf_counter() - t0)
        assert opt is not None
        wall = statistics.median(walls)
        entry = {
            "flags": flags,
            "solver": solver_metrics(opt, wall, time_limit),
            "wall_time_s_runs": walls,
            **plan_metrics(opt),
        }
        results[name] = entry
        log(
            f"  optimized/{name:21s} agendadas={entry['scheduled']} estado="
            f"{entry['solver']['status']} brecha={entry['solver']['gap']} "
            f"det={entry['solver']['deterministic_time_total']:.2f} ({wall:.1f} s)"
        )
    best = results.get("all") or next(iter(results.values()))
    # Misma configuración sin sobrecupo: comparación lexicográfica justa con la voraz.
    cfg_nob = config.model_copy(update={"overbooking": OverbookingConfig(enabled=False)})
    t0 = time.perf_counter()
    nob = solve(instance, cfg_nob)
    wall = time.perf_counter() - t0
    no_overbooking = {"solver": solver_metrics(nob, wall, time_limit), **plan_metrics(nob)}
    log(f"  optimized/sin sobrecupo agendadas={no_overbooking['scheduled']} ({wall:.1f} s)")
    return {
        "size": size,
        "horizon_weeks": weeks,
        "data": run,
        "times_s": {"generate": t_gen, "train_noshow": t_train, "build_instance": t_inst},
        "problem": size_stats(instance, config),
        "greedy": greedy,
        "optimized": results,
        "optimized_without_overbooking": no_overbooking,
        "optimized_vs_priority": compare(best, greedy["priority"]),
        "optimized_without_overbooking_vs_priority": compare(no_overbooking, greedy["priority"]),
    }


def _ints(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


@app.command()
def main(
    sizes: Annotated[str, typer.Option("--sizes", help="Tamaños, separados por coma.")] = ",".join(
        str(s) for s in SIZES
    ),
    weeks: Annotated[str, typer.Option("--weeks", help="Horizontes en semanas.")] = ",".join(
        str(w) for w in WEEKS
    ),
    seed: Annotated[int, typer.Option("--seed")] = 42,
    scenario: Annotated[NoShowScenario, typer.Option("--scenario")] = NoShowScenario.BASELINE,
    time_limit: Annotated[float, typer.Option("--time-limit", min=0.1, help="Segundos.")] = 120.0,
    ablation: Annotated[
        bool, typer.Option("--ablation/--no-ablation", help="Corre cada técnica apagada.")
    ] = True,
    repeats: Annotated[
        int, typer.Option("--repeats", min=1, help="Repeticiones de la variante completa.")
    ] = 3,
    work_dir: Annotated[Path, typer.Option("--work-dir")] = Path("data/bench"),
    out: Annotated[Path, typer.Option("--out")] = Path("results/scheduler-benchmark.json"),
) -> None:
    """Corre el benchmark y escribe el informe JSON."""
    typer.echo(DISCLAIMER)
    variants = list(VARIANTS) if ablation else ["all"]
    cells = [
        bench_cell(work_dir, n, w, seed, scenario.value, time_limit, variants, repeats, typer.echo)
        for n in _ints(sizes)
        for w in _ints(weeks)
    ]
    payload = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "code_version": code_version(),
        "config_defaults": SchedulerConfig().model_dump(mode="json"),
        "time_limit_s": time_limit,
        "seed": seed,
        "scenario": scenario.value,
        "variants": VARIANTS,
        "repeats_all": repeats,
        "machine": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
            "ortools": version("ortools"),
            "polars": version("polars"),
        },
        "cells": cells,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"informe={out}")


def run() -> None:
    """Punto de entrada de ``prioriza-schedule-bench``."""
    app()
