"""Resultados mínimos y sintéticos para probar ``load_facts`` sin depender de ``results/``.

Los valores son inventados (no son datos de pacientes ni resultados reales); solo reproducen la
estructura que ``reports.facts`` lee.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from reports.facts import SIM_COMPARISONS, SIM_METRICS

RUN_ID = "11111111-2222-3333-4444-555555555555"
SIM_RUN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
DISCLAIMER = (
    "Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas "
    "ni de gestión real sin validación institucional."
)
SCHED_POLICIES = ("fifo", "priority", "optimized")
SIM_POLICIES = ("fifo", "priority", "optimized", "optimized_overbooking")


def _calibration() -> dict[str, Any]:
    check = {
        "name": "C1.tipo",
        "group": "C1",
        "metric": "tvd",
        "observed": 0.001,
        "target": 0.0,
        "tolerance": 0.01,
        "n": 1000,
        "passed": True,
        "severity": "strict",
        "detail": ["peor grupo: tipo"],
    }
    failing = {
        **check,
        "name": "C5.x",
        "group": "C5",
        "passed": False,
        "severity": "soft",
        "target": None,
        "tolerance": None,
        "detail": [],
    }
    return {
        "run_id": RUN_ID,
        "digest": "d" * 64,
        "checks": [check, failing],
        "passed": True,
        "summary": {"strict_passed": 1, "strict_failed": 0, "soft_failed": 1, "skipped": 0},
        "notes": ["Una nota de calibración", DISCLAIMER],
    }


def _equity_rows(policy: str) -> list[dict[str, Any]]:
    exposed = policy == "optimized"
    rows = []
    for dim, values in (
        ("age_group", ["0_14", "65_plus"]),
        ("insurance", ["fonasa_a", "other"]),
        ("commune_code", ["01101", "01107"]),
    ):
        for i, value in enumerate(values):
            rows.append(
                {
                    "dimension": dim,
                    "value": value,
                    "entries": 100 + 10 * i,
                    "candidates": 50,
                    "scheduled": 20 + i,
                    "scheduled_cne": 18,
                    "scheduled_rate": 0.2 + 0.01 * i + (0.02 if exposed else 0.0),
                    "exposure_share": 0.3 + 0.1 * i if exposed else 0.0,
                    "flagged_share": 0.02 if exposed else 0.0,
                    "mean_risk_exposed": 0.07 if exposed else 0.0,
                }
            )
    rows.append(
        {
            "dimension": "all",
            "value": "all",
            "entries": 210,
            "candidates": 100,
            "scheduled": 41,
            "scheduled_cne": 36,
            "scheduled_rate": 0.2,
            "exposure_share": 0.35 if exposed else 0.0,
            "flagged_share": 0.02 if exposed else 0.0,
            "mean_risk_exposed": 0.07 if exposed else 0.0,
        }
    )
    return rows


def _schedule() -> dict[str, Any]:
    comparison = []
    policies: dict[str, Any] = {}
    base = {"fifo": 10, "priority": 12, "optimized": 15}
    for p in SCHED_POLICIES:
        comparison.append(
            {
                "policy": p,
                "scheduled": base[p],
                "scheduled_cne": base[p] - 2,
                "scheduled_or": 2,
                "q1_scheduled": base[p] // 2,
                "ges_met": base[p] // 3,
                "ges_unmet": 5,
                "ges_on_time": base[p] // 4,
                "overbooked_flags": 1 if p == "optimized" else 0,
                "sum_coef": base[p] * 100,
                "solver_status": "OPTIMAL" if p == "optimized" else "NOT_APPLICABLE",
                "gap": 0.001 if p == "optimized" else None,
            }
        )
        policies[p] = {
            "ges": {"obligated": 8, "met": 1, "unmet": 7, "on_time": 1, "unmet_by_cause": {"x": 7}},
            "equity": _equity_rows(p),
        }
    opt = policies["optimized"]
    opt.update(
        {
            "horizon_start": "2025-10-06",
            "horizon_end_exclusive": "2025-11-03",
            "config": {
                "horizon_weeks": 4,
                "time_limit_s": 120.0,
                "group_limits": {"min_group_n": 30},
            },
            "noshow_model_version": "noshow-test",
            "code_version": "scheduler-test",
            "review_status": "pending",
            "rules_digest": "0" * 64,
            "rules_version": "0",
            "solver": {
                "status": "OPTIMAL",
                "subproblems": [{}, {}],
                "status_by_phase": {"1": {"OPTIMAL": 2}, "3a": {"OPTIMAL": 2}},
                "gap_by_phase": {"3a": 0.0},
                "time": {
                    "plan": {"wall_time_s": 1.5, "deterministic_time": 0.5},
                    "discarded_first_pass": {"wall_time_s": 0.5},
                },
                "budget": {
                    "exhausted": True,
                    "first_pass": {"allotted": 9.0, "spent": 8.0},
                    "frontier": {"allotted": 4.0, "components_skipped": 2, "spent": 3.0},
                    "overrun": 0.0,
                    "phases_ended_by_limit": 7,
                    "spent": 11.0,
                    "total": 12.0,
                    "unit": "deterministic",
                },
            },
            "reproducible": True,
            "capacity_by_week": [
                {"cne_units": 10, "or_minutes": 100, "cne_sessions": 2, "or_blocks": 1},
                {"cne_units": 12, "or_minutes": 120, "cne_sessions": 3, "or_blocks": 2},
            ],
            "summary": {
                "entries_waiting": 210,
                "candidates": 100,
                "not_candidate": 110,
                "with_compatible_block": 210,
                "added_by_overbooking": 2,
                "overbooked_flags": 1,
                "by_status": {"scheduled": 15},
            },
            "overbooking": {
                "alpha": 0.1,
                "blocks": [{"scheduled": 11, "capacity": 10}],
                "max_risk_exact": 0.09,
            },
            "frontier": {"reached": ["s:1|iq:x"], "still_reached": []},
            "warnings": ["un aviso"],
        }
    )
    return {
        "comparison": comparison,
        "policies": policies,
        "run": {
            "id": RUN_ID,
            "as_of": "2025-09-30",
            "scenario": "baseline",
            "seed": 42,
            "size": 210,
        },
    }


def _curve() -> list[dict[str, Any]]:
    return [{"mean_predicted": 0.1, "observed_rate": 0.12, "n": 50}]


def _metrics(brier: float) -> dict[str, Any]:
    return {
        "auc": 0.6,
        "brier": brier,
        "ece": 0.01,
        "log_loss": 0.4,
        "mean_predicted": 0.15,
        "observed_rate": 0.14,
        "calibration_curve": _curve(),
    }


def _fairness_dim(groups: list[str]) -> dict[str, Any]:
    return {
        "groups": [
            {
                "group": g,
                "n": 300,
                "observed_rate": 0.15,
                "mean_predicted": 0.15,
                "mean_true_prob": 0.15 - 0.01 * i,
                "gap": 0.0,
                "gap_vs_truth": 0.01 * i,
            }
            for i, g in enumerate(groups)
        ],
        "max_abs_gap_vs_truth": 0.01 * (len(groups) - 1),
    }


def _diagnostic() -> dict[str, Any]:
    def variant(feature: str, brier: float, diff: float, significant: bool) -> dict[str, Any]:
        return {
            "added_features": [feature],
            "selected_candidate": "logistic_regression",
            "share_of_oracle_brier_gap_closed": -diff / 0.01,
            "test_metrics": {"auc": 0.61, "brier": brier, "ece": 0.02},
            "vs_primary": {
                "brier_difference": diff,
                "ci95_low": diff - 0.0002,
                "ci95_high": diff + 0.0002,
                "n_boot": 100,
                "resampling_unit": "patient",
                "significant_at_95": significant,
                "variant_better_brier": diff < 0,
            },
        }

    return {
        "method": "Método del diagnóstico.",
        "never_included": ["sex", "true_noshow_prob"],
        "oracle_reference": {"auc": 0.7, "brier": 0.11, "ece": 0.004, "log_loss": 0.36},
        "persisted": False,
        "purpose": "Solo medición.",
        "reference": {
            "model": "logistic_regression_uncalibrated",
            "test_metrics": {"auc": 0.6, "brier": 0.12, "ece": 0.01},
        },
        "used_by_scheduler": False,
        "variants": {
            "plus_age_group": variant("age_group", 0.1196, -0.0004, True),
            "plus_insurance": variant("insurance", 0.12, 0.0, False),
            "plus_commune_code": variant("commune_code", 0.1204, 0.0004, True),
            "plus_health_service_code": variant("health_service_code", 0.1199, -0.0001, False),
            "plus_all_excluded": variant("age_group", 0.1197, -0.0003, True),
        },
    }


def _noshow() -> dict[str, Any]:
    split = {
        "first": "2024-01-01T12:00:00+00:00",
        "last": "2024-06-01T12:00:00+00:00",
        "n": 1000,
        "no_show_rate": 0.15,
    }
    return {
        "model_version": "noshow-test",
        "selection": {
            "primary": "logistic_regression",
            "primary_is_calibrated": True,
            "criterion": "Menor Brier.",
            "brier_calibration_set": {"logistic_regression": 0.12},
        },
        "calibration": {"method": "isotonic", "calibration_events": 100, "rule": "regla"},
        "diagnostic_excluded": _diagnostic(),
        "caveat": "Con datos sintéticos, validan el pipeline.",
        "config": {"seed": 42, "n_boot": 100},
        "data_version": {
            "run_id": RUN_ID,
            "size": 210,
            "seed": 42,
            "scenario": "baseline",
            "as_of": "2025-09-30",
            "generator_version": "0.0",
        },
        "split": {"train": split, "calibration": split, "test": split},
        "test_metrics": {"logistic_regression": _metrics(0.12), "baseline": _metrics(0.13)},
        "oracle_reference": {"metrics": _metrics(0.11)},
        "primary_vs_baseline": {
            "brier_difference": -0.01,
            "ci95_low": -0.02,
            "ci95_high": -0.001,
            "n_boot": 100,
            "resampling_unit": "patient",
            "beats_baseline_brier": True,
            "significant_at_95": True,
        },
        "features": {
            "categorical": ["care_type"],
            "numeric": ["lead_days"],
            "constant_in_train_dropped": [],
            "excluded": {"sex": "Atributo protegido."},
            "proxy_risks": {"care_type": "Un riesgo."},
        },
        "fairness": {
            "description": "Descripción.",
            "min_n": 200,
            "age_group": _fairness_dim(["0_14", "65_plus"]),
            "care_type": _fairness_dim(["consultation", "surgery"]),
            "insurance": _fairness_dim(["fonasa_a", "other"]),
            "health_service_code": _fairness_dim(["1", "2"]),
            "commune_code": {
                **_fairness_dim(["01101", "01107"]),
                "n_groups_total": 5,
                "note": "Nota.",
            },
        },
    }


def _variant_cell(status: str, runs: list[float]) -> dict[str, Any]:
    return {
        "scheduled": 10,
        "q1_scheduled": 4,
        "ges_met": 2,
        "ges_on_time": 1,
        "sum_coef": 1000,
        "wall_time_s_runs": runs,
        "solver": {
            "status": status,
            "gap": 0.0,
            "candidates": 9,
            "pairs_in_model": 20,
            "subproblems": 3,
            "largest_subproblem_pairs": 7,
            "frontier": {"reached": [], "still_reached": []},
        },
    }


def _bench() -> dict[str, Any]:
    cells = []
    for size, weeks in ((1000, 2), (1000, 4)):
        greedy = {
            "scheduled": 8,
            "q1_scheduled": 3,
            "ges_met": 1,
            "ges_on_time": 1,
            "sum_coef": 900,
        }
        cells.append(
            {
                "size": size,
                "horizon_weeks": weeks,
                "data": {
                    "run_id": f"run-{size}-{weeks}",
                    "calibration_passed": True,
                    "calibration_strict_failed": [],
                },
                "problem": {
                    "entries": size,
                    "entries_with_pairs": 90,
                    "pairs_compatible": 100,
                    "ges_obligated": 5,
                },
                "optimized": {
                    "all": _variant_cell("OPTIMAL", [0.2, 0.1, 0.3]),
                    "none": _variant_cell("FEASIBLE", [0.5]),
                },
                "greedy": {"priority": greedy, "fifo": greedy},
                "optimized_vs_priority": {"optimized_not_worse_lexicographic": True},
                "optimized_without_overbooking_vs_priority": {
                    "optimized_not_worse_lexicographic": True
                },
            }
        )
    return {
        "cells": cells,
        "code_version": "scheduler-test",
        "config_defaults": {"solver": {"num_workers": 8, "deterministic": True}},
        "generated_at": "2026-10-09T14:33:20+00:00",
        "machine": {
            "cpu_count": 8,
            "machine": "arm64",
            "ortools": "9.0",
            "platform": "test",
            "python": "3.12",
        },
        "repeats_all": 3,
        "scenario": "baseline",
        "seed": 42,
        "time_limit_s": 120.0,
        "variants": {"all": {}, "none": {"hints": False}},
    }


def _stat(mean: float) -> dict[str, float]:
    return {"mean": mean, "ci95_low": mean - 1, "ci95_high": mean + 1, "n": 2}


def _group_block(dim: str, values: list[str], bias: float) -> dict[str, Any]:
    return {
        "dimension": dim,
        "groups": [
            {
                "value": v,
                "entries": 100 + 10 * i,
                "attended": 30,
                "attention_rate": 0.3 + 0.05 * i + bias,
                "ges_breached": 4,
                "no_show_realized_rate": 0.15,
                "overbooking_exposure": 0.1 * i + (0.2 if bias else 0.0),
                "overflow_share": 0.0,
                "removed_no_show": 1,
                "wait_attended": {"median": 100.0, "n": 30, "p90": 300.0},
            }
            for i, v in enumerate(values)
        ],
    }


def _simulation() -> dict[str, Any]:
    aggregate = {
        p: {key: _stat(10.0 + i) for i, (key, _, _) in enumerate(SIM_METRICS)} for p in SIM_POLICIES
    }
    comparisons: dict[str, Any] = {}
    names = [*SIM_COMPARISONS, "fifo_vs_priority"]
    for name in names:
        sign = -1.0 if name == "fifo_vs_priority" else 1.0
        comparisons[name] = {
            key: {
                "mean_diff": sign * (1.0 if i % 3 == 0 else -2.0 if i % 3 == 1 else 0.0),
                "ci95_low": sign * (0.5 if i % 3 == 0 else -2.5 if i % 3 == 1 else -1.0),
                "ci95_high": sign * (1.5 if i % 3 == 0 else -1.5 if i % 3 == 1 else 1.0),
                "better_in": 2,
                "direction": 1 if i % 2 == 0 else -1,
            }
            for i, (key, _, _) in enumerate(SIM_METRICS)
        }
    # fifo_vs_priority es el espejo de priority_vs_fifo: ci95 invertido
    for key, stat in comparisons["fifo_vs_priority"].items():
        ref = comparisons["priority_vs_fifo"][key]
        stat["mean_diff"] = -ref["mean_diff"]
        stat["ci95_low"] = -ref["ci95_high"]
        stat["ci95_high"] = -ref["ci95_low"]
    sched = {
        "plans": 4,
        "max_gap": None,
        "wall_time_total": 1.0,
        "status_by_phase": {},
    }
    replicas = []
    for seed in (101, 102):
        policies: dict[str, Any] = {}
        for p in SIM_POLICIES:
            bias = 0.01 if p != "fifo" else 0.0
            policies[p] = {
                "groups": [
                    _group_block("age_group", ["0_14", "65_plus"], bias),
                    _group_block("insurance", ["fonasa_a", "other"], bias),
                    _group_block("commune_code", ["01101", "01107"], bias),
                ],
                "scheduler": {
                    **sched,
                    "status_by_phase": {"1": {"OPTIMAL": 3}} if "optim" in p else {},
                    "max_gap": 0.001 if "optim" in p else None,
                },
            }
        replicas.append({"seed": seed, "policies": policies})
    cov = {
        "blocks": 5,
        "cells": 10,
        "cells_with_block": 4,
        "stock": 100,
        "stock_in_cells_with_block": 70,
        "minutes_target": 1000.0,
        "minutes_offered": 900,
        "duration_histogram": {"60": 3, "120": 2},
    }
    cov_consultation = {
        **cov,
        "seats": 40,
        "seats_without_overbooking_share": 0.3,
        "blocks_without_overbooking_share": 0.6,
    }
    return {
        "aggregate": aggregate,
        "code_version": "simulation-test",
        "comparisons": comparisons,
        "config": {
            "weeks": 8,
            "horizon_weeks": 4,
            "commit_weeks": 1,
            "time_limit_s": 30.0,
            "capacity_multiplier": 1.0,
            "abandon_weekly_rate": 0.0,
            "max_no_shows": 2,
            "overbooking_alpha": 0.1,
            "match_level": "health_service",
            "policies": list(SIM_POLICIES),
        },
        "generated_at": "2026-10-09T14:39:28+00:00",
        "limitations": ["Una limitación."],
        "noshow_model_version": "noshow-test",
        "replica_seeds": [101, 102],
        "replicas": replicas,
        "run": {
            "id": SIM_RUN_ID,
            "as_of": "2025-09-30",
            "scenario": "baseline",
            "seed": 42,
            "size": 100,
        },
        "supply_coverage": {"consultation": cov_consultation, "surgery": cov},
        "timing": {p: {"mean_s": 1.0, "total_s": 2.0} for p in SIM_POLICIES},
        "truth_source": "synthetic.noshow_truth.true_noshow_prob",
    }


def write_minimal_results(target: Path) -> Path:
    """Escribe los cinco JSON mínimos en ``target`` y devuelve la carpeta."""
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "synthetic_calibration_baseline_seed42_n210.json": _calibration(),
        "noshow.json": _noshow(),
        f"schedule_{RUN_ID}_4w.json": _schedule(),
        "scheduler-benchmark.json": _bench(),
        "simulation.json": _simulation(),
    }
    for name, data in files.items():
        (target / name).write_text(json.dumps(data), encoding="utf-8")
    return target


def _drop_group_in_first_replica(results: Path, dimension: str, value: str) -> None:
    path = results / "simulation.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for policy in doc["replicas"][0]["policies"].values():
        for block in policy["groups"]:
            if block["dimension"] == dimension:
                block["groups"] = [g for g in block["groups"] if g["value"] != value]
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def drop_group_in_first_replica() -> Callable[[Path, str, str], None]:
    """Quita un grupo de la primera réplica (simula que no alcanzó el mínimo de entradas)."""
    return _drop_group_in_first_replica


@pytest.fixture
def minimal_results(tmp_path: Path) -> Path:
    """Carpeta con resultados mínimos y sintéticos."""
    return write_minimal_results(tmp_path / "results")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Raíz del repositorio (dos niveles sobre ``reports/tests``)."""
    return Path(__file__).resolve().parents[2]
