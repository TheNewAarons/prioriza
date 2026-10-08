"""Invariantes del modelo de inasistencias: split temporal sin fugas y sin variables prohibidas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from noshow.data import FEATURE_TABLES, load_run
from noshow.features import (
    FORBIDDEN_FEATURES,
    MODEL_FEATURES,
    OPTIONAL_NUMERIC_FEATURES,
    TIMESTAMP,
    build_features,
    model_columns,
)
from noshow.split import temporal_split
from noshow.train import TrainConfig, train

from noshow import data as noshow_data

PROTECTED = ("sex", "ethnicity", "nationality", "age_group", "insurance", "commune_code")


# --- split temporal -------------------------------------------------------------------------


def _frame(offsets: list[int]) -> pl.DataFrame:
    base = datetime(2025, 1, 1, 12, tzinfo=UTC)
    n = len(offsets)
    return pl.DataFrame(
        {
            "id": [f"a{i}" for i in range(n)],
            TIMESTAMP: [base + timedelta(days=d) for d in offsets],
            "no_show": [i % 2 for i in range(n)],
        }
    )


@settings(max_examples=60, deadline=None)
@given(
    offsets=st.lists(st.integers(0, 400), min_size=3, max_size=80),
    test_days=st.integers(1, 120),
    cal_days=st.integers(1, 120),
)
def test_split_is_temporal_disjoint_and_complete(
    offsets: list[int], test_days: int, cal_days: int
) -> None:
    frame = _frame(offsets)
    try:
        split = temporal_split(frame, test_days, cal_days)
    except ValueError:
        return  # entrenamiento o calibración vacíos: se rechaza, no se mezcla
    tr, cal, te = split.train[TIMESTAMP], split.calibration[TIMESTAMP], split.test[TIMESTAMP]
    assert tr.max() < cal.min()
    assert cal.max() < te.min()
    assert tr.max() < split.calibration_start <= cal.min()
    assert cal.max() < split.test_start <= te.min()
    ids = [*split.train["id"], *split.calibration["id"], *split.test["id"]]
    assert sorted(ids) == sorted(frame["id"].to_list())


def test_split_on_real_layout_is_temporal(run_dir: Path) -> None:
    run = load_run(run_dir)
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    split = temporal_split(feats, 120, 120)
    assert split.train[TIMESTAMP].max() < split.calibration[TIMESTAMP].min()
    assert split.calibration[TIMESTAMP].max() < split.test[TIMESTAMP].min()


def test_test_labels_do_not_affect_fitted_models(run_dir: Path, small_config: TrainConfig) -> None:
    """Invertir las etiquetas del periodo de prueba no cambia ningún modelo ajustado."""
    run = load_run(run_dir)
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    split = temporal_split(feats, small_config.test_days, small_config.calibration_days)
    flipped_ids = set(feats.filter(pl.col(TIMESTAMP) >= split.test_start)["id"].to_list())
    flipped = run.appointment.with_columns(
        pl.when(pl.col("id").is_in(list(flipped_ids)))
        .then(
            pl.when(pl.col("status") == "no_show")
            .then(pl.lit("attended"))
            .otherwise(pl.lit("no_show"))
        )
        .otherwise(pl.col("status"))
        .alias("status")
    )
    # se evalúa sobre filas anteriores a la prueba: sus features no dependen de esas etiquetas
    probe = feats.filter(pl.col(TIMESTAMP) < split.test_start)
    a = train(run, small_config).bundle
    b = train(_replace(run, appointment=flipped), small_config).bundle
    for name in a["models"]:
        cols = a["columns"]["categorical"] + a["columns"]["numeric"]
        pa = a["models"][name].predict_proba(probe.select(cols))[:, 1]
        pb = b["models"][name].predict_proba(probe.select(cols))[:, 1]
        np.testing.assert_allclose(pa, pb)


def _replace(run: noshow_data.RunData, **changes: object) -> noshow_data.RunData:
    from dataclasses import replace

    return replace(run, **changes)  # type: ignore[arg-type]


# --- historial previo sin fuga ----------------------------------------------------------------


def test_prior_history_only_uses_outcomes_known_at_booking(run_dir: Path) -> None:
    run = load_run(run_dir)
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    appts = run.appointment.select("id", "patient_id", "scheduled_start", "lead_days", "status")
    by_patient: dict[str, list[tuple[datetime, str]]] = {}
    for pid, start, status in appts.select("patient_id", "scheduled_start", "status").iter_rows():
        by_patient.setdefault(pid, []).append((start, status))
    lookup = {r[0]: r for r in appts.iter_rows()}
    for row in feats.select("id", "prior_attended", "prior_no_show").iter_rows():
        _, pid, start, lead, _ = lookup[row[0]]
        booked = start - timedelta(days=lead)
        known = [s for t, s in by_patient[pid] if t < booked]
        assert row[1] == known.count("attended")
        assert row[2] == known.count("no_show")


def test_future_outcome_does_not_change_past_features(run_dir: Path) -> None:
    run = load_run(run_dir)
    last = run.appointment.sort(TIMESTAMP).tail(1)
    flipped = run.appointment.with_columns(
        pl.when(pl.col("id") == last["id"][0])
        .then(pl.lit("no_show" if last["status"][0] == "attended" else "attended"))
        .otherwise(pl.col("status"))
        .alias("status")
    )
    a = build_features(run.appointment, run.catalog_specialty).drop("no_show")
    b = build_features(flipped, run.catalog_specialty).drop("no_show")
    assert a.sort("id").equals(b.sort("id"))


# --- variables prohibidas ----------------------------------------------------------------------


def test_policy_declares_no_forbidden_feature() -> None:
    allowed = set(MODEL_FEATURES) | set(OPTIONAL_NUMERIC_FEATURES)
    assert not allowed & FORBIDDEN_FEATURES
    assert set(PROTECTED) <= FORBIDDEN_FEATURES


def test_model_columns_rejects_forbidden_optional() -> None:
    with pytest.raises(ValueError, match="prohibidas"):
        model_columns(("age_group",))


def test_build_features_drops_protected_columns_from_input(run_dir: Path) -> None:
    run = load_run(run_dir)
    n = run.appointment.height
    rng = np.random.default_rng(0)
    polluted = run.appointment.with_columns(
        *(pl.Series(c, rng.choice(["x", "y"], size=n)) for c in PROTECTED),
        pl.Series("true_noshow_prob", rng.random(n)),
        pl.Series("noshow_frailty", rng.normal(size=n)),
    )
    clean = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    dirty = build_features(polluted, run.catalog_specialty, run.waitlist_entry)
    assert dirty.equals(clean)
    assert not set(dirty.columns) & (FORBIDDEN_FEATURES - {"id", "patient_id"})


def test_trained_models_only_see_allowed_columns(run_dir: Path, small_config: TrainConfig) -> None:
    output = train(load_run(run_dir), small_config)
    allowed = set(MODEL_FEATURES) | set(OPTIONAL_NUMERIC_FEATURES)
    for name, model in output.bundle["models"].items():
        seen = set(getattr(model, "feature_names_in_", []))
        if name == "baseline_specialty_rate":
            seen = {model.column}
        assert seen, name
        assert seen <= allowed, (name, seen - allowed)
        assert not seen & FORBIDDEN_FEATURES, name
    used = set(output.results["features"]["categorical"] + output.results["features"]["numeric"])
    assert used <= allowed


def test_feature_loading_never_reads_truth_or_patient_tables(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[str] = []
    original = pl.read_parquet

    def spy(source: Path, *args: object, **kwargs: object) -> pl.DataFrame:
        read.append(Path(source).stem)
        return original(source, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(noshow_data.pl, "read_parquet", spy)
    run = load_run(run_dir)
    build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    assert set(read) <= FEATURE_TABLES
    assert not {"appointment_truth", "patient_latent", "patient"} & set(read)


def test_feature_allowlist_rejects_truth_table(run_dir: Path) -> None:
    with pytest.raises(PermissionError):
        noshow_data._read_table(run_dir, "appointment_truth", FEATURE_TABLES)
