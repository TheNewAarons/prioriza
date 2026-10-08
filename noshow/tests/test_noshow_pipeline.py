"""Pipeline de punta a punta del modelo de inasistencias sobre la corrida de juguete."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import joblib
import numpy as np
import pytest
from noshow.data import load_run
from noshow.features import build_features
from noshow.train import (
    TrainConfig,
    TrainOutput,
    load_bundle,
    predict_noshow,
    save,
    train,
)
from noshow_test_support import make_run
from shared.disclaimer import DISCLAIMER

from noshow import MODEL_FORMAT_VERSION

CONFIG = TrainConfig(seed=7, test_days=120, calibration_days=120, n_boot=50, fairness_min_n=20)
EXPECTED_MODELS = {
    "baseline_specialty_rate",
    "logistic_regression",
    "logistic_regression_uncalibrated",
    "gradient_boosting",
    "gradient_boosting_uncalibrated",
}
EXPECTED_KEYS = {
    "test_metrics",
    "oracle_reference",
    "primary_vs_baseline",
    "fairness",
    "features",
    "calibration",
    "selection",
    "split",
    "data_version",
    "disclaimer",
    "caveat",
}


def _dumps(results: dict) -> str:
    return json.dumps(results, sort_keys=True)


@pytest.fixture(scope="module")
def output(run_dir: Path) -> TrainOutput:
    """Un único entrenamiento por módulo (solo lectura)."""
    return train(load_run(run_dir), CONFIG)


def test_results_have_expected_keys(output: TrainOutput) -> None:
    r = output.results
    assert set(r) >= EXPECTED_KEYS
    assert set(r["test_metrics"]) == EXPECTED_MODELS
    assert r["disclaimer"] == DISCLAIMER
    assert r["oracle_reference"]["metrics"] is not None


def test_primary_and_calibration(output: TrainOutput) -> None:
    r = output.results
    assert r["selection"]["primary"] in {"logistic_regression", "gradient_boosting"}
    assert output.bundle["primary"] == r["selection"]["primary"]
    # Con pocos eventos en calibración se usa sigmoide, no isotónica.
    assert r["calibration"]["method"] == "sigmoid"
    assert r["calibration"]["calibration_events"] < 1000


def test_metrics_are_probabilities(output: TrainOutput) -> None:
    for name, m in output.results["test_metrics"].items():
        assert 0.0 <= m["mean_predicted"] <= 1.0, name
        assert 0.0 <= m["brier"] <= 1.0, name
        assert 0.0 <= m["ece"] <= 1.0, name
        assert m["auc"] is None or 0.0 <= m["auc"] <= 1.0, name


def test_predictions_in_unit_interval(output: TrainOutput, run_dir: Path) -> None:
    run = load_run(run_dir)
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    p = predict_noshow(output.bundle, feats)
    assert p.shape == (feats.height,)
    assert np.all((p >= 0.0) & (p <= 1.0))


def test_results_are_json_serializable(output: TrainOutput) -> None:
    assert json.loads(_dumps(output.results))["model_version"].startswith("noshow-")


def test_save_load_predict_roundtrip(output: TrainOutput, run_dir: Path, tmp_path: Path) -> None:
    run = load_run(run_dir)
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    before = predict_noshow(output.bundle, feats)
    artifact = save(output, tmp_path / "models", tmp_path / "res" / "noshow.json")
    after = predict_noshow(load_bundle(artifact), feats)
    np.testing.assert_array_equal(before, after)
    assert json.loads((tmp_path / "res" / "noshow.json").read_text(encoding="utf-8"))


def test_metadata_has_no_models_and_has_disclaimer(output: TrainOutput, tmp_path: Path) -> None:
    artifact = save(output, tmp_path / "models", tmp_path / "noshow.json")
    meta = json.loads((artifact.parent / "metadata.json").read_text(encoding="utf-8"))
    assert "models" not in meta
    assert meta["disclaimer"] == DISCLAIMER
    assert meta["model_format_version"] == MODEL_FORMAT_VERSION


def test_load_bundle_rejects_other_format(output: TrainOutput, tmp_path: Path) -> None:
    bad = tmp_path / "bad.joblib"
    joblib.dump({**output.bundle, "model_format_version": "999"}, bad)
    with pytest.raises(ValueError, match="incompatible"):
        load_bundle(bad)


def test_same_seed_is_reproducible(output: TrainOutput, run_dir: Path) -> None:
    again = train(load_run(run_dir), CONFIG)
    assert _dumps(again.results) == _dumps(output.results)
    run = load_run(run_dir)
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    np.testing.assert_array_equal(
        predict_noshow(output.bundle, feats), predict_noshow(again.bundle, feats)
    )


def test_other_toy_run_changes_results(output: TrainOutput, tmp_path: Path) -> None:
    other = make_run(tmp_path, seed=1)
    res = train(load_run(other), CONFIG).results
    assert _dumps(res) != _dumps(output.results)
    shutil.rmtree(other)
