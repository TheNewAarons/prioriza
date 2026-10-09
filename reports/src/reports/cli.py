"""Comando ``prioriza-report``: genera ``docs/results.md`` y ``docs/results.html``.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión
real sin validación institucional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from reports.build import build_report
from reports.facts import FactsError

app = typer.Typer(add_completion=False, help="Genera el informe de resultados de Prioriza.")


@app.command()
def main(
    results_dir: Annotated[
        Path, typer.Option("--results-dir", help="Carpeta con los JSON de resultados.")
    ] = Path("results"),
    out_dir: Annotated[
        Path, typer.Option("--out-dir", help="Carpeta de salida del informe.")
    ] = Path("docs"),
    repo_root: Annotated[
        Path, typer.Option("--repo-root", help="Raíz del repositorio (para el commit de results/).")
    ] = Path(),
) -> None:
    """Lee ``results/`` y escribe el informe en Markdown y HTML."""
    try:
        md_path, html_path = build_report(results_dir, out_dir, repo_root)
    except FactsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Informe escrito en {md_path} y {html_path}")


def run() -> None:
    """Punto de entrada de ``prioriza-report``."""
    app()
