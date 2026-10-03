"""Línea de comandos ``prioriza-ingest``."""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from shared.config import get_settings

from ingestion.pipeline import RunResult, run_all, run_source
from ingestion.sources import SOURCES

app = typer.Typer(
    help="Descarga y procesa datos públicos agregados (sin datos de pacientes).",
    no_args_is_help=True,
    add_completion=False,
)

DataDirOption = Annotated[
    Path | None,
    typer.Option("--data-dir", help="Directorio de datos (por defecto, DATA_DIR o ./data)."),
]
RefreshOption = Annotated[bool, typer.Option("--refresh", help="Fuerza la descarga.")]
OfflineOption = Annotated[bool, typer.Option("--offline", help="Usa solo la caché local.")]


def _data_dir(value: Path | None) -> Path:
    return value if value is not None else get_settings().data_dir


def _describe(result: RunResult) -> str:
    if result.ok:
        line = f"OK    {result.source_id}: {result.rows} filas -> {result.output}"
        if result.warnings:
            line += f" ({len(result.warnings)} advertencias)"
        return line
    return f"ERROR {result.source_id}: {result.error}"


def _echo_warnings(result: RunResult) -> None:
    for warning in result.warnings:
        typer.echo(f"  advertencia: {warning}", err=True)


@app.command("list")
def list_sources() -> None:
    """Lista las fuentes registradas."""
    for spec in SOURCES.values():
        period = spec.period.isoformat() if spec.period else "-"
        typer.echo(f"{spec.source_id}\t{spec.ref}\t{spec.kind.value}\t{period}\t{spec.title}")


@app.command("all")
def run_everything(
    data_dir: DataDirOption = None,
    refresh: RefreshOption = False,
    offline: OfflineOption = False,
    fail_fast: Annotated[
        bool, typer.Option("--fail-fast", help="Se detiene en la primera fuente que falle.")
    ] = False,
) -> None:
    """Procesa todas las fuentes y muestra un resumen; sale con 1 si alguna falla."""
    results = run_all(
        data_dir=_data_dir(data_dir),
        today=date.today(),
        refresh=refresh,
        offline=offline,
        fail_fast=fail_fast,
    )
    for result in results:
        typer.echo(_describe(result), err=not result.ok)
        _echo_warnings(result)
    failed = [r for r in results if not r.ok]
    typer.echo(f"Resumen: {len(results) - len(failed)} OK, {len(failed)} con error.")
    if failed:
        raise typer.Exit(code=1)


def _make_command(source_id: str) -> Callable[..., None]:
    def command(
        data_dir: DataDirOption = None,
        refresh: RefreshOption = False,
        offline: OfflineOption = False,
        input_path: Annotated[
            Path | None,
            typer.Option("--input", help="Procesa este archivo local en vez de descargar."),
        ] = None,
    ) -> None:
        result = run_source(
            source_id,
            data_dir=_data_dir(data_dir),
            today=date.today(),
            refresh=refresh,
            offline=offline,
            input_path=input_path,
        )
        typer.echo(_describe(result), err=not result.ok)
        _echo_warnings(result)
        if not result.ok:
            raise typer.Exit(code=1)

    command.__doc__ = f"Procesa la fuente {source_id}."
    return command


for _source_id in SOURCES:
    app.command(_source_id)(_make_command(_source_id))


def main() -> None:
    """Punto de entrada del script ``prioriza-ingest``."""
    app()
