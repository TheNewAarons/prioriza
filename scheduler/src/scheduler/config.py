"""Configuración del programador (formulación §12).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OverbookingConfig(_Frozen):
    """Sobreagendamiento en sesiones CNE (formulación §6.3)."""

    enabled: bool = True
    alpha: float = Field(default=0.10, gt=0.0, lt=1.0)
    max_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    p_clip_low: float = Field(default=0.001, gt=0.0, lt=1.0)
    p_clip_high: float = Field(default=0.95, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _check_clip(self) -> OverbookingConfig:
        if self.p_clip_low >= self.p_clip_high:
            raise ValueError("p_clip_low debe ser menor que p_clip_high")
        return self


GroupDimension = Literal["age_group", "insurance", "commune_code"]


class GroupLimitsConfig(_Frozen):
    """Límites de exposición al sobrecupo por grupo (contrato provisional con P6, §6.5)."""

    enabled: bool = True
    dimensions: tuple[GroupDimension, ...] = ("age_group", "insurance", "commune_code")
    mode: Literal["relative", "absolute"] = "relative"
    max_gap_pp: float = Field(default=5.0, ge=0.0, le=100.0)
    max_share: float | None = Field(default=None, ge=0.0, le=1.0)
    min_group_n: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def _check_mode(self) -> GroupLimitsConfig:
        if self.mode == "absolute" and self.max_share is None:
            raise ValueError("mode absolute requiere max_share")
        return self


class WeightsConfig(_Frozen):
    """Términos secundarios del objetivo (§6.6)."""

    earliness: float = Field(default=0.05, ge=0.0, lt=1.0)
    ges_delay_points_per_day: float = Field(default=1.0, ge=0.0)
    balance_tolerance: float = Field(default=0.0, ge=0.0, lt=1.0)


class SolverConfig(_Frozen):
    """Parámetros de CP-SAT (§8.5)."""

    num_workers: int = Field(default=8, ge=1)
    deterministic: bool = True
    relative_gap_limit: float = Field(default=0.001, ge=0.0)
    linearization_level: int = Field(default=2, ge=0, le=2)
    log_search_progress: bool = False
    # Técnicas de rendimiento (§8.6); apagarlas solo sirve para medir su efecto.
    hints: bool = True
    symmetry_breaking: bool = True
    prune_overbooking_levels: bool = True
    objective_cut: bool = True
    overbooking_hint: bool = True
    warm_start_frontier: bool = True


class SchedulerConfig(_Frozen):
    """Configuración completa; su digest se registra con cada plan."""

    horizon_weeks: int = Field(default=4, ge=1, le=52)
    match_level: Literal["health_service", "establishment"] = "health_service"
    min_lead_days: int = Field(default=7, ge=0)
    ges_min_lead_days: int = Field(default=2, ge=0)
    or_turnover_min: int = Field(default=30, ge=0)
    or_max_fill: float = Field(default=0.85, gt=0.0, le=1.0)
    max_per_patient_per_day: Literal[1] = 1
    overbooking: OverbookingConfig = OverbookingConfig()
    group_limits: GroupLimitsConfig = GroupLimitsConfig()
    weights: WeightsConfig = WeightsConfig()
    candidate_margin: float = Field(default=2.0, ge=1.0)
    expand_on_frontier: bool = True
    decomposition: Literal["auto", "specialty"] = "auto"
    max_pairs_per_subproblem: int = Field(default=400_000, ge=1)
    commit_weeks: int = Field(default=1, ge=1)
    or_standby_size: int = Field(default=3, ge=0)
    time_limit_s: float = Field(default=120.0, gt=0.0)
    solver: SolverConfig = SolverConfig()

    def digest(self) -> str:
        """SHA-256 del JSON canónico de la configuración."""
        text = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
