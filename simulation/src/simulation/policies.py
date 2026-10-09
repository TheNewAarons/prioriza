"""Políticas de agendamiento comparadas (diseño §5).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from scheduler.config import OverbookingConfig, SchedulerConfig, SolverConfig
from scheduler.instance import SchedulingInstance
from scheduler.plan import SchedulePlan, greedy_schedule, solve

from simulation.config import SimulationConfig


def scheduler_config(config: SimulationConfig, policy: str) -> SchedulerConfig:
    """Configuración del programador de la política (solo el sobrecupo y el ``noshow`` cambian)."""
    return SchedulerConfig(
        horizon_weeks=config.horizon_weeks,
        commit_weeks=config.commit_weeks,
        time_limit_s=config.time_limit_s,
        match_level=config.match_level,
        overbooking=OverbookingConfig(
            enabled=policy == "optimized_overbooking", alpha=config.overbooking_alpha
        ),
        solver=SolverConfig(num_workers=1, deterministic=True),
    )


def apply(instance: SchedulingInstance, config: SchedulerConfig, policy: str) -> SchedulePlan:
    """Plan de la política sobre la instancia."""
    if policy == "fifo":
        return greedy_schedule(instance, config, "fifo")
    if policy == "priority":
        return greedy_schedule(instance, config, "priority")
    return solve(instance, config)
