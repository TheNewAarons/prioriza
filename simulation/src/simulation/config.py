"""Configuración de la simulación de políticas (diseño §1/§4/§6/§8).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

POLICIES: tuple[str, ...] = ("fifo", "priority", "optimized", "optimized_overbooking")
DEFAULT_REPLICA_SEEDS: tuple[int, ...] = (101, 102, 103, 104, 105)


class SimulationConfig(BaseModel):
    """Parámetros de una corrida; junto con el mundo fijan el resultado (salvo reloj)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    weeks: int = Field(default=26, ge=1)
    horizon_weeks: int = Field(default=4, ge=1, le=52)
    commit_weeks: int = Field(default=1, ge=1)
    time_limit_s: float = Field(default=30.0, gt=0.0)
    match_level: Literal["health_service", "establishment"] = "health_service"
    capacity_multiplier: float = Field(default=1.0, gt=0.0)
    abandon_weekly_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    overbooking_alpha: float = Field(default=0.10, gt=0.0, lt=1.0)
    max_no_shows: int = Field(default=2, ge=1)
    policies: tuple[str, ...] = POLICIES
    replica_seeds: tuple[int, ...] = DEFAULT_REPLICA_SEEDS

    @model_validator(mode="after")
    def _check(self) -> SimulationConfig:
        unknown = [p for p in self.policies if p not in POLICIES]
        if unknown:
            raise ValueError(f"políticas desconocidas: {unknown}")
        if not self.replica_seeds:
            raise ValueError("replica_seeds no puede quedar vacío")
        return self
