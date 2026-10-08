"""CLI ``prioriza-noshow`` con ``CliRunner`` sobre la corrida de juguete."""

from __future__ import annotations

from pathlib import Path

from noshow.cli import app
from shared.disclaimer import DISCLAIMER
from typer.testing import CliRunner

runner = CliRunner()


def test_train_command_writes_artifacts(run_dir: Path, tmp_path: Path) -> None:
    results = tmp_path / "noshow.json"
    models = tmp_path / "models"
    result = runner.invoke(
        app,
        [
            "train",
            "--run-dir",
            str(run_dir),
            "--models-dir",
            str(models),
            "--results",
            str(results),
            "--test-days",
            "120",
            "--calibration-days",
            "120",
        ],
    )
    assert result.exit_code == 0, result.output
    assert DISCLAIMER in result.output
    assert results.exists()
    assert list(models.glob("*/noshow_model.joblib"))


def test_train_command_fails_without_matching_run(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["train", "--data-dir", str(empty)])
    assert result.exit_code == 1
