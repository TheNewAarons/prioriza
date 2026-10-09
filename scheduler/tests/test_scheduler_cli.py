"""Tests rutinarios de la CLI ``prioriza-schedule`` (formulación §14).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.

Cobertura:
- Corrida sin sobreagendamiento con ``--policy all`` escribe el informe y los parquet.
- El informe incluye ``comparison`` de las tres políticas y el ``disclaimer``.
- ``--run-dir`` inexistente y ``--data-dir`` vacío terminan con error.
- Sobreagendamiento sin modelo entrenado informa el comando de recuperación.
- (Opcional) Política ``optimized`` con sobreagendamiento tras entrenar el modelo.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from scheduler.cli import app
from shared.disclaimer import DISCLAIMER
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def synth_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Corrida sintética pequeña (N=1000) escrita a parquet una sola vez por sesión."""
    from shared.db.enums import NoShowScenario
    from synthetic.config import RunConfig
    from synthetic.io import write_parquet
    from synthetic.pipeline import generate

    cfg = RunConfig(size=1_000, seed=42, scenario=NoShowScenario.BASELINE)
    ds = generate(cfg)
    out_dir = tmp_path_factory.mktemp("synthetic_data")
    run_dir = write_parquet(ds, out_dir)
    return run_dir


@pytest.fixture(scope="session")
def trained_models_dir(tmp_path_factory: pytest.TempPathFactory, synth_run_dir: Path) -> Path:
    """Entrena un modelo de inasistencias de juguete sobre la corrida sintética."""
    from noshow.data import load_run
    from noshow.train import TrainConfig, save, train

    models_dir = tmp_path_factory.mktemp("models")
    results_path = tmp_path_factory.mktemp("noshow_results") / "noshow.json"
    cfg = TrainConfig(seed=42, test_days=120, calibration_days=120, n_boot=20, fairness_min_n=10)
    run_data = load_run(synth_run_dir)
    output = train(run_data, cfg)
    save(output, models_dir, results_path)
    return models_dir


# ---------------------------------------------------------------------------
# Tests de la CLI
# ---------------------------------------------------------------------------


def test_policy_all_without_overbooking_writes_report_and_parquet(
    tmp_path: Path, synth_run_dir: Path
) -> None:
    """--no-overbooking --policy all escribe el JSON y los parquet de las tres políticas."""
    results_dir = tmp_path / "results"
    out_dir = tmp_path / "schedules"
    result = runner.invoke(
        app,
        [
            "--no-overbooking",
            "--policy",
            "all",
            "--weeks",
            "4",
            "--run-dir",
            str(synth_run_dir),
            "--results-dir",
            str(results_dir),
            "--out-dir",
            str(out_dir),
            "--time-limit",
            "5",
            "--workers",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert DISCLAIMER in result.output

    # Informe JSON.
    manifest = json.loads((synth_run_dir / "manifest.json").read_text(encoding="utf-8"))
    run_id = manifest["run"]["id"]
    json_files = list(results_dir.glob(f"schedule_{run_id}_4w.json"))
    assert len(json_files) == 1
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert payload["disclaimer"] == DISCLAIMER
    assert "policies" in payload
    assert set(payload["policies"]) == {"fifo", "priority", "optimized"}
    for name in ("fifo", "priority", "optimized"):
        assert "disclaimer" in payload["policies"][name]
    comparison = payload["comparison"]
    assert {row["policy"] for row in comparison} == {"fifo", "priority", "optimized"}

    # Parquet por política.
    plan_dir = out_dir / run_id / "4w"
    assert plan_dir.exists()
    for policy in ("fifo", "priority", "optimized"):
        for suffix in ("assignments", "explanations", "ges", "standby"):
            path = plan_dir / f"{policy}_{suffix}.parquet"
            assert path.exists(), f"falta {path}"
            df = pl.read_parquet(path)
            assert df.height >= 0


def test_missing_run_dir_fails(tmp_path: Path) -> None:
    """--run-dir a un directorio que no existe termina con error."""
    ghost = tmp_path / "no_existe"
    result = runner.invoke(
        app,
        [
            "--no-overbooking",
            "--run-dir",
            str(ghost),
            "--results-dir",
            str(tmp_path / "results"),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "Error" in result.output


def test_empty_data_dir_fails(tmp_path: Path) -> None:
    """--data-dir sin corridas termina con error."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(
        app,
        [
            "--no-overbooking",
            "--data-dir",
            str(empty),
            "--results-dir",
            str(tmp_path / "results"),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "Error" in result.output


def test_overbooking_without_model_fails(tmp_path: Path, synth_run_dir: Path) -> None:
    """Con --overbooking activo y sin modelo en --models-dir sale con 1 y sugiere entrenar."""
    empty_models = tmp_path / "no_models"
    empty_models.mkdir()
    result = runner.invoke(
        app,
        [
            "--overbooking",
            "--policy",
            "optimized",
            "--weeks",
            "4",
            "--run-dir",
            str(synth_run_dir),
            "--models-dir",
            str(empty_models),
            "--results-dir",
            str(tmp_path / "results"),
            "--out-dir",
            str(tmp_path / "out"),
            "--time-limit",
            "5",
            "--workers",
            "1",
        ],
    )
    assert result.exit_code == 1
    assert "make train-noshow" in result.output


def test_optimized_with_overbooking_and_trained_model(
    tmp_path: Path, synth_run_dir: Path, trained_models_dir: Path
) -> None:
    """La política optimized con sobreagendamiento corre y escribe el informe."""
    results_dir = tmp_path / "results"
    out_dir = tmp_path / "schedules"
    result = runner.invoke(
        app,
        [
            "--overbooking",
            "--policy",
            "optimized",
            "--weeks",
            "4",
            "--run-dir",
            str(synth_run_dir),
            "--models-dir",
            str(trained_models_dir),
            "--results-dir",
            str(results_dir),
            "--out-dir",
            str(out_dir),
            "--time-limit",
            "5",
            "--workers",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((synth_run_dir / "manifest.json").read_text(encoding="utf-8"))
    run_id = manifest["run"]["id"]
    json_files = list(results_dir.glob(f"schedule_{run_id}_4w.json"))
    assert len(json_files) == 1
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert "optimized" in payload["policies"]
