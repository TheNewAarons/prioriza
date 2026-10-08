"""Línea de comandos ``prioriza-synth``: build-targets, generate y validate.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from shared.db.enums import NoShowScenario

from synthetic.config import RunConfig
from synthetic.io import DISCLAIMER, write_parquet
from synthetic.pipeline import generate
from synthetic.targets import (
    build_targets,
    load_assumptions,
    load_targets,
    write_json_canonical,
)
from synthetic.validate import CalibrationReport, calibration_report

app = typer.Typer(
    help="Genera población sintética calibrada contra datos públicos agregados. " + DISCLAIMER,
    no_args_is_help=True,
    add_completion=False,
)

SizeOption = Annotated[int, typer.Option("--size", min=1000, help="Número de entradas (>= 1.000).")]
SeedOption = Annotated[int, typer.Option("--seed", help="Semilla fija.")]
ScenarioOption = Annotated[
    NoShowScenario, typer.Option("--scenario", help="Escenario de inasistencias.")
]
HorizonOption = Annotated[int, typer.Option("--horizon-weeks", min=1, help="Semanas de oferta.")]
AsOfOption = Annotated[
    str | None, typer.Option("--as-of", help="Fecha de referencia ISO (desplaza todas las fechas).")
]


def _config(
    size: int, seed: int, scenario: NoShowScenario, horizon: int, as_of: str | None
) -> RunConfig:
    return RunConfig(
        size=size,
        seed=seed,
        scenario=scenario,
        horizon_weeks=horizon,
        as_of=date.fromisoformat(as_of) if as_of else None,
    )


def _print_report(report: CalibrationReport) -> None:
    s = report.summary
    typer.echo(
        f"Calibración: {s['strict_passed']} chequeos estrictos pasan, {s['strict_failed']} fallan; "
        f"{s['soft_failed']} blandos con aviso, {s['skipped']} omitidos."
    )
    for c in report.checks:
        if (c.severity == "strict" and not c.passed) or (c.severity == "soft" and not c.passed):
            tag = "FALLA" if c.severity == "strict" else "aviso"
            typer.echo(
                f"  [{tag}] {c.name}: observado={c.observed} objetivo={c.target} {c.detail[:2]}"
            )
    for note in report.notes:
        typer.echo(f"  nota: {note}")


@app.command("build-targets")
def build_targets_cmd(
    processed_dir: Annotated[
        Path, typer.Option("--processed-dir", help="Directorio de parquet.")
    ] = Path("data/processed"),
    out: Annotated[
        Path | None, typer.Option("--out", help="Destino (por defecto, el JSON del paquete).")
    ] = None,
    reference: Annotated[str, typer.Option("--reference")] = "glosa06_2025q3",
) -> None:
    """Regenera ``calibration_targets.json`` desde los parquet de ingesta."""
    from importlib import resources

    target = out or Path(str(resources.files("synthetic") / "targets" / "calibration_targets.json"))
    sha = write_json_canonical(build_targets(processed_dir, reference), target)
    typer.echo(f"{target} sha256={sha}")


@app.command("generate")
def generate_cmd(
    size: SizeOption,
    seed: SeedOption = 42,
    scenario: ScenarioOption = NoShowScenario.BASELINE,
    horizon_weeks: HorizonOption = 26,
    as_of: AsOfOption = None,
    load: Annotated[bool, typer.Option("--load/--no-load", help="Carga a PostgreSQL.")] = False,
    replace: Annotated[
        bool, typer.Option("--replace", help="Reemplaza la corrida si existe.")
    ] = False,
    out: Annotated[Path, typer.Option("--out", help="Directorio de salida.")] = Path(
        "data/synthetic"
    ),
    report_dir: Annotated[Path, typer.Option("--report-dir")] = Path("results"),
) -> None:
    """Genera la población, valida la calibración, escribe parquet y opcionalmente carga a la BD."""
    cfg = _config(size, seed, scenario, horizon_weeks, as_of)
    typer.echo(DISCLAIMER)
    t0 = time.perf_counter()
    targets, assumptions = load_targets(), load_assumptions()
    ds = generate(cfg, targets, assumptions)
    t_gen = time.perf_counter() - t0
    report = calibration_report(ds, targets, assumptions)
    t_val = time.perf_counter() - t0 - t_gen
    run_dir = write_parquet(ds, out, report)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"synthetic_calibration_seed{seed}_n{size}.json"
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    typer.echo(f"run_id={ds.run['id']}")
    typer.echo(f"digest={ds.digest}")
    typer.echo(f"parquet={run_dir}  informe={report_path}")
    typer.echo(f"tiempos: generación {t_gen:.1f} s, validación {t_val:.1f} s")
    _print_report(report)
    if not report.passed:
        typer.echo("La calibración estricta falló; no se carga a la base.", err=True)
        raise typer.Exit(code=2)
    if load:
        from shared.db.session import get_engine

        from synthetic.load import LoadError, count_rows, load_dataset

        engine = get_engine()
        t1 = time.perf_counter()
        try:
            load_dataset(ds, engine, replace=replace)
        except LoadError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"carga a PostgreSQL: {time.perf_counter() - t1:.1f} s")
        from uuid import UUID

        for name, count in count_rows(engine, UUID(str(ds.run["id"]))).items():
            typer.echo(f"  {name}: {count}")


@app.command("validate")
def validate_cmd(
    size: SizeOption,
    seed: SeedOption = 42,
    scenario: ScenarioOption = NoShowScenario.BASELINE,
    horizon_weeks: HorizonOption = 26,
    as_of: AsOfOption = None,
) -> None:
    """Genera en memoria e imprime el informe de calibración (código de salida 2 si falla)."""
    cfg = _config(size, seed, scenario, horizon_weeks, as_of)
    targets, assumptions = load_targets(), load_assumptions()
    ds = generate(cfg, targets, assumptions)
    report = calibration_report(ds, targets, assumptions)
    _print_report(report)
    if not report.passed:
        raise typer.Exit(code=2)


def main() -> None:
    """Punto de entrada de ``prioriza-synth``."""
    app()
