"""Predicción sobre citas futuras (sin resultado) y franja horaria local con horario de verano."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
from noshow.data import load_run
from noshow.features import build_candidate_features, build_features
from noshow.train import TrainConfig, load_bundle, predict_noshow, save, train

SPECIALTIES = pl.DataFrame({"code": ["cne_medical:cardiologia"], "care_type": ["consultation"]})


def _candidates(starts: list[datetime], lead: int = 14) -> pl.DataFrame:
    n = len(starts)
    return pl.DataFrame(
        {
            "id": [f"c{i}" for i in range(n)],
            "patient_id": ["p0"] * n,
            "scheduled_start": starts,
            "lead_days": [lead] * n,
            "specialty_code": ["cne_medical:cardiologia"] * n,
            "status": ["scheduled"] * n,
        },
        schema_overrides={"scheduled_start": pl.Datetime("us", "UTC")},
    )


def test_scheduled_appointments_are_scored_in_order(
    run_dir: Path, small_config: TrainConfig, tmp_path: Path
) -> None:
    """Guardar, cargar y predecir sobre citas ``scheduled`` (lo que usará el programador)."""
    run = load_run(run_dir)
    output = train(run, small_config)
    artifact = save(output, tmp_path / "models", tmp_path / "noshow.json")
    bundle = load_bundle(artifact)
    patients = run.appointment["patient_id"].unique().sort().head(5).to_list()
    future = pl.DataFrame(
        {
            "id": [f"f{i}" for i in range(5)],
            "patient_id": patients,
            "scheduled_start": [datetime(2025, 10, 20 + i, 14, tzinfo=UTC) for i in range(5)],
            "lead_days": [10, 20, 30, 40, 50],
            "specialty_code": run.appointment["specialty_code"].head(5).to_list(),
            "status": ["scheduled"] * 5,
        },
        schema_overrides={"scheduled_start": pl.Datetime("us", "UTC")},
    )
    feats = build_candidate_features(future, run.appointment, run.catalog_specialty)
    assert feats["id"].to_list() == future["id"].to_list()
    p = predict_noshow(bundle, feats)
    assert p.shape == (5,)
    assert np.all((p > 0) & (p < 1))
    # el historial previo sale de las citas observadas del paciente
    assert feats["prior_attended"].sum() + feats["prior_no_show"].sum() > 0


def test_candidate_history_ignores_unobserved_appointments() -> None:
    history = _candidates([datetime(2025, 1, 1, 12, tzinfo=UTC)]).with_columns(
        pl.lit("cancelled").alias("status")
    )
    feats = build_candidate_features(
        _candidates([datetime(2025, 6, 1, 12, tzinfo=UTC)]), history, SPECIALTIES
    )
    assert feats["prior_attended"][0] == 0
    assert feats["prior_no_show"][0] == 0


def test_time_band_uses_santiago_local_time_across_dst() -> None:
    """15:30 UTC es 12:30 en verano (UTC-3) y 11:30 en invierno (UTC-4): ambas mañana."""
    starts = [
        datetime(2025, 1, 15, 15, 30, tzinfo=UTC),  # verano: 12:30 local
        datetime(2025, 1, 15, 16, 30, tzinfo=UTC),  # verano: 13:30 local
        datetime(2025, 7, 15, 16, 30, tzinfo=UTC),  # invierno: 12:30 local
        datetime(2025, 7, 15, 17, 30, tzinfo=UTC),  # invierno: 13:30 local
    ]
    feats = build_candidate_features(_candidates(starts), _candidates(starts).clear(), SPECIALTIES)
    assert feats["time_band"].to_list() == ["morning", "afternoon", "morning", "afternoon"]


def test_training_features_equal_candidate_features_for_observed(run_dir: Path) -> None:
    run = load_run(run_dir)
    train_feats = build_features(run.appointment, run.catalog_specialty).drop("no_show")
    cand = build_candidate_features(run.appointment, run.appointment, run.catalog_specialty)
    assert train_feats.sort("id").equals(cand.sort("id"))
