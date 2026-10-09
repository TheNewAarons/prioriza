"""Línea de comandos ``prioriza-schedule``.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from shared.db.enums import NoShowScenario
from shared.disclaimer import DISCLAIMER

from scheduler.config import OverbookingConfig, SchedulerConfig, SolverConfig
from scheduler.plan import SchedulePlan, greedy_schedule, solve

app = typer.Typer(
    help="Programador CP-SAT de la lista de espera. " + DISCLAIMER,
    add_completion=False,
)


class PolicyChoice(StrEnum):
    """Políticas que la CLI puede correr."""

    ALL = "all"
    OPTIMIZED = "optimized"
    PRIORITY = "priority"
    FIFO = "fifo"


class Decomposition(StrEnum):
    """Modo de descomposición (formulación §8.3)."""

    AUTO = "auto"
    SPECIALTY = "specialty"


def _find_run(data_dir: Path, seed: int, size: int, scenario: str) -> Path:
    from noshow.cli import current_generator_shas  # type: ignore[import-untyped]
    from noshow.data import find_run_dir  # type: ignore[import-untyped]

    path: Path = find_run_dir(data_dir, seed, size, scenario, current_generator_shas())
    return path


def comparison(plans: dict[str, SchedulePlan]) -> list[dict[str, Any]]:
    """Tabla de métricas por política, incluidas las que no mejoran (sin ocultar nada)."""
    rows: list[dict[str, Any]] = []
    for name, plan in plans.items():
        rep = plan.report
        rows.append(
            {
                "policy": name,
                "scheduled": rep["summary"]["scheduled"],
                "scheduled_cne": rep["summary"]["scheduled_cne"],
                "scheduled_or": rep["summary"]["scheduled_or"],
                "overbooked_flags": rep["summary"]["overbooked_flags"],
                "sum_coef": int(plan.assignments["coef"].sum()),
                "q1_scheduled": rep["summary"]["q1_scheduled"],
                "ges_met": rep["ges"]["met"],
                "ges_unmet": rep["ges"]["unmet"],
                "ges_on_time": rep["ges"]["on_time"],
                "solver_status": plan.solver_status,
                "gap": plan.gap,
            }
        )
    return rows


@app.command()
def main(
    weeks: Annotated[
        int, typer.Option("--weeks", min=1, max=52, help="Semanas del horizonte.")
    ] = 4,
    policy: Annotated[PolicyChoice, typer.Option("--policy")] = PolicyChoice.ALL,
    seed: Annotated[int, typer.Option("--seed", help="Semilla de la corrida y del solver.")] = 42,
    size: Annotated[int, typer.Option("--size", help="Tamaño de la corrida sintética.")] = 100_000,
    scenario: Annotated[NoShowScenario, typer.Option("--scenario")] = NoShowScenario.BASELINE,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data/synthetic"),
    run_dir: Annotated[
        Path | None, typer.Option("--run-dir", help="Corrida explícita (ignora seed/size).")
    ] = None,
    models_dir: Annotated[Path, typer.Option("--models-dir")] = Path("models/noshow"),
    overbooking: Annotated[bool, typer.Option("--overbooking/--no-overbooking")] = True,
    alpha: Annotated[float, typer.Option("--alpha", min=0.0001, max=0.9999)] = 0.10,
    time_limit: Annotated[float, typer.Option("--time-limit", min=0.1, help="Segundos.")] = 120.0,
    workers: Annotated[int, typer.Option("--workers", min=1)] = 8,
    deterministic: Annotated[bool, typer.Option("--deterministic/--no-deterministic")] = True,
    decomposition: Annotated[Decomposition, typer.Option("--decomposition")] = Decomposition.AUTO,
    persist: Annotated[
        bool, typer.Option("--persist/--no-persist", help="Guarda en schedule_run y appointment.")
    ] = False,
    results_dir: Annotated[Path, typer.Option("--results-dir")] = Path("results"),
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("data/schedules"),
) -> None:
    """Corre el programador sobre una corrida sintética y escribe el informe y los planes."""
    from scheduler.adapters import instance_from_run

    typer.echo(DISCLAIMER)
    if run_dir is None:
        try:
            run_dir = _find_run(data_dir, seed, size, scenario.value)
        except (FileNotFoundError, FileExistsError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    config = SchedulerConfig(
        horizon_weeks=weeks,
        overbooking=OverbookingConfig(enabled=overbooking, alpha=alpha),
        decomposition=decomposition.value,
        time_limit_s=time_limit,
        solver=SolverConfig(num_workers=workers, deterministic=deterministic),
    )
    t0 = time.perf_counter()
    try:
        instance, info = instance_from_run(run_dir, config, models_dir=models_dir, seed=seed)
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"corrida={info.run_id} as_of={info.as_of} horizonte={info.horizon_start} +{weeks} sem "
        f"entradas={len(instance.entries)} bloques={len(instance.blocks)} "
        f"({time.perf_counter() - t0:.1f} s)"
    )
    names = ["fifo", "priority", "optimized"] if policy is PolicyChoice.ALL else [policy.value]
    plans: dict[str, SchedulePlan] = {}
    for name in names:
        t1 = time.perf_counter()
        if name == "optimized":
            plans[name] = solve(instance, config)
        else:
            plans[name] = greedy_schedule(
                instance, config, "fifo" if name == "fifo" else "priority"
            )
        rep = plans[name].report
        typer.echo(
            f"  {name:10s} agendadas={rep['summary']['scheduled']} "
            f"sobrecupos={rep['summary']['overbooked_flags']} GES cumplidas={rep['ges']['met']}/"
            f"{rep['ges']['obligated']} estado={plans[name].solver_status} "
            f"brecha={plans[name].gap} ({time.perf_counter() - t1:.1f} s)"
        )

    target = out_dir / info.run_id / f"{weeks}w"
    target.mkdir(parents=True, exist_ok=True)
    for name, plan in plans.items():
        plan.assignments.write_parquet(target / f"{name}_assignments.parquet")
        plan.explanations.write_parquet(target / f"{name}_explanations.parquet")
        plan.ges.write_parquet(target / f"{name}_ges.parquet")
        plan.standby.write_parquet(target / f"{name}_standby.parquet")
    results_dir.mkdir(parents=True, exist_ok=True)
    # El nombre canónico es solo para la configuración por defecto; una variante (otra política,
    # alpha, sin sobrecupo, etc.) lleva el digest para no pisar el resultado versionado.
    variant = ""
    if policy is not PolicyChoice.ALL or config != SchedulerConfig(horizon_weeks=weeks):
        variant = f"_{policy.value}_{config.digest()[:8]}"
    results_path = results_dir / f"schedule_{info.run_id}_{weeks}w{variant}.json"
    payload = {
        "disclaimer": DISCLAIMER,
        "run": {k: info.manifest_run[k] for k in ("id", "seed", "size", "scenario", "as_of")},
        "comparison": comparison(plans),
        "policies": {name: plan.report for name, plan in plans.items()},
    }
    results_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"informe={results_path} planes={target}")

    if persist:
        from shared.db.session import session_factory

        from scheduler.persist import persist_plan

        with session_factory()() as session, session.begin():
            for name, plan in plans.items():
                end = instance.horizon_start + timedelta(days=7 * weeks)
                sid = persist_plan(session, plan, instance, uuid.UUID(info.run_id), end)
                typer.echo(f"  {name}: schedule_run={sid} (review_status=pending)")


def run() -> None:
    """Punto de entrada de ``prioriza-schedule``."""
    app()
