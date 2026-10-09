"""Hechos del informe: lectura estricta de ``results/*.json`` y de las fuentes versionadas.

``load_facts`` es puro (no formatea): devuelve números y textos tal como salen de los archivos,
más las cantidades derivadas (diferencias, brechas, lecturas de comparaciones) calculadas aquí
para que las plantillas no calculen nada. Si falta un archivo o un campo, levanta ``FactsError``
con el archivo y la ruta del campo; no hay valores por defecto silenciosos.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión
real sin validación institucional.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shared.disclaimer import DISCLAIMER
from synthetic.targets import load_assumptions, load_targets  # type: ignore[import-untyped]

from priority import load_default_rules

CALIBRATION_GLOB = "synthetic_calibration_*.json"
CALIBRATION_NAME = re.compile(
    r"^synthetic_calibration_(?P<scenario>.+)_seed(?P<seed>\d+)_n(?P<size>\d+)\.json$"
)
SCHEDULE_NAME = re.compile(r"^schedule_(?P<run_id>[0-9a-f-]{36})_4w\.json$")
NOSHOW_FILE = "noshow.json"
BENCHMARK_FILE = "scheduler-benchmark.json"
SIMULATION_FILE = "simulation.json"

LISTING_LIMIT = 10
"""Grupos que se listan cuando una dimensión tiene demasiados (comunas): los más expuestos."""
FULL_LISTING_MAX = 12
"""Hasta este número de grupos por dimensión se listan todos."""

REFERENCE_DOCUMENT = "Glosa 06"
"""Nombre del documento del Minsal del que salen las cifras nacionales de referencia."""

POLICY_LABELS = {
    "fifo": "Orden de llegada",
    "priority": "Solo prioridad",
    "optimized": "Optimizada",
    "optimized_overbooking": "Optimizada con sobrecupo",
}

SIM_METRICS: tuple[tuple[str, str, str], ...] = (
    ("exits_attended", "Pacientes atendidos", "count"),
    ("wait_attended_median", "Mediana de espera de los atendidos (días)", "days"),
    ("wait_attended_p90", "p90 de espera de los atendidos (días)", "days"),
    ("wait_stock_final_median", "Mediana de espera de la lista final (días)", "days"),
    ("wait_stock_final_p90", "p90 de espera de la lista final (días)", "days"),
    ("list_size_final", "Tamaño final de la lista", "count"),
    ("ges_attended_on_time", "GES atendidas a tiempo", "count"),
    ("ges_breached", "GES incumplidas", "count"),
    ("ges_overdue_at_end", "GES vencidas al final", "count"),
    ("no_slot_at_arrival", "Llegadas sin cupo en el horizonte del plan", "count"),
    ("exits_two_no_shows", "Salidas por dos inasistencias", "count"),
    ("no_show_rate_cne", "Inasistencia realizada, consultas", "rate"),
    ("no_show_rate_or", "Inasistencia realizada, cirugías", "rate"),
    ("slot_use_cne_utilization", "Utilización de cupos de consulta", "rate"),
    ("slot_use_or_utilization", "Utilización de pabellón", "rate"),
    ("lost_slots_cne_units", "Cupos de consulta perdidos", "count"),
    ("lost_slots_or_minutes", "Minutos de pabellón perdidos", "count"),
    ("overflow_sessions", "Sesiones con desborde", "count"),
    ("overflow_affected_patients", "Pacientes afectados por desborde", "count"),
)

SIM_COMPARISONS = (
    "optimized_vs_priority",
    "optimized_vs_fifo",
    "priority_vs_fifo",
    "optimized_overbooking_vs_priority",
    "optimized_overbooking_vs_fifo",
    "optimized_overbooking_vs_optimized",
)
"""Comparaciones pareadas que se muestran. ``fifo_vs_priority`` es el espejo (signo invertido) de
``priority_vs_fifo`` y no se repite; ``load_facts`` verifica que sea realmente su espejo."""
MIRRORED_COMPARISON = ("fifo_vs_priority", "priority_vs_fifo")

SIM_GROUP_DIMENSIONS = ("age_group", "insurance", "commune_code")
SCHED_GROUP_DIMENSIONS = ("age_group", "insurance", "commune_code")
SIM_GROUP_FIELDS = (
    "entries",
    "attended",
    "attention_rate",
    "ges_breached",
    "no_show_realized_rate",
    "overbooking_exposure",
    "overflow_share",
)

RESAMPLING_LABELS = {"patient": "paciente", "appointment": "cita"}

VARIANT_LABELS = {
    "all": "Completa (todas las técnicas)",
    "none": "Sin ninguna técnica",
    "without_hints": "Sin pistas de solución",
    "without_objective_cut": "Sin corte del objetivo",
    "without_overbooking_hint": "Sin pista de sobrecupo",
    "without_prune_overbooking_levels": "Sin poda de niveles de sobrecupo",
    "without_symmetry_breaking": "Sin ruptura de simetría",
    "without_warm_start_frontier": "Sin arranque en caliente de la frontera",
}


class FactsError(ValueError):
    """Falta un archivo o un campo, o la estructura no es la esperada."""


class _Doc:
    """Un JSON leído con acceso por ruta punteada que falla con el archivo y la ruta."""

    def __init__(self, data: Any, name: str, prefix: str = "") -> None:
        self.data = data
        self.name = name
        self.prefix = prefix

    def _fail(self, path: str, why: str) -> FactsError:
        full = f"{self.prefix}.{path}" if self.prefix else path
        return FactsError(f"{self.name}: {why} '{full}'")

    def req(self, path: str) -> Any:
        node: Any = self.data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                raise self._fail(path, "falta el campo")
            node = node[key]
        return node

    def num(self, path: str) -> float | int:
        value = self.req(path)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise self._fail(path, "se esperaba un número en")
        return value

    def text(self, path: str) -> str:
        value = self.req(path)
        if not isinstance(value, str):
            raise self._fail(path, "se esperaba un texto en")
        return value

    def items(self, path: str) -> list[Any]:
        value = self.req(path)
        if not isinstance(value, list):
            raise self._fail(path, "se esperaba una lista en")
        return value

    def sub(self, path: str) -> _Doc:
        value = self.req(path)
        if not isinstance(value, dict):
            raise self._fail(path, "se esperaba un objeto en")
        prefix = f"{self.prefix}.{path}" if self.prefix else path
        return _Doc(value, self.name, prefix)


def _read(path: Path) -> _Doc:
    if not path.is_file():
        raise FactsError(f"falta el archivo de resultados {path} (corre el paso que lo genera)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FactsError(f"{path.name}: JSON inválido ({exc})") from exc
    if not isinstance(data, dict):
        raise FactsError(f"{path.name}: se esperaba un objeto JSON en la raíz")
    return _Doc(data, path.name)


def _find_schedule(results_dir: Path) -> Path:
    found = sorted(p for p in results_dir.glob("schedule_*_4w.json") if SCHEDULE_NAME.match(p.name))
    if not found:
        raise FactsError(
            f"falta el plan canónico {results_dir / 'schedule_<run_id>_4w.json'} (make schedule)"
        )
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise FactsError(f"hay más de un plan canónico en {results_dir} ({names}); deja uno")
    return found[0]


def _find_calibration(results_dir: Path, run_id: str) -> Path:
    found = sorted(results_dir.glob(CALIBRATION_GLOB))
    if not found:
        raise FactsError(f"falta el informe de calibración {results_dir / CALIBRATION_GLOB}")
    matching: list[Path] = []
    for path in found:
        data = _read(path)
        if data.req("run_id") == run_id:
            matching.append(path)
    if not matching:
        raise FactsError(
            f"ningún informe de calibración en {results_dir} corresponde a la corrida {run_id}"
        )
    if len(matching) > 1:
        raise FactsError(
            f"más de un informe de calibración para la corrida {run_id}: "
            + ", ".join(p.name for p in matching)
        )
    return matching[0]


def _results_commit(results_dir: Path, repo_root: Path) -> str | None:
    """Hash del último commit que tocó ``results/``; ``None`` si no hay git o no hay historial."""
    try:
        done = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                "-1",
                "--format=%H",
                "--",
                str(results_dir.resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = done.stdout.strip()
    return commit if done.returncode == 0 and commit else None


def _label(policy: str) -> str:
    if policy not in POLICY_LABELS:
        raise FactsError(f"política desconocida en los resultados: {policy!r}")
    return POLICY_LABELS[policy]


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


# ------------------------------------------------------------------ Contexto y calibración


def _context(as_of: str) -> dict[str, Any]:
    targets = load_targets()
    sources = [{"source_id": s.source_id, "period": s.period} for s in targets.sources]
    national = []
    for key in ("consultation", "surgery", "ges"):
        row = targets.national_row(key)
        national.append(
            {
                "key": key,
                "waiting_count": row.waiting_count,
                "persons_count": row.persons_count,
                "mean_wait_days": row.mean_wait_days,
                "median_wait_days": row.median_wait_days,
            }
        )
    reference = next(
        (s for s in targets.sources if s.source_id == targets.reference_source_id), None
    )
    if reference is None:
        raise FactsError(
            f"calibration_targets.json: la fuente de referencia {targets.reference_source_id} "
            "no está en sources"
        )
    return {
        "reference_document": REFERENCE_DOCUMENT,
        "reference_source_id": targets.reference_source_id,
        "reference_period": reference.period,
        "sources": sources,
        "national": national,
        "as_of": as_of,
    }


def _calibration(doc: _Doc, name_match: re.Match[str]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for i, raw in enumerate(doc.items("checks")):
        c = _Doc(raw, doc.name, f"checks[{i}]")
        detail = c.req("detail")
        checks.append(
            {
                "name": c.text("name"),
                "group": c.text("group"),
                "metric": c.text("metric"),
                "observed": c.req("observed"),
                "target": c.req("target"),
                "tolerance": c.req("tolerance"),
                "n": c.req("n"),
                "passed": bool(c.req("passed")),
                "severity": c.text("severity"),
                "detail": "; ".join(str(d) for d in detail) if isinstance(detail, list) else "",
            }
        )
    groups: dict[str, dict[str, Any]] = {}
    for chk in checks:
        bucket = groups.setdefault(
            chk["group"],
            {"group": chk["group"], "checks": 0, "passed": 0, "strict_failed": 0, "soft_failed": 0},
        )
        bucket["checks"] += 1
        if chk["passed"]:
            bucket["passed"] += 1
        elif chk["severity"] == "strict":
            bucket["strict_failed"] += 1
        else:
            bucket["soft_failed"] += 1
    summary = doc.sub("summary")
    return {
        "run_id": doc.text("run_id"),
        "digest": doc.text("digest"),
        "scenario": name_match.group("scenario"),
        "seed": int(name_match.group("seed")),
        "size": int(name_match.group("size")),
        "passed": bool(doc.req("passed")),
        "summary": {
            k: summary.num(k) for k in ("strict_passed", "strict_failed", "soft_failed", "skipped")
        },
        "checks": checks,
        "failed": [c for c in checks if not c["passed"]],
        "by_group": sorted(groups.values(), key=lambda g: str(g["group"])),
        "notes": [str(n) for n in doc.items("notes") if str(n) != DISCLAIMER],
    }


# ------------------------------------------------------------------ Priorización


def _priority_rules(rules_digest_in_plan: str, rules_version_in_plan: str) -> dict[str, Any]:
    rules = load_default_rules()
    total = sum(c.weight for c in rules.components)
    components = []
    for c in rules.components:
        dumped = c.model_dump(mode="json")
        components.append(
            {
                "field": dumped["field"],
                "label": dumped["label"],
                "weight": dumped["weight"],
                "share": dumped["weight"] / total,
                "mapping": dumped.get("mapping"),
                "transform": dumped.get("transform"),
            }
        )
    strict = rules.ges_strict.model_dump(mode="json")
    return {
        "rules_id": rules.rules_id,
        "rules_version": rules.rules_version,
        "digest": rules.digest(),
        "description": rules.description,
        "total_weight": total,
        "components": components,
        "ges_strict": strict,
        "matches_plan": rules.digest() == rules_digest_in_plan
        and rules.rules_version == rules_version_in_plan,
        "plan_rules_digest": rules_digest_in_plan,
        "plan_rules_version": rules_version_in_plan,
    }


# ------------------------------------------------------------------ Plan canónico


def _plan_row(comparison: _Doc, policy_doc: _Doc) -> dict[str, Any]:
    return {
        "policy": comparison.text("policy"),
        "label": _label(comparison.text("policy")),
        "scheduled": comparison.num("scheduled"),
        "scheduled_cne": comparison.num("scheduled_cne"),
        "scheduled_or": comparison.num("scheduled_or"),
        "q1_scheduled": comparison.num("q1_scheduled"),
        "ges_obligated": policy_doc.num("ges.obligated"),
        "ges_met": comparison.num("ges_met"),
        "ges_unmet": comparison.num("ges_unmet"),
        "ges_on_time": comparison.num("ges_on_time"),
        "overbooked_flags": comparison.num("overbooked_flags"),
        "sum_coef": comparison.num("sum_coef"),
        "solver_status": comparison.text("solver_status"),
        "gap": comparison.req("gap"),
    }


def _phase_counts(status_by_phase: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for phase in sorted(status_by_phase):
        counts = status_by_phase[phase]
        rows.append(
            {
                "phase": phase,
                "counts": {k: counts[k] for k in sorted(counts)},
                "total": sum(counts.values()),
            }
        )
    return rows


def _delta(a: dict[str, Any], b: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        diff = a[k] - b[k]
        out[k] = {"diff": diff, "relative": (diff / b[k]) if b[k] else None}
    return out


def _scheduler(doc: _Doc) -> dict[str, Any]:
    run = doc.sub("run")
    comparison_rows = doc.items("comparison")
    policies_doc = doc.sub("policies")
    plan_rows: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(comparison_rows):
        comp = _Doc(raw, doc.name, f"comparison[{i}]")
        name = comp.text("policy")
        plan_rows[name] = _plan_row(comp, policies_doc.sub(name))
    for needed in ("fifo", "priority", "optimized"):
        if needed not in plan_rows:
            raise FactsError(f"{doc.name}: falta la política '{needed}' en comparison")
    order = ("fifo", "priority", "optimized")
    opt = policies_doc.sub("optimized")
    wall_plan = opt.num("solver.time.plan.wall_time_s")
    wall_discarded = opt.num("solver.time.discarded_first_pass.wall_time_s")
    capacity = opt.items("capacity_by_week")
    delta_keys = ("scheduled", "q1_scheduled", "ges_met", "ges_on_time", "sum_coef")
    warnings = [str(w) for w in opt.items("warnings")]
    equity_doc = {name: policies_doc.sub(name).items("equity") for name in order}
    return {
        "run": {k: run.req(k) for k in ("id", "as_of", "scenario", "seed", "size")},
        "horizon_start": opt.text("horizon_start"),
        "horizon_end_exclusive": opt.text("horizon_end_exclusive"),
        "horizon_weeks": opt.num("config.horizon_weeks"),
        "time_limit_s": opt.num("config.time_limit_s"),
        "noshow_model_version": opt.text("noshow_model_version"),
        "code_version": opt.text("code_version"),
        "review_status": opt.text("review_status"),
        "rows": [plan_rows[p] for p in order],
        "delta_optimized_vs_priority": _delta(
            plan_rows["optimized"], plan_rows["priority"], delta_keys
        ),
        "delta_optimized_vs_fifo": _delta(plan_rows["optimized"], plan_rows["fifo"], delta_keys),
        "delta_priority_vs_fifo": _delta(plan_rows["priority"], plan_rows["fifo"], delta_keys),
        "capacity": {
            "cne_units": sum(w["cne_units"] for w in capacity),
            "or_minutes": sum(w["or_minutes"] for w in capacity),
            "cne_sessions": sum(w["cne_sessions"] for w in capacity),
            "or_blocks": sum(w["or_blocks"] for w in capacity),
        },
        "optimized": {
            "entries_waiting": opt.num("summary.entries_waiting"),
            "candidates": opt.num("summary.candidates"),
            "not_candidate": opt.num("summary.not_candidate"),
            "added_by_overbooking": opt.num("summary.added_by_overbooking"),
            "overbooked_flags": opt.num("summary.overbooked_flags"),
            "by_status": opt.req("summary.by_status"),
            "ges_unmet_by_cause": opt.req("ges.unmet_by_cause"),
            "overbooking_alpha": opt.num("overbooking.alpha"),
            "overbooking_blocks": len(opt.items("overbooking.blocks")),
            "overbooking_max_risk_exact": opt.num("overbooking.max_risk_exact"),
            "solver_status": opt.text("solver.status"),
            "subproblems": len(opt.items("solver.subproblems")),
            "status_by_phase": _phase_counts(opt.req("solver.status_by_phase")),
            "gap_by_phase": opt.req("solver.gap_by_phase"),
            "wall_time_plan_s": wall_plan,
            "wall_time_discarded_s": wall_discarded,
            "wall_time_total_s": wall_plan + wall_discarded,
            "deterministic_time_plan": opt.num("solver.time.plan.deterministic_time"),
            "frontier_reached": len(opt.items("frontier.reached")),
            "frontier_still_reached": len(opt.items("frontier.still_reached")),
        },
        "warnings": warnings,
        "equity_by_policy": equity_doc,
        "min_group_n": opt.num("config.group_limits.min_group_n"),
    }


# ------------------------------------------------------------------ Equidad del programador


def _widest_scheduled_gap(
    groups: list[dict[str, Any]], reference: dict[str, Any]
) -> dict[str, Any]:
    """Grupo con el mayor desvío (con signo) de la tasa de agendamiento respecto del total."""
    worst = max(
        groups,
        key=lambda g: (
            abs(g["scheduled_rate"]["optimized"] - reference["scheduled_rate"]),
            g["value"],
        ),
    )
    return {
        "value": worst["value"],
        "gap": worst["scheduled_rate"]["optimized"] - reference["scheduled_rate"],
    }


def _sched_equity(
    scheduler_equity: dict[str, list[dict[str, Any]]], min_n: float
) -> dict[str, Any]:
    policies = ("fifo", "priority", "optimized")
    indexed: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for policy in policies:
        by_dim: dict[str, dict[str, dict[str, Any]]] = {}
        for row in scheduler_equity[policy]:
            by_dim.setdefault(row["dimension"], {})[str(row["value"])] = row
        indexed[policy] = by_dim
    for policy in policies:
        if "all" not in indexed[policy] or "all" not in indexed[policy]["all"]:
            raise FactsError(f"plan canónico: falta la fila 'all' de equidad de {policy}")
    reference = {p: indexed[p]["all"]["all"] for p in policies}
    dimensions = []
    for dim in SCHED_GROUP_DIMENSIONS:
        if dim not in indexed["optimized"]:
            raise FactsError(f"plan canónico: falta la dimensión de equidad {dim}")
        values = sorted(
            v for v, row in indexed["optimized"][dim].items() if row["entries"] >= min_n
        )
        total_groups = len(indexed["optimized"][dim])
        groups: list[dict[str, Any]] = []
        for v in values:
            rows = {p: indexed[p][dim][v] for p in policies}
            opt = rows["optimized"]
            groups.append(
                {
                    "value": v,
                    "entries": opt["entries"],
                    "scheduled_rate": {p: rows[p]["scheduled_rate"] for p in policies},
                    "delta_vs_priority": opt["scheduled_rate"] - rows["priority"]["scheduled_rate"],
                    "delta_vs_fifo": opt["scheduled_rate"] - rows["fifo"]["scheduled_rate"],
                    "exposure_share": opt["exposure_share"],
                    "exposure_gap": opt["exposure_share"]
                    - reference["optimized"]["exposure_share"],
                    "flagged_share": opt["flagged_share"],
                    "mean_risk_exposed": opt["mean_risk_exposed"],
                }
            )
        if not groups:
            raise FactsError(
                f"plan canónico: la dimensión {dim} no tiene grupos con entradas suficientes"
            )
        most_exposed = max(groups, key=lambda g: (g["exposure_share"], g["value"]))
        worst_delta = min(groups, key=lambda g: (g["delta_vs_priority"], g["value"]))
        widest_exposure = max(groups, key=lambda g: (abs(g["exposure_gap"]), g["value"]))
        if len(groups) <= FULL_LISTING_MAX:
            shown = groups
        else:
            shown = sorted(groups, key=lambda g: (-g["exposure_share"], g["value"]))[:LISTING_LIMIT]
        worse = [g for g in groups if g["delta_vs_priority"] < 0]
        dimensions.append(
            {
                "dimension": dim,
                "n_groups_total": total_groups,
                "n_groups": len(groups),
                "min_group_n": min_n,
                "groups": groups,
                "shown": shown,
                "truncated": len(shown) < len(groups),
                "most_exposed": most_exposed,
                "widest_exposure": widest_exposure,
                "worst_delta_vs_priority": worst_delta,
                "n_worse_than_priority": len(worse),
                "n_better_than_priority": sum(1 for g in groups if g["delta_vs_priority"] > 0),
                "widest_scheduled_gap": _widest_scheduled_gap(groups, reference["optimized"]),
            }
        )
    return {
        "reference": {
            p: {
                "scheduled_rate": reference[p]["scheduled_rate"],
                "exposure_share": reference[p]["exposure_share"],
                "flagged_share": reference[p]["flagged_share"],
                "mean_risk_exposed": reference[p]["mean_risk_exposed"],
            }
            for p in policies
        },
        "dimensions": dimensions,
    }


# ------------------------------------------------------------------ Modelo de inasistencias


def _noshow(doc: _Doc) -> dict[str, Any]:
    primary = doc.text("selection.primary")
    metrics_doc = doc.sub("test_metrics")
    models = []
    for name in sorted(metrics_doc.data):
        m = metrics_doc.sub(name)
        models.append(
            {
                "model": name,
                "is_primary": name == primary,
                "auc": m.num("auc"),
                "brier": m.num("brier"),
                "ece": m.num("ece"),
                "log_loss": m.num("log_loss"),
                "mean_predicted": m.num("mean_predicted"),
                "observed_rate": m.num("observed_rate"),
            }
        )
    if primary not in metrics_doc.data:
        raise FactsError(f"{doc.name}: selection.primary '{primary}' no está en test_metrics")
    curve = [
        {
            k: _Doc(p, doc.name, f"test_metrics.{primary}.calibration_curve[{i}]").num(k)
            for k in ("mean_predicted", "observed_rate", "n")
        }
        for i, p in enumerate(metrics_doc.sub(primary).items("calibration_curve"))
    ]
    oracle = doc.sub("oracle_reference.metrics")
    fairness_doc = doc.sub("fairness")
    min_n = fairness_doc.num("min_n")
    dims = []
    for dim in ("age_group", "care_type", "insurance", "health_service_code", "commune_code"):
        block = fairness_doc.sub(dim)
        groups: list[dict[str, Any]] = []
        for i, raw in enumerate(block.items("groups")):
            g = _Doc(raw, doc.name, f"fairness.{dim}.groups[{i}]")
            groups.append(
                {
                    "group": g.text("group"),
                    "n": g.num("n"),
                    "observed_rate": g.num("observed_rate"),
                    "mean_predicted": g.num("mean_predicted"),
                    "mean_true_prob": g.num("mean_true_prob"),
                    "gap": g.num("gap"),
                    "gap_vs_truth": g.num("gap_vs_truth"),
                }
            )
        groups.sort(key=lambda g: (-abs(g["gap_vs_truth"]), g["group"]))
        if len(groups) <= FULL_LISTING_MAX:
            shown = sorted(groups, key=lambda g: g["group"])
        else:
            shown = groups[:LISTING_LIMIT]
        note = block.data.get("note")
        dims.append(
            {
                "dimension": dim,
                "n_groups": len(groups),
                "n_groups_total": block.data.get("n_groups_total", len(groups)),
                "max_abs_gap_vs_truth": block.num("max_abs_gap_vs_truth"),
                "groups": groups,
                "shown": shown,
                "truncated": len(shown) < len(groups),
                "worst": groups[0],
                "note": note if isinstance(note, str) else None,
            }
        )
    excluded = doc.sub("features.excluded").data
    split = doc.sub("split")
    return {
        "model_version": doc.text("model_version"),
        "primary": primary,
        "primary_is_calibrated": bool(doc.req("selection.primary_is_calibrated")),
        "selection_criterion": doc.text("selection.criterion"),
        "brier_calibration_set": doc.req("selection.brier_calibration_set"),
        "calibration": {
            "method": doc.text("calibration.method"),
            "events": doc.num("calibration.calibration_events"),
            "rule": doc.text("calibration.rule"),
        },
        "caveat": doc.text("caveat"),
        "seed": doc.num("config.seed"),
        "n_boot": doc.num("config.n_boot"),
        "data_version": {
            k: doc.req(f"data_version.{k}")
            for k in ("run_id", "size", "seed", "scenario", "as_of", "generator_version")
        },
        "split": {
            part: {
                "n": split.num(f"{part}.n"),
                "first": split.text(f"{part}.first"),
                "last": split.text(f"{part}.last"),
                "no_show_rate": split.num(f"{part}.no_show_rate"),
            }
            for part in ("train", "calibration", "test")
        },
        "models": models,
        "primary_metrics": next(m for m in models if m["is_primary"]),
        "curve": curve,
        "oracle": {k: oracle.num(k) for k in ("auc", "brier", "ece", "log_loss")},
        "vs_baseline": {
            "brier_difference": doc.num("primary_vs_baseline.brier_difference"),
            "ci95_low": doc.num("primary_vs_baseline.ci95_low"),
            "ci95_high": doc.num("primary_vs_baseline.ci95_high"),
            "n_boot": doc.num("primary_vs_baseline.n_boot"),
            "resampling_unit": doc.text("primary_vs_baseline.resampling_unit"),
            "resampling_unit_label": RESAMPLING_LABELS.get(
                doc.text("primary_vs_baseline.resampling_unit"),
                doc.text("primary_vs_baseline.resampling_unit"),
            ),
            "beats_baseline_brier": bool(doc.req("primary_vs_baseline.beats_baseline_brier")),
            "significant_at_95": bool(doc.req("primary_vs_baseline.significant_at_95")),
        },
        "features": {
            "categorical": [str(x) for x in doc.items("features.categorical")],
            "numeric": [str(x) for x in doc.items("features.numeric")],
            "dropped_constant": [str(x) for x in doc.items("features.constant_in_train_dropped")],
            "excluded": [{"name": k, "reason": str(excluded[k])} for k in sorted(excluded)],
            "proxy_risks": [
                {"name": k, "reason": str(v)}
                for k, v in sorted(doc.sub("features.proxy_risks").data.items())
            ],
        },
        "fairness": {
            "description": doc.text("fairness.description"),
            "min_n": min_n,
            "dimensions": dims,
        },
    }


# ------------------------------------------------------------------ Benchmark del programador


def _bench(doc: _Doc) -> dict[str, Any]:
    cells = []
    variants_doc = doc.sub("variants")
    variant_names = list(variants_doc.data)
    for i, raw in enumerate(doc.items("cells")):
        c = _Doc(raw, doc.name, f"cells[{i}]")
        size = int(c.num("size"))
        weeks = int(c.num("horizon_weeks"))
        full = c.sub("optimized.all")
        priority = c.sub("greedy.priority")
        fifo = c.sub("greedy.fifo")
        runs = [float(x) for x in full.items("wall_time_s_runs")]
        if not runs:
            raise FactsError(f"{doc.name}: cells[{i}].optimized.all.wall_time_s_runs está vacío")
        keys = ("scheduled", "q1_scheduled", "ges_met", "ges_on_time", "sum_coef")
        optimized_row = {k: full.num(k) for k in keys}
        priority_row = {k: priority.num(k) for k in keys}
        fifo_row = {k: fifo.num(k) for k in keys}
        solver = full.sub("solver")
        cells.append(
            {
                "size": size,
                "weeks": weeks,
                "run_id": c.text("data.run_id"),
                "calibration_passed": bool(c.req("data.calibration_passed")),
                "calibration_strict_failed": [
                    str(x) for x in c.items("data.calibration_strict_failed")
                ],
                "entries": c.num("problem.entries"),
                "entries_with_pairs": c.num("problem.entries_with_pairs"),
                "pairs_compatible": c.num("problem.pairs_compatible"),
                "ges_obligated": c.num("problem.ges_obligated"),
                "candidates": solver.num("candidates"),
                "pairs_in_model": solver.num("pairs_in_model"),
                "subproblems": solver.num("subproblems"),
                "largest_subproblem_pairs": solver.num("largest_subproblem_pairs"),
                "status": solver.text("status"),
                "gap": solver.req("gap"),
                "wall_time_s_median": _median(runs),
                "wall_time_s_runs": runs,
                "repeats": len(runs),
                "frontier_reached": len(solver.items("frontier.reached")),
                "frontier_still_reached": len(solver.items("frontier.still_reached")),
                "optimized": optimized_row,
                "priority": priority_row,
                "fifo": fifo_row,
                "delta_vs_priority": {k: optimized_row[k] - priority_row[k] for k in keys},
                "delta_vs_fifo": {k: optimized_row[k] - fifo_row[k] for k in keys},
                "not_worse_lexicographic": bool(
                    c.req("optimized_vs_priority.optimized_not_worse_lexicographic")
                ),
                "without_overbooking_not_worse_lexicographic": bool(
                    c.req(
                        "optimized_without_overbooking_vs_priority.optimized_not_worse_lexicographic"
                    )
                ),
                "variants": _bench_variants(c, variant_names),
            }
        )
    cells.sort(key=lambda c: (c["size"], c["weeks"]))
    largest = cells[-1]
    return {
        "generated_at": doc.text("generated_at"),
        "code_version": doc.text("code_version"),
        "seed": doc.num("seed"),
        "scenario": doc.text("scenario"),
        "time_limit_s": doc.num("time_limit_s"),
        "repeats_all": doc.num("repeats_all"),
        "machine": {
            k: doc.req(f"machine.{k}")
            for k in ("cpu_count", "machine", "ortools", "platform", "python")
        },
        "num_workers": doc.num("config_defaults.solver.num_workers"),
        # En modo determinista CP-SAT corre con un hilo aunque num_workers diga otra cosa
        # (formulación §8.5); el informe muestra los hilos que de verdad se usaron.
        "deterministic": _deterministic(doc),
        "threads": 1 if _deterministic(doc) else doc.num("config_defaults.solver.num_workers"),
        "cells": cells,
        "sizes": sorted({c["size"] for c in cells}),
        "horizons": sorted({c["weeks"] for c in cells}),
        "variants": [
            {"name": v, "label": VARIANT_LABELS.get(v, v), "flags": variants_doc.data[v]}
            for v in variant_names
        ],
        "largest_cell": {"size": largest["size"], "weeks": largest["weeks"]},
        "any_calibration_failed": any(not c["calibration_passed"] for c in cells),
        "any_not_worse_false": any(not c["not_worse_lexicographic"] for c in cells),
        "hit_time_limit_cells": [
            {"size": c["size"], "weeks": c["weeks"], "status": c["status"]}
            for c in cells
            if c["status"] != "OPTIMAL"
        ],
    }


def _bench_variants(cell: _Doc, names: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in names:
        v = cell.sub(f"optimized.{name}")
        runs = [float(x) for x in v.items("wall_time_s_runs")]
        if not runs:
            raise FactsError(
                f"{cell.name}: {cell.prefix}.optimized.{name}.wall_time_s_runs está vacío"
            )
        out.append(
            {
                "variant": name,
                "label": VARIANT_LABELS.get(name, name),
                "status": v.text("solver.status"),
                "gap": v.req("solver.gap"),
                "wall_time_s_median": _median(runs),
                "repeats": len(runs),
                "scheduled": v.num("scheduled"),
                "sum_coef": v.num("sum_coef"),
            }
        )
    return out


# ------------------------------------------------------------------ Simulación


def _reading(stat: _Doc) -> str:
    """Lectura de una diferencia pareada: ``better``, ``worse``, ``unclear`` o ``context``."""
    direction = stat.req("direction")
    if direction is None:
        return "context"
    low, high = stat.num("ci95_low"), stat.num("ci95_high")
    if low > 0 or high < 0:
        mean = stat.num("mean_diff")
        return "better" if mean * direction > 0 else "worse"
    return "unclear"


def _simulation_comparisons(doc: _Doc, n_replicas: int) -> list[dict[str, Any]]:
    comps = doc.sub("comparisons")
    for mirrored in MIRRORED_COMPARISON:
        if mirrored not in comps.data:
            raise FactsError(f"{doc.name}: falta la comparación '{mirrored}'")
    a, b = comps.sub(MIRRORED_COMPARISON[0]), comps.sub(MIRRORED_COMPARISON[1])
    for key, _, _ in SIM_METRICS:
        if abs(a.num(f"{key}.mean_diff") + b.num(f"{key}.mean_diff")) > 1e-9 * max(
            1.0, abs(b.num(f"{key}.mean_diff"))
        ):
            raise FactsError(
                f"{doc.name}: {MIRRORED_COMPARISON[0]} no es el espejo de "
                f"{MIRRORED_COMPARISON[1]} en {key}"
            )
    out = []
    for name in SIM_COMPARISONS:
        pair = comps.sub(name)
        head, base = name.split("_vs_")
        rows = []
        for key, label, kind in SIM_METRICS:
            s = pair.sub(key)
            reading = _reading(s)
            rows.append(
                {
                    "metric": key,
                    "label": label,
                    "kind": kind,
                    "stat": {
                        "mean": s.num("mean_diff"),
                        "ci95_low": s.num("ci95_low"),
                        "ci95_high": s.num("ci95_high"),
                    },
                    "direction": s.req("direction"),
                    "better_in": s.req("better_in"),
                    "reading": reading,
                }
            )
        out.append(
            {
                "name": name,
                "policy": head,
                "base": base,
                "policy_label": _label(head),
                "base_label": _label(base),
                "n_replicas": n_replicas,
                "rows": rows,
                "n_better": sum(1 for r in rows if r["reading"] == "better"),
                "n_worse": sum(1 for r in rows if r["reading"] == "worse"),
                "n_unclear": sum(1 for r in rows if r["reading"] == "unclear"),
                "worse_labels": [r["label"] for r in rows if r["reading"] == "worse"],
            }
        )
    return out


def _deviation_key(
    policy: str, field: str, reference: float
) -> Callable[[dict[str, Any]], tuple[float, str]]:
    """Clave de orden: desvío absoluto de un grupo respecto de la referencia (y el nombre)."""

    def key(group: dict[str, Any]) -> tuple[float, str]:
        return abs(group["by_policy"][policy][field] - reference), str(group["value"])

    return key


def _attention_key(policy: str) -> Callable[[dict[str, Any]], tuple[float, str]]:
    """Clave de orden: tasa de atención de un grupo (y el nombre, para desempatar)."""

    def key(group: dict[str, Any]) -> tuple[float, str]:
        return group["by_policy"][policy]["attention_rate"], str(group["value"])

    return key


def _simulation_groups(doc: _Doc, policies: list[str]) -> list[dict[str, Any]]:
    replicas = doc.items("replicas")
    out = []
    for dim in SIM_GROUP_DIMENSIONS:
        acc: dict[str, dict[str, dict[str, list[float]]]] = {}
        for ri, rep in enumerate(replicas):
            rep_doc = _Doc(rep, doc.name, f"replicas[{ri}]")
            for policy in policies:
                blocks = rep_doc.items(f"policies.{policy}.groups")
                block = next((b for b in blocks if b.get("dimension") == dim), None)
                if block is None:
                    raise FactsError(
                        f"{doc.name}: replicas[{ri}].policies.{policy}.groups "
                        f"no tiene la dimensión {dim}"
                    )
                for gi, g in enumerate(block["groups"]):
                    gd = _Doc(g, doc.name, f"replicas[{ri}].policies.{policy}.groups[{dim}][{gi}]")
                    slot = acc.setdefault(gd.text("value"), {}).setdefault(policy, {})
                    for field in SIM_GROUP_FIELDS:
                        slot.setdefault(field, []).append(float(gd.num(field)))
                    slot.setdefault("wait_median", []).append(float(gd.num("wait_attended.median")))
        n_rep = len(replicas)
        groups: list[dict[str, Any]] = []
        for value in sorted(acc):
            per_policy = acc[value]
            if set(per_policy) != set(policies) or any(
                len(per_policy[p]["entries"]) != n_rep for p in policies
            ):
                continue  # grupo ausente en alguna réplica o política: no es comparable
            by_policy = {
                p: {f: statistics.fmean(v) for f, v in per_policy[p].items()} for p in policies
            }
            groups.append(
                {
                    "value": value,
                    "entries": by_policy[policies[0]]["entries"],
                    "by_policy": by_policy,
                }
            )
        if not groups:
            raise FactsError(
                f"{doc.name}: la dimensión {dim} no tiene grupos comparables entre réplicas"
            )
        reference: dict[str, dict[str, float]] = {}
        gaps: dict[str, dict[str, Any]] = {}
        for p in policies:
            total = sum(g["entries"] for g in groups)
            reference[p] = {
                f: sum(g["entries"] * g["by_policy"][p][f] for g in groups) / total
                for f in ("attention_rate", "overbooking_exposure", "no_show_realized_rate")
            }
            gaps[p] = {}
            for f in ("attention_rate", "overbooking_exposure"):
                worst = max(groups, key=_deviation_key(p, f, reference[p][f]))
                gaps[p][f] = {
                    "group": worst["value"]
                    if abs(worst["by_policy"][p][f] - reference[p][f]) > 0
                    else None,
                    "gap": worst["by_policy"][p][f] - reference[p][f],
                    "entries": worst["entries"],
                }
        exposure_policy = "optimized_overbooking"
        if exposure_policy not in policies:
            raise FactsError(f"{doc.name}: config.policies no incluye {exposure_policy}")
        most_exposed = max(
            groups,
            key=lambda g: (g["by_policy"][exposure_policy]["overbooking_exposure"], g["value"]),
        )
        lowest_attention = {p: min(groups, key=_attention_key(p)) for p in policies}
        if len(groups) <= FULL_LISTING_MAX:
            shown = groups
        else:
            shown = sorted(
                groups,
                key=lambda g: (
                    -g["by_policy"][exposure_policy]["overbooking_exposure"],
                    g["value"],
                ),
            )[:LISTING_LIMIT]
        out.append(
            {
                "dimension": dim,
                "n_groups": len(groups),
                "groups": groups,
                "shown": shown,
                "truncated": len(shown) < len(groups),
                "reference": reference,
                "gaps": gaps,
                "most_exposed": {
                    "value": most_exposed["value"],
                    "entries": most_exposed["entries"],
                    "exposure": most_exposed["by_policy"][exposure_policy]["overbooking_exposure"],
                    "gap": most_exposed["by_policy"][exposure_policy]["overbooking_exposure"]
                    - reference[exposure_policy]["overbooking_exposure"],
                },
                "lowest_attention": {
                    p: {
                        "value": g["value"],
                        "entries": g["entries"],
                        "attention_rate": g["by_policy"][p]["attention_rate"],
                        "gap": g["by_policy"][p]["attention_rate"] - reference[p]["attention_rate"],
                    }
                    for p, g in lowest_attention.items()
                },
            }
        )
    return out


def _simulation(doc: _Doc, canonical_size: int) -> dict[str, Any]:
    policies = [str(p) for p in doc.items("config.policies")]
    seeds = [int(s) for s in doc.items("replica_seeds")]
    n_replicas = len(seeds)
    aggregate = doc.sub("aggregate")
    metrics_rows = []
    for key, label, kind in SIM_METRICS:
        stats = {}
        for p in policies:
            s = aggregate.sub(p).sub(key)
            if int(s.num("n")) != n_replicas:
                raise FactsError(f"{doc.name}: aggregate.{p}.{key}.n no coincide con las réplicas")
            stats[p] = {
                "mean": s.num("mean"),
                "ci95_low": s.num("ci95_low"),
                "ci95_high": s.num("ci95_high"),
            }
        metrics_rows.append({"metric": key, "label": label, "kind": kind, "by_policy": stats})
    coverage = doc.sub("supply_coverage")
    supply = []
    for care in ("consultation", "surgery"):
        c = coverage.sub(care)
        supply.append(
            {
                "care_type": care,
                **{
                    k: c.num(k)
                    for k in (
                        "blocks",
                        "cells",
                        "cells_with_block",
                        "stock",
                        "stock_in_cells_with_block",
                    )
                },
                "cells_share": c.num("cells_with_block") / c.num("cells"),
                "stock_share": c.num("stock_in_cells_with_block") / c.num("stock"),
            }
        )
    scheduler_by_policy = []
    for p in policies:
        statuses: dict[str, dict[str, int]] = {}
        max_gap: float | None = None
        plans = 0
        wall = 0.0
        for ri, rep in enumerate(doc.items("replicas")):
            s = _Doc(rep, doc.name, f"replicas[{ri}]").sub(f"policies.{p}.scheduler")
            plans += int(s.num("plans"))
            wall += float(s.num("wall_time_total"))
            gap = s.req("max_gap")
            if gap is not None:
                max_gap = gap if max_gap is None else max(max_gap, gap)
            for phase, counts in s.sub("status_by_phase").data.items():
                slot = statuses.setdefault(phase, {})
                for status, n in counts.items():
                    slot[status] = slot.get(status, 0) + n
        scheduler_by_policy.append(
            {
                "policy": p,
                "label": _label(p),
                "plans": plans,
                "max_gap": max_gap,
                "wall_time_total_s": wall,
                "status_by_phase": _phase_counts(statuses),
                "uses_solver": bool(statuses),
            }
        )
    run = doc.sub("run")
    timing = doc.sub("timing")
    return {
        "run": {k: run.req(k) for k in ("id", "as_of", "scenario", "seed", "size")},
        "is_canonical_size": run.num("size") == canonical_size,
        "canonical_size": canonical_size,
        "generated_at": doc.text("generated_at"),
        "code_version": doc.text("code_version"),
        "noshow_model_version": doc.text("noshow_model_version"),
        "truth_source": doc.text("truth_source"),
        "config": {
            k: doc.req(f"config.{k}")
            for k in (
                "weeks",
                "horizon_weeks",
                "commit_weeks",
                "time_limit_s",
                "capacity_multiplier",
                "abandon_weekly_rate",
                "max_no_shows",
                "overbooking_alpha",
                "match_level",
            )
        },
        "policies": policies,
        "policy_labels": {p: _label(p) for p in policies},
        "replica_seeds": seeds,
        "n_replicas": n_replicas,
        "metrics": metrics_rows,
        "comparisons": _simulation_comparisons(doc, n_replicas),
        "supply": supply,
        "scheduler": scheduler_by_policy,
        "timing": [
            {
                "policy": p,
                "label": _label(p),
                "mean_s": timing.num(f"{p}.mean_s"),
                "total_s": timing.num(f"{p}.total_s"),
            }
            for p in policies
        ],
        "limitations": [str(x) for x in doc.items("limitations")],
        "groups": _simulation_groups(doc, policies),
    }


# ------------------------------------------------------------------ Ensamblado


def _provenance(
    calibration: dict[str, Any],
    noshow: _Doc,
    schedule: dict[str, Any],
    bench: dict[str, Any],
    sim: dict[str, Any],
    names: dict[str, str],
    results_commit: str | None,
) -> dict[str, Any]:
    files = [
        {
            "key": "calibration",
            "file": names["calibration"],
            "generated_at": None,
            "code_version": None,
            "run_ids": [calibration["run_id"]],
            "sizes": [calibration["size"]],
            "seed": calibration["seed"],
        },
        {
            "key": "noshow",
            "file": names["noshow"],
            "generated_at": None,
            "code_version": noshow.text("model_version"),
            "run_ids": [noshow.text("data_version.run_id")],
            "sizes": [noshow.num("data_version.size")],
            "seed": noshow.num("config.seed"),
        },
        {
            "key": "schedule",
            "file": names["schedule"],
            "generated_at": None,
            "code_version": schedule["code_version"],
            "run_ids": [schedule["run"]["id"]],
            "sizes": [schedule["run"]["size"]],
            "seed": schedule["run"]["seed"],
        },
        {
            "key": "benchmark",
            "file": names["benchmark"],
            "generated_at": bench["generated_at"],
            "code_version": bench["code_version"],
            "run_ids": sorted({c["run_id"] for c in bench["cells"]}),
            "sizes": bench["sizes"],
            "seed": bench["seed"],
        },
        {
            "key": "simulation",
            "file": names["simulation"],
            "generated_at": sim["generated_at"],
            "code_version": sim["code_version"],
            "run_ids": [sim["run"]["id"]],
            "sizes": [sim["run"]["size"]],
            "seed": sim["run"]["seed"],
        },
    ]
    return {"files": files, "results_commit": results_commit}


def _method(
    calibration: dict[str, Any],
    noshow: dict[str, Any],
    schedule: dict[str, Any],
    bench: dict[str, Any],
    sim: dict[str, Any],
) -> dict[str, Any]:
    return {
        "synth": {"size": calibration["size"], "seed": calibration["seed"]},
        "train": {
            "size": noshow["data_version"]["size"],
            "seed": noshow["data_version"]["seed"],
            "scenario": noshow["data_version"]["scenario"],
        },
        "schedule": {
            "weeks": schedule["horizon_weeks"],
            "size": schedule["run"]["size"],
            "seed": schedule["run"]["seed"],
            "scenario": schedule["run"]["scenario"],
        },
        "bench": {
            "sizes": bench["sizes"],
            "horizons": bench["horizons"],
            "seed": bench["seed"],
            "scenario": bench["scenario"],
            "time_limit_s": bench["time_limit_s"],
            "repeats": bench["repeats_all"],
        },
        "simulate": {
            "size": sim["run"]["size"],
            "seed": sim["run"]["seed"],
            "scenario": sim["run"]["scenario"],
            "weeks": sim["config"]["weeks"],
            "replica_seeds": sim["replica_seeds"],
            "horizon_weeks": sim["config"]["horizon_weeks"],
            "time_limit_s": sim["config"]["time_limit_s"],
            "capacity_multiplier": sim["config"]["capacity_multiplier"],
            "abandon_weekly_rate": sim["config"]["abandon_weekly_rate"],
            "policies": sim["policies"],
        },
    }


def load_facts(results_dir: Path, repo_root: Path) -> dict[str, Any]:
    """Lee ``results_dir`` y las fuentes versionadas y devuelve el diccionario de hechos.

    Claves de primer nivel: ``disclaimer``, ``labels``, ``provenance``, ``context``,
    ``calibration``, ``priority``, ``noshow``, ``scheduler``, ``benchmark``, ``simulation``,
    ``equity``, ``limitations`` y ``method``. Levanta ``FactsError`` si falta un archivo o un
    campo.
    """
    results_dir = Path(results_dir)
    repo_root = Path(repo_root)
    schedule_path = _find_schedule(results_dir)
    schedule_doc = _read(schedule_path)
    schedule = _scheduler(schedule_doc)
    calibration_path = _find_calibration(results_dir, schedule["run"]["id"])
    calibration_match = CALIBRATION_NAME.match(calibration_path.name)
    if calibration_match is None:
        raise FactsError(
            f"{calibration_path.name}: el nombre no sigue "
            "synthetic_calibration_<escenario>_seed<N>_n<N>.json"
        )
    calibration = _calibration(_read(calibration_path), calibration_match)
    noshow_doc = _read(results_dir / NOSHOW_FILE)
    noshow = _noshow(noshow_doc)
    bench = _bench(_read(results_dir / BENCHMARK_FILE))
    sim = _simulation(_read(results_dir / SIMULATION_FILE), schedule["run"]["size"])

    if noshow["data_version"]["run_id"] != schedule["run"]["id"]:
        raise FactsError(
            f"{NOSHOW_FILE}: el modelo se entrenó con la corrida "
            f"{noshow['data_version']['run_id']} "
            f"y el plan canónico usa {schedule['run']['id']}"
        )

    first_opt = schedule_doc.sub("policies.optimized")
    priority = _priority_rules(first_opt.text("rules_digest"), first_opt.text("rules_version"))
    assumptions = load_assumptions()
    unverified = assumptions.unverified()
    names = {
        "calibration": calibration_path.name,
        "noshow": NOSHOW_FILE,
        "schedule": schedule_path.name,
        "benchmark": BENCHMARK_FILE,
        "simulation": SIMULATION_FILE,
    }
    equity_sched = _sched_equity(schedule["equity_by_policy"], schedule["min_group_n"])
    del schedule["equity_by_policy"]
    return {
        "disclaimer": DISCLAIMER,
        "labels": {"policies": dict(POLICY_LABELS)},
        "provenance": _provenance(
            calibration,
            noshow_doc,
            schedule,
            bench,
            sim,
            names,
            _results_commit(results_dir, repo_root),
        ),
        "context": _context(schedule["run"]["as_of"]),
        "calibration": calibration,
        "priority": priority,
        "noshow": noshow,
        "scheduler": schedule,
        "benchmark": bench,
        "simulation": sim,
        "equity": {
            "listing_limit": LISTING_LIMIT,
            "scheduler": equity_sched,
            "simulation": sim["groups"],
        },
        "limitations": {
            "unverified_assumptions": unverified,
            "n_unverified": len(unverified),
            "n_parameters": len(assumptions.parameters) + len(assumptions.ges_problem_map),
            "simulation": sim["limitations"],
            "scheduler_warnings": schedule["warnings"],
            "calibration_notes": calibration["notes"],
            "noshow_caveat": noshow["caveat"],
        },
        "method": _method(calibration, noshow, schedule, bench, sim),
    }


def _deterministic(doc: _Doc) -> bool:
    value = doc.req("config_defaults.solver.deterministic")
    if not isinstance(value, bool):
        raise doc._fail("config_defaults.solver.deterministic", "se esperaba un booleano")
    return value
