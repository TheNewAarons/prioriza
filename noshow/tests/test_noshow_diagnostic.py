"""Diagnóstico de variables excluidas: solo medición, nunca llega al artefacto ni al programador."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from noshow.cli import app
from noshow.data import load_fairness_attributes, load_run
from noshow.features import FORBIDDEN_FEATURES, MODEL_FEATURES
from noshow.models import build_logistic
from noshow.train import (
    PRODUCTION_MODEL_NAMES,
    TrainConfig,
    TrainOutput,
    assert_production_bundle,
    load_bundle,
    prepare,
    save,
    train,
)
from typer.testing import CliRunner

from noshow import diagnostic

REPO = Path(__file__).resolve().parents[2]
CONFIG = TrainConfig(seed=7, test_days=120, calibration_days=120, n_boot=50, fairness_min_n=20)

# Copia literal de la política vigente: si alguien la cambia, este test obliga a revisarlo.
EXPECTED_MODEL_FEATURES = (
    "specialty_code",
    "care_type",
    "weekday",
    "time_band",
    "lead_days",
    "prior_attended",
    "prior_no_show",
)
EXPECTED_FORBIDDEN = frozenset(
    {
        "sex",
        "gender",
        "ethnicity",
        "nationality",
        "age_group",
        "insurance",
        "commune_code",
        "health_service_code",
        "establishment_code",
        "noshow_frailty",
        "true_noshow_prob",
        "patient_id",
        "id",
        "entry_id",
        "run_id",
    }
)


@pytest.fixture(scope="module")
def output(run_dir: Path) -> TrainOutput:
    return train(load_run(run_dir), CONFIG)


@pytest.fixture(scope="module")
def diag(run_dir: Path, output: TrainOutput) -> dict[str, Any]:
    return diagnostic.diagnose_excluded(load_run(run_dir), CONFIG, output)


# --- política de variables intacta -------------------------------------------------------------


def test_feature_policy_is_unchanged() -> None:
    assert MODEL_FEATURES == EXPECTED_MODEL_FEATURES
    assert FORBIDDEN_FEATURES == EXPECTED_FORBIDDEN
    # las variables diagnosticadas siguen prohibidas en producción
    assert set(diagnostic.DIAGNOSTIC_FEATURES) <= FORBIDDEN_FEATURES
    assert not set(diagnostic.DIAGNOSTIC_FEATURES) & set(MODEL_FEATURES)


def test_never_diagnosed_covers_protected_and_truth() -> None:
    never = {"sex", "ethnicity", "nationality", "noshow_frailty", "true_noshow_prob"}
    assert never <= diagnostic.NEVER_DIAGNOSED
    assert not diagnostic.NEVER_DIAGNOSED & set(diagnostic.DIAGNOSTIC_FEATURES)
    for extra in diagnostic.VARIANTS.values():
        assert set(extra) <= set(diagnostic.DIAGNOSTIC_FEATURES)


@pytest.mark.parametrize("bad", ["sex", "ethnicity", "nationality", "true_noshow_prob", "x"])
def test_check_variant_rejects_forbidden_or_unknown(bad: str) -> None:
    with pytest.raises(ValueError):
        diagnostic._check_variant(("age_group", bad))


def test_diagnose_rejects_variant_with_truth(
    run_dir: Path, output: TrainOutput, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostic, "VARIANTS", {"leak": ("noshow_frailty",)})
    with pytest.raises(ValueError, match="nunca permitidas"):
        diagnostic.diagnose_excluded(load_run(run_dir), CONFIG, output)


# --- contenido y determinismo del diagnóstico --------------------------------------------------


def test_diagnostic_is_measurement_only_and_json(diag: dict[str, Any]) -> None:
    # sin ``default=``: falla si se colara un estimador u otro objeto no JSON
    json.dumps(diag)
    assert diag["used_by_scheduler"] is False
    assert diag["persisted"] is False
    assert "Solo medición" in diag["purpose"]
    assert set(diag["variants"]) == set(diagnostic.VARIANTS)
    assert diag["oracle_reference"] is not None
    for v in diag["variants"].values():
        assert {"auc", "brier", "ece"} <= set(v["test_metrics"])
        assert v["vs_primary"]["resampling_unit"] == "patient"
        assert v["vs_primary"]["ci95_low"] <= v["vs_primary"]["ci95_high"]
        assert v["selected_candidate"] in v["test_metrics_by_candidate"]


def test_reference_is_the_production_primary(diag: dict[str, Any], output: TrainOutput) -> None:
    primary = output.bundle["primary"]
    assert diag["reference"]["model"] == primary
    assert (
        diag["reference"]["test_metrics"]["brier"]
        == output.results["test_metrics"][primary]["brier"]
    )
    assert (
        diag["reference"]["test_metrics"]["auc"] == output.results["test_metrics"][primary]["auc"]
    )


def test_diagnostic_is_deterministic(
    run_dir: Path, output: TrainOutput, diag: dict[str, Any]
) -> None:
    again = diagnostic.diagnose_excluded(load_run(run_dir), CONFIG, output)
    assert json.dumps(again, sort_keys=True) == json.dumps(diag, sort_keys=True)


def test_variant_without_extras_reproduces_primary(
    run_dir: Path, output: TrainOutput, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mismo pipeline: sin variables agregadas, la variante es exactamente el principal."""
    monkeypatch.setattr(diagnostic, "VARIANTS", {"none": ()})
    diag = diagnostic.diagnose_excluded(load_run(run_dir), CONFIG, output)
    v = diag["variants"]["none"]
    assert v["selected_candidate"] == output.bundle["primary"]
    assert v["brier_calibration_set"] == output.results["selection"]["brier_calibration_set"]
    assert v["test_metrics"] == diag["reference"]["test_metrics"]
    assert v["vs_primary"]["brier_difference"] == 0.0


