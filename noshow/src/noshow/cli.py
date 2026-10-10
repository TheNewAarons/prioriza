"""Línea de comandos ``prioriza-noshow``.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

import typer
from shared.db.enums import NoShowScenario
from shared.disclaimer import DISCLAIMER

from noshow.data import find_run_dir, load_run
from noshow.train import TrainConfig, save, train

app = typer.Typer(
    help="Modelo de inasistencias (scikit-learn, calibrado). " + DISCLAIMER,
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """Agrupa los subcomandos (``train``)."""


@app.command("train")
def train_cmd(
    seed: Annotated[int, typer.Option("--seed", help="Semilla de la corrida y del modelo.")] = 42,
    size: Annotated[int, typer.Option("--size", help="Tamaño de la corrida sintética.")] = 100_000,
    scenario: Annotated[
        NoShowScenario, typer.Option("--scenario", help="Escenario de inasistencias.")
    ] = NoShowScenario.BASELINE,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="Directorio de corridas sintéticas.")
    ] = Path("data/synthetic"),
    run_dir: Annotated[
        Path | None, typer.Option("--run-dir", help="Corrida explícita (ignora seed/size).")
    ] = None,
    models_dir: Annotated[
        Path, typer.Option("--models-dir", help="Destino de los artefactos.")
    ] = Path("models/noshow"),
    results: Annotated[Path, typer.Option("--results", help="Informe JSON.")] = Path(
        "results/noshow.json"
    ),
    test_days: Annotated[int, typer.Option("--test-days", min=1)] = 180,
    calibration_days: Annotated[int, typer.Option("--calibration-days", min=1)] = 120,
    diagnostic: Annotated[
        bool,
        typer.Option(
            "--diagnostic/--no-diagnostic",
            help="Agrega a results el diagnóstico (solo medición) del costo de las variables "
            "excluidas por equidad. No cambia el modelo ni el artefacto.",
        ),
    ] = True,
) -> None:
    """Entrena, calibra y evalúa el modelo; escribe el artefacto y ``results/noshow.json``.

    Con ``--diagnostic`` (por defecto) agrega ``diagnostic_excluded`` al informe; los modelos de
    diagnóstico no se guardan en el artefacto.
    """
    typer.echo(DISCLAIMER)
    if run_dir is None:
        try:
            run_dir = find_run_dir(data_dir, seed, size, scenario.value, current_generator_shas())
        except (FileNotFoundError, FileExistsError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    config = TrainConfig(seed=seed, test_days=test_days, calibration_days=calibration_days)
    t0 = time.perf_counter()
    run = load_run(run_dir)
    output = train(run, config)
    t_main = time.perf_counter() - t0
    if diagnostic:
        # importación diferida: ``scheduler.cli`` importa este módulo y no debe cargar el
        # diagnóstico
        from noshow.diagnostic import diagnose_excluded

        diag = diagnose_excluded(run, config, output)
        output = replace(output, results={**output.results, "diagnostic_excluded": diag})
    artifact = save(output, models_dir, results)
    r = output.results
    typer.echo(f"corrida={run_dir.name} modelo={r['model_version']}")
    typer.echo(f"calibración={r['calibration']['method']} principal={r['selection']['primary']}")
    for name, m in r["test_metrics"].items():
        typer.echo(f"  {name:36s} AUC={m['auc']:.4f} Brier={m['brier']:.5f} ECE={m['ece']:.4f}")
    oracle = r["oracle_reference"]["metrics"]
    if oracle is not None:
        typer.echo(
            f"  {'oráculo (verdad sintética)':36s} AUC={oracle['auc']:.4f} "
            f"Brier={oracle['brier']:.5f}"
        )
    cmp_ = r["primary_vs_baseline"]
    typer.echo(
        f"Δ Brier principal - baseline = {cmp_['brier_difference']:+.5f} "
        f"(IC95 {cmp_['ci95_low']:+.5f} a {cmp_['ci95_high']:+.5f})"
    )
    if diagnostic:
        _echo_diagnostic(output.results["diagnostic_excluded"])
    typer.echo(
        f"artefacto={artifact} informe={results} (modelo {t_main:.1f} s, total "
        f"{time.perf_counter() - t0:.1f} s)"
    )


def _echo_diagnostic(diag: dict[str, Any]) -> None:
    """Resumen en consola del diagnóstico de variables excluidas (solo medición)."""
    typer.echo("Diagnóstico de variables excluidas (solo medición, no se persiste):")
    for name, v in diag["variants"].items():
        m, c = v["test_metrics"], v["vs_primary"]
        typer.echo(
            f"  {name:36s} AUC={m['auc']:.4f} Brier={m['brier']:.5f} ECE={m['ece']:.4f} "
            f"Δ Brier={c['brier_difference']:+.5f} "
            f"(IC95 {c['ci95_low']:+.5f} a {c['ci95_high']:+.5f})"
        )


def current_generator_shas() -> dict[str, str]:
    """Huellas de los objetivos y supuestos vigentes del generador sintético."""
    from synthetic.targets import load_assumptions, load_targets, sha256_text

    return {
        "targets_sha256": sha256_text(load_targets()),
        "params_sha256": sha256_text(load_assumptions()),
    }


def main() -> None:
    """Punto de entrada de ``prioriza-noshow``."""
    app()
