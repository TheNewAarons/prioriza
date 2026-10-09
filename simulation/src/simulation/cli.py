"""CLI ``prioriza-simulate`` (diseño §8).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from scheduler.bench import ensure_run, train_model
from shared.db.enums import NoShowScenario
from shared.disclaimer import DISCLAIMER

from simulation.config import POLICIES, SimulationConfig
from simulation.report import run_experiment
from simulation.world import world_from_run

GENERATOR_WEEKS = 26  # horizonte por defecto de RunConfig

app = typer.Typer(
    help="Simulación de políticas de programación. " + DISCLAIMER, add_completion=False
)


def _split_ints(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


@app.command()
def main(
    size: Annotated[int, typer.Option("--size", help="Entradas de la corrida sintética.")] = 10_000,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    scenario: Annotated[NoShowScenario, typer.Option("--scenario")] = NoShowScenario.BASELINE,
    weeks: Annotated[int, typer.Option("--weeks", min=1, help="Semanas de citas simuladas.")] = 26,
    replicas: Annotated[int, typer.Option("--replicas", min=1)] = 5,
    replica_seeds: Annotated[
        str | None, typer.Option("--replica-seeds", help="Semillas, por coma.")
    ] = None,
    horizon_weeks: Annotated[int, typer.Option("--horizon-weeks", min=1, max=52)] = 4,
    time_limit: Annotated[float, typer.Option("--time-limit", min=0.1)] = 30.0,
    policies: Annotated[
        str, typer.Option("--policies", help="Políticas separadas por coma.")
    ] = ",".join(POLICIES),
    capacity_multiplier: Annotated[float, typer.Option("--capacity-multiplier", min=0.01)] = 1.0,
    abandon_weekly_rate: Annotated[
        float, typer.Option("--abandon-weekly-rate", min=0.0, max=1.0)
    ] = 0.0,
    work_dir: Annotated[Path, typer.Option("--work-dir")] = Path("data/simulation"),
    out: Annotated[Path, typer.Option("--out")] = Path("results/simulation.json"),
) -> None:
    """Genera la corrida, entrena el modelo si falta y escribe el informe JSON."""
    typer.echo(DISCLAIMER)
    seeds = _split_ints(replica_seeds) if replica_seeds else [101 + i for i in range(replicas)]
    policy_list = tuple(p for p in policies.split(",") if p.strip())
    config = SimulationConfig(
        weeks=weeks,
        horizon_weeks=horizon_weeks,
        time_limit_s=time_limit,
        capacity_multiplier=capacity_multiplier,
        abandon_weekly_rate=abandon_weekly_rate,
        policies=policy_list,
        replica_seeds=tuple(seeds),
    )
    # La oferta del generador no se usa (diseño §3): se fija su horizonte para reutilizar
    # la misma corrida con cualquier número de semanas simuladas.
    run = ensure_run(work_dir, size, seed, scenario.value, GENERATOR_WEEKS)
    run_dir: Path = run["run_dir"]
    run_id: str = run["run_id"]
    model_version = train_model(work_dir, run_dir, seed)
    model_path = work_dir / "models" / run_id / "noshow_model.joblib"
    world = world_from_run(run_dir, model_path)
    typer.echo(
        f"corrida={run_id} as_of={world.as_of} semanas={weeks} réplicas={seeds} "
        f"modelo={model_version}"
    )
    payload = run_experiment(world, config)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"informe={out}")


def run() -> None:
    """Punto de entrada de ``prioriza-simulate``."""
    app()
