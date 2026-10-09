"""Simulación de políticas de programación para Prioriza.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

API pública mínima: ``SimulationConfig``, ``World``, ``world_from_run``, ``simulate`` y
``run_experiment`` (diseño §9).
"""

from simulation.config import SimulationConfig
from simulation.engine import simulate
from simulation.metrics import PolicyResult
from simulation.report import run_experiment
from simulation.world import World, world_from_run

__all__ = [
    "PolicyResult",
    "SimulationConfig",
    "World",
    "run_experiment",
    "simulate",
    "world_from_run",
]
