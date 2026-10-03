"""Tests de la CLI ``prioriza-ingest`` y de la orquestación (sin red)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import ingestion.pipeline as pipeline
import ingestion.validate as validate
import polars as pl
import pytest
from ingestion.cli import app
from ingestion.download import sha256_file
from ingestion.pipeline import RunResult
from ingestion.sources import SOURCES
from shared.config import get_settings
from shared.schemas import FACILITY_POLARS_SCHEMA, GES_CASES_POLARS_SCHEMA
from typer.testing import CliRunner

runner = CliRunner()
ALL_IDS = [
    "glosa06_2025q3",
    "glosa06_2025q4",
    "glosa06_2026q1",
    "sis_ges_cases_2026q1",
    "minsal_establishments",
]


def _fixture(fixtures_dir: Path, *parts: str) -> Path:
    return fixtures_dir.joinpath(*parts)


def test_list_shows_the_five_sources() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    for source_id in ALL_IDS:
        assert source_id in result.output
    assert list(SOURCES) == ALL_IDS


def test_help_lists_one_command_per_source_plus_all_and_list() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["list", "all", *ALL_IDS]:
        assert command in result.output


def test_establishments_input_writes_parquet_and_sidecar(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # La muestra es mínima: se baja el umbral de tamaño mínimo del catálogo.
    monkeypatch.setattr(validate, "MIN_FACILITIES", 1)
    csv_path = _fixture(fixtures_dir, "minsal_establishments", "establishments_sample.csv")
    data_dir = tmp_path / "data"
    result = runner.invoke(
        app, ["minsal_establishments", "--input", str(csv_path), "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 0, result.output
    assert "minsal_establishments" in result.output

    parquet = data_dir / "processed" / "minsal_establishments.parquet"
    sidecar_path = data_dir / "processed" / "minsal_establishments.metadata.json"
    frame = pl.read_parquet(parquet)
    assert frame.height == 15
    assert frame.schema == pl.Schema(FACILITY_POLARS_SCHEMA)
    assert frame["establishment_code"].is_unique().all()
    assert frame["establishment_code"].to_list() == sorted(frame["establishment_code"].to_list())

    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["source_id"] == "minsal_establishments"
    assert sidecar["raw_sha256"] == sha256_file(csv_path)
    assert sidecar["rows"] == 15
    assert sidecar["columns"] == frame.columns
    assert isinstance(sidecar["warnings"], list)
    assert "tables" in sidecar
    assert "ingestion_version" in sidecar


def test_establishments_sample_below_minimum_size_exits_1(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """Sin bajar el umbral, la muestra de 15 filas no pasa la validación de tamaño."""
    csv_path = _fixture(fixtures_dir, "minsal_establishments", "establishments_sample.csv")
    result = runner.invoke(
        app, ["minsal_establishments", "--input", str(csv_path), "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "minsal_establishments" in result.output
    assert not (tmp_path / "processed" / "minsal_establishments.parquet").exists()


def test_sis_ges_input_writes_parquet(fixtures_dir: Path, tmp_path: Path) -> None:
    xlsx = _fixture(fixtures_dir, "sis_ges", "sis_ges_cases_mini.xlsx")
    result = runner.invoke(
        app, ["sis_ges_cases_2026q1", "--input", str(xlsx), "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    frame = pl.read_parquet(tmp_path / "processed" / "sis_ges_cases_2026q1.parquet")
    assert frame.height == 50
    assert frame.schema == pl.Schema(GES_CASES_POLARS_SCHEMA)
    assert set(frame["insurer"]) == {"fonasa", "isapre"}
    sidecar = json.loads(
        (tmp_path / "processed" / "sis_ges_cases_2026q1.metadata.json").read_text(encoding="utf-8")
    )
    assert sidecar["raw_sha256"] == sha256_file(xlsx)
    assert sidecar["rows"] == 50


def test_parsing_a_wrong_file_exits_1_with_the_error_on_stderr(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """Un PDF de 1 página no trae las 8 tablas: deriva de formato, no un crash."""
    pdf = _fixture(fixtures_dir, "glosa06", "glosa06_2026q1_p26.pdf")
    result = runner.invoke(
        app, ["glosa06_2026q1", "--input", str(pdf), "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "glosa06_2026q1" in result.stderr
    assert "ERROR" in result.stderr
    assert not (tmp_path / "processed").exists() or not list(
        (tmp_path / "processed").glob("*.parquet")
    )


def test_offline_without_cache_exits_1_and_never_touches_the_network(tmp_path: Path) -> None:
    result = runner.invoke(app, ["glosa06_2025q3", "--offline", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "offline" in result.stderr.lower()


def test_all_offline_reports_every_source_and_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["all", "--offline", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    for source_id in ALL_IDS:
        assert source_id in result.output
    assert "0 OK" in result.output
    assert "5 con error" in result.output


def test_input_option_is_only_for_single_sources(tmp_path: Path) -> None:
    result = runner.invoke(app, ["all", "--input", "x", "--data-dir", str(tmp_path)])
    assert result.exit_code == 2


def test_fail_fast_is_only_for_all(tmp_path: Path) -> None:
    result = runner.invoke(app, ["glosa06_2025q3", "--fail-fast", "--data-dir", str(tmp_path)])
    assert result.exit_code == 2


def _fake_run_source(failing: set[str], calls: list[str]):  # type: ignore[no-untyped-def]
    def fake(source_id: str, *, data_dir: Path, today: date, **_: object) -> RunResult:
        calls.append(source_id)
        if source_id in failing:
            return RunResult(source_id, ok=False, error=f"[{source_id}/t] se rompió algo")
        return RunResult(source_id, ok=True, rows=7, output=data_dir / f"{source_id}.parquet")

    return fake


def test_all_with_one_failing_source_exits_1_with_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "run_source", _fake_run_source({"glosa06_2025q4"}, calls))
    result = runner.invoke(app, ["all", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert calls == ALL_IDS  # sin --fail-fast se procesan todas
    assert "OK" in result.output
    assert "glosa06_2025q4" in result.stderr
    assert "se rompió algo" in result.stderr
    assert "Resumen: 4 OK, 1 con error" in result.output


def test_all_with_every_source_ok_exits_0(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "run_source", _fake_run_source(set(), calls))
    result = runner.invoke(app, ["all", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Resumen: 5 OK, 0 con error" in result.output


def test_all_fail_fast_stops_at_the_first_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "run_source", _fake_run_source({"glosa06_2025q4"}, calls))
    result = runner.invoke(app, ["all", "--fail-fast", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert calls == ["glosa06_2025q3", "glosa06_2025q4"]


def test_data_dir_defaults_to_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "from_env"))
    get_settings.cache_clear()
    try:
        seen: list[Path] = []

        def fake(source_id: str, *, data_dir: Path, today: date, **_: object) -> RunResult:
            seen.append(data_dir)
            return RunResult(source_id, ok=True, rows=1, output=data_dir)

        monkeypatch.setattr(pipeline, "run_source", fake)
        result = runner.invoke(app, ["all"])
        assert result.exit_code == 0, result.output
        assert set(seen) == {tmp_path / "from_env"}
    finally:
        get_settings.cache_clear()


# --- pipeline directo -----------------------------------------------------------------------------


def test_run_source_reports_failures_instead_of_raising(tmp_path: Path) -> None:
    result = pipeline.run_source(
        "glosa06_2025q3", data_dir=tmp_path, today=date(2026, 10, 3), offline=True
    )
    assert isinstance(result, RunResult)
    assert result.ok is False
    assert result.rows == 0
    assert result.output is None
    assert result.error and "glosa06_2025q3" in result.error


def test_run_source_with_input_is_idempotent(fixtures_dir: Path, tmp_path: Path) -> None:
    xlsx = _fixture(fixtures_dir, "sis_ges", "sis_ges_cases_mini.xlsx")
    first = pipeline.run_source(
        "sis_ges_cases_2026q1", data_dir=tmp_path, today=date(2026, 10, 3), input_path=xlsx
    )
    second = pipeline.run_source(
        "sis_ges_cases_2026q1", data_dir=tmp_path, today=date(2026, 10, 4), input_path=xlsx
    )
    assert first.ok and second.ok
    assert first.output == second.output
    assert pl.read_parquet(first.output).equals(pl.read_parquet(second.output))  # type: ignore[arg-type]
    assert first.rows == second.rows == 50