def test_high_cardinality_is_capped_for_boosting(
    run_dir: Path, output: TrainOutput, monkeypatch: pytest.MonkeyPatch
) -> None:
    # la fixture tiene 3 comunas: con tope 2 se ejercita el agrupamiento de infrecuentes
    monkeypatch.setattr(diagnostic, "GB_MAX_CATEGORIES", 2)
    monkeypatch.setattr(diagnostic, "VARIANTS", {"plus_commune_code": ("commune_code",)})
    diag = diagnostic.diagnose_excluded(load_run(run_dir), CONFIG, output)
    assert diag["variants"]["plus_commune_code"]["gradient_boosting_max_categories"] == 2


def test_diagnostic_does_not_touch_production_bundle(run_dir: Path) -> None:
    output = train(load_run(run_dir), CONFIG)
    before = {name: id(m) for name, m in output.bundle["models"].items()}
    keys = set(output.bundle)
    diagnostic.diagnose_excluded(load_run(run_dir), CONFIG, output)
    assert set(output.bundle) == keys
    assert {name: id(m) for name, m in output.bundle["models"].items()} == before
    assert "diagnostic_excluded" not in output.results


# --- el artefacto persistido no cambia ---------------------------------------------------------


def _cli_train(run_dir: Path, out: Path, *flags: str) -> tuple[dict[str, Any], dict[str, Any]]:
    args = ["train", "--run-dir", str(run_dir), "--models-dir", str(out / "models")]
    args += ["--results", str(out / "noshow.json"), "--test-days", "120"]
    args += ["--calibration-days", "120", *flags]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    results = json.loads((out / "noshow.json").read_text(encoding="utf-8"))
    (meta_path,) = (out / "models").glob("*/metadata.json")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata.pop("joblib_sha256")
    return results, metadata


def test_cli_diagnostic_changes_only_results_key(run_dir: Path, tmp_path: Path) -> None:
    with_diag, meta_with = _cli_train(run_dir, tmp_path / "with")
    without, meta_without = _cli_train(run_dir, tmp_path / "without", "--no-diagnostic")
    assert "diagnostic_excluded" in with_diag
    assert "diagnostic_excluded" not in without
    assert {k: v for k, v in with_diag.items() if k != "diagnostic_excluded"} == without
    assert meta_with == meta_without
    (artifact,) = (tmp_path / "with" / "models").glob("*/noshow_model.joblib")
    bundle = load_bundle(artifact)
    assert set(bundle["models"]) == PRODUCTION_MODEL_NAMES
    assert_production_bundle(bundle)
    for model in bundle["models"].values():
        seen = set(getattr(model, "feature_names_in_", [getattr(model, "column", "")]))
        assert not seen & set(diagnostic.DIAGNOSTIC_FEATURES)


def test_save_rejects_extra_model(output: TrainOutput, tmp_path: Path) -> None:
    models = {**output.bundle["models"], "diagnostic_plus_age_group": object()}
    bad = replace(output, bundle={**output.bundle, "models": models})
    with pytest.raises(ValueError, match="ajenos a producción"):
        save(bad, tmp_path / "models", tmp_path / "noshow.json")
    assert not (tmp_path / "models").exists()
    assert not (tmp_path / "noshow.json").exists()


def test_save_rejects_model_that_saw_excluded_feature(
    run_dir: Path, output: TrainOutput, tmp_path: Path
) -> None:
    """Un modelo de diagnóstico disfrazado con nombre de producción tampoco se persiste."""
    run = load_run(run_dir)
    prep = prepare(run, CONFIG)
    attrs = load_fairness_attributes(run.run_dir).select("patient_id", "age_group")
    frame = prep.split.train.join(attrs, on="patient_id", how="left", maintain_order="left")
    categorical = [*prep.categorical, "age_group"]
    leaky = build_logistic(categorical, prep.numeric, CONFIG.seed).fit(
        frame.select(categorical + prep.numeric), frame["no_show"].to_numpy().astype(np.int64)
    )
    models = {**output.bundle["models"], "logistic_regression_uncalibrated": leaky}
    bad = replace(output, bundle={**output.bundle, "models": models})
    with pytest.raises(ValueError, match="prohibidas"):
        save(bad, tmp_path / "models", tmp_path / "noshow.json")
    cols = {**output.bundle["columns"], "categorical": categorical}
    with pytest.raises(ValueError, match="prohibidas"):
        assert_production_bundle({**output.bundle, "columns": cols})
    assert not (tmp_path / "models").exists()


# --- aislamiento: el programador y la simulación no lo importan ---------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("package", ["scheduler", "simulation", "api", "dashboard"])
def test_consumers_do_not_import_diagnostic(package: str) -> None:
    files = sorted((REPO / package / "src").rglob("*.py"))
    assert files, package
    for path in files:
        assert "noshow.diagnostic" not in _imports(path), path


def test_production_modules_do_not_load_diagnostic_transitively() -> None:
    code = (
        "import importlib, pkgutil, sys\n"
        "import noshow.train, noshow.cli, noshow.features\n"
        "for pkg in ('scheduler', 'simulation'):\n"
        "    mod = importlib.import_module(pkg)\n"
        "    for info in pkgutil.walk_packages(mod.__path__, pkg + '.'):\n"
        "        importlib.import_module(info.name)\n"
        "assert 'noshow.diagnostic' not in sys.modules, 'diagnóstico cargado'\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_diagnostic_module_cannot_persist() -> None:
    names = _imports(REPO / "noshow" / "src" / "noshow" / "diagnostic.py")
    assert "joblib" not in names
    assert "noshow.train.save" not in names
    assert not any(n.startswith("pickle") for n in names)
