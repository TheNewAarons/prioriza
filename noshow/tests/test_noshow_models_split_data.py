"""Baseline por especialidad, regla de calibración, split temporal y lectura de corridas."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from noshow.data import data_version, find_run_dir
from noshow.models import ISOTONIC_MIN_EVENTS, SpecialtyRateBaseline, choose_calibration_method
from noshow.split import temporal_split
from noshow_test_support import make_run

# --- models ---------------------------------------------------------------------------------


def test_baseline_shrunk_rate_by_hand() -> None:
    X = pl.DataFrame({"specialty_code": ["a"] * 4 + ["b"] * 2})
    y = np.array([1, 1, 0, 0, 0, 0])
    model = SpecialtyRateBaseline(smoothing=2.0).fit(X, y)
    g = 2 / 6
    p = model.predict_proba(pl.DataFrame({"specialty_code": ["a", "b", "zzz"]}))[:, 1]
    assert p[0] == pytest.approx((2 + 2 * g) / (4 + 2))
    assert p[1] == pytest.approx((0 + 2 * g) / (2 + 2))
    assert p[2] == pytest.approx(g)  # especialidad no vista: tasa global


@pytest.mark.parametrize(
    ("minority", "expected"),
    [(ISOTONIC_MIN_EVENTS - 1, "sigmoid"), (ISOTONIC_MIN_EVENTS, "isotonic")],
)
def test_calibration_threshold(minority: int, expected: str) -> None:
    y = np.array([1] * minority + [0] * 5000)
    assert choose_calibration_method(y) == expected


# --- split ----------------------------------------------------------------------------------


def _frame(n_days: int = 400) -> pl.DataFrame:
    base = datetime(2025, 1, 1, 12, tzinfo=UTC)
    return pl.DataFrame(
        {
            "id": [f"a{i}" for i in range(n_days)],
            "scheduled_start": [base + timedelta(days=i) for i in range(n_days)],
            "no_show": [i % 2 for i in range(n_days)],
        }
    )


@pytest.mark.parametrize(("test_days", "cal_days"), [(0, 10), (10, 0), (-1, 10)])
def test_split_rejects_non_positive_days(test_days: int, cal_days: int) -> None:
    with pytest.raises(ValueError, match=">= 1"):
        temporal_split(_frame(), test_days, cal_days)


def test_split_rejects_empty_train() -> None:
    with pytest.raises(ValueError, match="vacío"):
        temporal_split(_frame(100), 60, 60)


def test_split_summary_sizes_add_up() -> None:
    frame = _frame()
    summary = temporal_split(frame, 60, 90).summary()
    total = sum(summary[k]["n"] for k in ("train", "calibration", "test"))  # type: ignore[index]
    assert total == frame.height


# --- data -----------------------------------------------------------------------------------


def test_find_run_dir_without_matches(tmp_path: Path) -> None:
    make_run(tmp_path, n_patients=30, seed=2)
    with pytest.raises(FileNotFoundError):
        find_run_dir(tmp_path, seed=99, size=30, scenario="baseline")


def _copy_run(src: Path, dst: Path, **run_changes: object) -> Path:
    """Copia una corrida de juguete cambiando campos de ``manifest.json``."""
    dst.mkdir()
    for f in src.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    manifest = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
    manifest["run"].update(run_changes)
    (dst / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dst


def test_find_run_dir_with_two_matches_fails(tmp_path: Path) -> None:
    first = make_run(tmp_path, n_patients=30, seed=2)
    _copy_run(first, tmp_path / "copy")
    with pytest.raises(FileExistsError):
        find_run_dir(tmp_path, seed=2, size=30, scenario="baseline")


def test_find_run_dir_filters_stale_generator_versions(tmp_path: Path) -> None:
    first = make_run(tmp_path, n_patients=30, seed=2)
    _copy_run(first, tmp_path / "stale", params_sha256="f" * 64)
    expected = {"params_sha256": "0" * 64, "targets_sha256": "0" * 64}
    assert find_run_dir(tmp_path, seed=2, size=30, scenario="baseline", expected=expected) == first


def test_find_run_dir_only_stale_runs_fails(tmp_path: Path) -> None:
    make_run(tmp_path, n_patients=30, seed=2)
    with pytest.raises(FileNotFoundError, match="otros supuestos"):
        find_run_dir(
            tmp_path, seed=2, size=30, scenario="baseline", expected={"params_sha256": "x"}
        )


def test_data_version_renames_id() -> None:
    run = {
        k: "x"
        for k in (
            "id",
            "seed",
            "size",
            "scenario",
            "as_of",
            "generator_version",
            "targets_sha256",
            "params_sha256",
            "dataset_sha256",
        )
    }
    run["id"] = "abc"
    out = data_version({"run": run})
    assert out["run_id"] == "abc"
    assert "id" not in out
    json.dumps(out)
