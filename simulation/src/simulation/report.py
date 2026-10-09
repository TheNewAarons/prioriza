"""Informe JSON de la simulación (diseño §8): agregados y comparaciones pareadas.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

from shared.disclaimer import DISCLAIMER

from simulation.config import SimulationConfig
from simulation.engine import simulate
from simulation.supply import supply_coverage
from simulation.world import World

LIMITATIONS = [
    "Granularidad de la oferta: cada sesión atiende una sola celda (servicio x especialidad); a "
    "tamaños chicos muchas celdas no reciben ninguna sesión en el periodo simulado y su stock no "
    "puede atenderse con ninguna política (ver supply_coverage).",
    "Llegadas por Little en estado estacionario: sin estacionalidad, sin tendencia y con la "
    "espera media de un solo corte.",
    "La oferta replica la del generador (capacity_multiplier 1,0, sin margen) y es igual todas "
    "las semanas; no hay feriados, suspensiones de pabellón ni ausentismo de especialistas.",
    "Sin abandono ni otras causales administrativas por defecto; sin controles posteriores ni "
    "derivación a cirugía.",
    "El modelo de inasistencias no se reentrena durante la simulación.",
    "La verdad de inasistencia es la del generador: las conclusiones valen para ese mundo "
    "sintético, no para la red real.",
]

# Dirección de cada métrica resumen (clave aplanada): -1 menor es mejor, +1 mayor es mejor.
# Las que no están (conteos de contexto como llegadas o n) no tienen dirección: better_in = None.
DIRECTION: dict[str, int] = {
    "list_size_final": -1,
    "waiting_final": -1,
    "resolved_total": 1,
    "removed_no_show_total": -1,
    "abandoned_total": -1,
    "wait_attended_median": -1,
    "wait_attended_p90": -1,
    "wait_stock_final_median": -1,
    "wait_stock_final_p90": -1,
    "ges_breached": -1,
    "ges_attended_on_time": 1,
    "ges_overdue_at_end": -1,
    "slot_use_cne_utilization": 1,
    "slot_use_or_utilization": 1,
    "lost_slots_cne_units": -1,
    "lost_slots_or_minutes": -1,
    "overflow_sessions": -1,
    "overflow_units": -1,
    "overflow_affected_patients": -1,
    "no_slot_at_arrival": -1,
    "no_show_rate_cne": -1,
    "no_show_rate_or": -1,
    "exits_attended": 1,
    "exits_two_no_shows": -1,
}


def _flatten(summary: dict[str, Any], prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in summary.items():
        key = f"{prefix}{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}_"))
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
            out[key] = float(v)
    return out


def _metric_keys(flats: list[dict[str, float]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for f in flats:
        for k in f:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def _t_critical(n: int) -> float:
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
    }
    return table.get(n - 1, 1.96)


def _ci(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n < 2:
        return (values[0], values[0]) if n == 1 else (0.0, 0.0)
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    half = _t_critical(n) * sd / (n**0.5)
    return (mean - half, mean + half)


def _better_in(ds: list[float], key: str) -> int | None:
    sign = DIRECTION.get(key)
    if sign is None:
        return None
    return sum(1 for d in ds if d * sign > 0)


def _aggregate(by_policy: dict[str, list[dict[str, float]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, flats in by_policy.items():
        metrics: dict[str, Any] = {}
        for key in _metric_keys(flats):
            vals = [f[key] for f in flats if key in f]
            if not vals:
                continue
            lo, hi = _ci(vals)
            metrics[key] = {
                "mean": statistics.mean(vals),
                "sd": statistics.stdev(vals) if len(vals) > 1 else 0.0,
                "min": min(vals),
                "max": max(vals),
                "ci95_low": lo,
                "ci95_high": hi,
                "n": len(vals),
            }
        out[name] = metrics
    return out


def _comparisons(
    by_policy: dict[str, list[dict[str, float]]], policies: tuple[str, ...]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # Contra las dos políticas base y, para aislar el sobrecupo, optimized_overbooking contra
    # optimized (misma réplica: números aleatorios comunes).
    pairs = [(p, base) for base in ("fifo", "priority") for p in policies if p != base]
    pairs.append(("optimized_overbooking", "optimized"))
    for policy, base in pairs:
        if base not in by_policy or policy not in by_policy:
            continue
        base_flats = by_policy[base]
        pol_flats = by_policy[policy]
        diffs: dict[str, Any] = {}
        for key in _metric_keys([*base_flats, *pol_flats]):
            ds = [
                pol_flats[i][key] - base_flats[i][key]
                for i in range(len(base_flats))
                if key in pol_flats[i] and key in base_flats[i]
            ]
            if not ds:
                continue
            lo, hi = _ci(ds)
            diffs[key] = {
                "mean_diff": statistics.mean(ds),
                "ci95_low": lo,
                "ci95_high": hi,
                "better_in": _better_in(ds, key),
                "direction": DIRECTION.get(key),
            }
        out[f"{policy}_vs_{base}"] = diffs
    return out


def run_experiment(world: World, config: SimulationConfig) -> dict[str, Any]:
    """Todas las políticas y réplicas; devuelve el payload del JSON (diseño §8)."""
    by_policy: dict[str, list[dict[str, float]]] = {}
    replicas: list[dict[str, Any]] = []
    timing: dict[str, list[float]] = {}
    for seed in config.replica_seeds:
        policies: dict[str, dict[str, Any]] = {}
        for policy in config.policies:
            t0 = time.perf_counter()
            result = simulate(world, policy, config, seed)
            timing.setdefault(policy, []).append(time.perf_counter() - t0)
            policies[policy] = {
                "summary": result.summary,
                "weekly": result.weekly,
                "groups": result.groups,
                "scheduler": result.scheduler,
            }
            by_policy.setdefault(policy, []).append(_flatten(result.summary))
        replicas.append({"seed": seed, "policies": policies})
    return {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "code_version": f"simulation-{version('simulation')}",
        "run": {
            "id": world.run_id,
            "size": world.size,
            "seed": world.seed,
            "scenario": world.scenario,
            "as_of": world.as_of.isoformat(),
        },
        "noshow_model_version": world.model_version,
        "truth_source": "synthetic.noshow_truth.true_noshow_prob",
        "config": config.model_dump(mode="json"),
        "replica_seeds": list(config.replica_seeds),
        "supply_coverage": supply_coverage(world, config),
        "replicas": replicas,
        "aggregate": _aggregate(by_policy),
        "comparisons": _comparisons(by_policy, config.policies),
        "limitations": LIMITATIONS,
        "timing": {p: {"total_s": sum(v), "mean_s": statistics.mean(v)} for p, v in timing.items()},
    }
