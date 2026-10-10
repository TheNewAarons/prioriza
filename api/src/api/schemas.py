"""Modelos de entrada y salida de la API.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Toda respuesta de lista de espera, paciente, plan, trabajo, revisión y simulación hereda de
`DisclaimerModel` y lleva el aviso obligatorio en el campo `disclaimer`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from shared.db.enums import (
    AgeGroup,
    ClinicalPriority,
    Insurance,
    Policy,
    ReviewAction,
    ReviewStatus,
)
from shared.disclaimer import DISCLAIMER
from shared.schemas import CareType


class DisclaimerModel(BaseModel):
    """Base de las respuestas con aviso obligatorio."""

    disclaimer: str = Field(default=DISCLAIMER, description="Aviso obligatorio de uso.")


class ErrorOut(BaseModel):
    """Cuerpo de los errores (401, 403, 404, 409, 503)."""

    detail: str


class MeOut(DisclaimerModel):
    """Usuario autenticado (con el aviso, como toda respuesta con datos de la API)."""

    user: str
    role: Literal["gestor", "revisor", "lectura"]


class StrictTierName(StrEnum):
    """Nivel estricto GES del puntaje."""

    NONE = "NONE"
    GES_DUE_SOON = "GES_DUE_SOON"
    GES_OVERDUE = "GES_OVERDUE"


class WaitlistOrder(StrEnum):
    """Orden de la lista de espera."""

    RANK = "rank"
    SCORE = "score"
    ENTRY_DATE = "entry_date"


# ------------------------------------------------------------------ lista de espera


class WaitlistItemOut(BaseModel):
    """Entrada en espera con su puntaje; `rank` es el puesto dentro de su cola."""

    entry_id: str
    patient_id: str
    health_service_code: int
    specialty_code: str
    care_type: CareType
    clinical_priority: ClinicalPriority
    is_ges: bool
    ges_deadline: date | None
    entry_date: date
    wait_days: int
    score: float
    rank: int = Field(description="Puesto (desde 1) en la cola: servicio, especialidad y tipo.")
    tier: StrictTierName


class WaitlistPageOut(DisclaimerModel):
    """Página de la lista de espera."""

    total: int
    limit: int
    offset: int
    items: list[WaitlistItemOut]


class ComponentOut(BaseModel):
    """Aporte de un componente al puntaje de priorización."""

    field: str
    label: str
    raw_value: str | int | None
    normalized: float
    weight: float
    contribution: float


class PatientEntryOut(BaseModel):
    """Entrada de un paciente; sin puntaje ni explicación si ya no está en espera."""

    entry_id: str
    patient_id: str
    health_service_code: int
    specialty_code: str
    care_type: CareType
    clinical_priority: ClinicalPriority
    is_ges: bool
    ges_deadline: date | None
    entry_date: date
    status: str
    wait_days: int | None
    score: float | None
    rank: int | None
    tier: StrictTierName | None
    explanation: dict[str, Any] | None = Field(
        description="Explicación del puntaje (`priority.explanation_to_dict`)."
    )
    components: list[ComponentOut] | None = Field(
        default=None,
        description="Desglose del puntaje por componente (null si no está en espera).",
    )


class WaitHistogramBin(BaseModel):
    """Tramo del histograma de espera (30 días; el último es '720 o más')."""

    from_day: int
    to_day: int | None = Field(description="null en el tramo final '720 o más'.")
    count: int


class CareTypeSummary(BaseModel):
    """Resumen de un tipo de atención (consulta o cirugía)."""

    care_type: CareType
    total: int
    wait_median: float | None
    wait_p90: float | None
    ges_total: int
    ges_at_risk: int
    ges_overdue: int


class WaitlistSummaryOut(DisclaimerModel):
    """Resumen agregado de la lista de espera, calculado una vez por corrida."""

    as_of: date
    run_id: str = Field(description="Identificador de la corrida sintética en uso.")
    run_entries: int = Field(description="Entradas de la corrida (en espera o no).")
    total: int
    wait_median: float | None
    wait_p90: float | None
    ges_total: int
    ges_at_risk: int = Field(description="GES no vencida con plazo a 30 días o menos de as_of.")
    ges_overdue: int = Field(description="GES con plazo anterior a as_of.")
    by_care_type: list[CareTypeSummary]
    wait_histogram: list[WaitHistogramBin]


class PatientOut(DisclaimerModel):
    """Paciente sintético (sin nombre, RUT, sexo ni fecha de nacimiento)."""

    patient_id: str
    health_service_code: int
    commune_code: str
    age_group: AgeGroup
    insurance: Insurance
    entries: list[PatientEntryOut]


# ------------------------------------------------------------------ programación


class ScheduleRequestIn(BaseModel):
    """Parámetros de una programación. `overbooking` y `alpha` solo afectan a `optimized`."""

    model_config = ConfigDict(extra="forbid")

    policy: Policy
    horizon_weeks: int = Field(default=4, ge=1, le=52)
    overbooking: bool = True
    alpha: float = Field(default=0.10, gt=0.0, lt=1.0)
    time_limit_s: float = Field(default=120.0, gt=0.0, le=3600.0)


class JobStatus(StrEnum):
    """Estado de un trabajo de programación."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobOut(DisclaimerModel):
    """Trabajo de programación; el plan resultante nace `pending` (requiere revisión humana)."""

    job_id: uuid.UUID
    status: JobStatus
    policy: Policy
    requested_by: str
    created_at: datetime
    plan_id: uuid.UUID | None = None
    error: str | None = None


# ------------------------------------------------------------------ planes


class PlanSummaryOut(DisclaimerModel):
    """Plan y su estado de revisión. Todo plan requiere revisión humana antes de usarse."""

    plan_id: uuid.UUID
    run_id: str
    policy: Policy
    review_status: ReviewStatus
    is_current: bool
    requested_by: str | None
    created_at: datetime
    solver_status: str | None
    objective_value: float | None
    horizon_start: date
    horizon_end: date


class PlanDetailOut(PlanSummaryOut):
    """Resumen del informe del plan, con los resultados de equidad tal cual salieron."""

    summary: dict[str, Any]
    ges: dict[str, Any]
    equity: list[dict[str, Any]]
    warnings: list[str]
    config: dict[str, Any]


class PlanPageOut(DisclaimerModel):
    """Página de planes."""

    total: int
    limit: int
    offset: int
    items: list[PlanSummaryOut]


class AssignmentOut(BaseModel):
    """Cita propuesta por el plan."""

    entry_id: str
    patient_id: str
    slot_id: str
    specialty_code: str | None
    scheduled_start: datetime
    duration_min: int
    lead_days: int | None
    is_overbooked: bool
    predicted_noshow_prob: float | None


class AssignmentPageOut(DisclaimerModel):
    """Página de asignaciones."""

    total: int
    limit: int
    offset: int
    items: list[AssignmentOut]


class ExplanationOut(BaseModel):
    """Por qué una entrada quedó (o no) en el plan."""

    entry_id: str
    status: str
    detail: str | None
    text: str


class ExplanationPageOut(DisclaimerModel):
    """Página de explicaciones."""

    total: int
    limit: int
    offset: int
    items: list[ExplanationOut]


class EntryScoreOut(BaseModel):
    """Puntaje de priorización de la entrada (la prioridad clínica es un dato de entrada)."""

    patient_id: str
    clinical_priority: ClinicalPriority
    is_ges: bool
    ges_deadline: date | None
    entry_date: date
    wait_days: int | None
    score: float | None
    rank: int | None
    tier: StrictTierName | None
    explanation: dict[str, Any] | None
    components: list[ComponentOut]


class BlockLoadOut(BaseModel):
    """Carga del bloque con sobrecupo donde quedó la cita (de `report.overbooking.blocks`)."""

    capacity: int
    scheduled: int
    overbooked: int
    risk_exact: float = Field(description="Probabilidad de desborde de la sesión (0 a 1).")


class EntryReasonOut(DisclaimerModel):
    """Por qué una entrada tiene (o no) su cupo en el plan, con todo lo que el plan guardó.

    `phase` es `3a` (agendada sin sobrecupo) o `3b` (entró gracias al sobreagendamiento) en la
    política optimizada, y el nombre de la política en las demás. `None` si no quedó agendada.
    """

    plan_id: uuid.UUID
    entry_id: str
    policy: Policy
    status: str
    detail: str | None
    text: str
    phase: str | None
    assignment: AssignmentOut | None
    block_load: BlockLoadOut | None
    ges: GesItemOut | None
    score: EntryScoreOut | None = Field(
        description="Puntaje actual de la lista de espera; null si ya no está en espera."
    )


class CompareSideOut(BaseModel):
    """Identificación de uno de los dos planes comparados."""

    plan_id: uuid.UUID
    policy: Policy
    review_status: ReviewStatus
    is_current: bool
    created_at: datetime
    requested_by: str | None
    solver_status: str | None


class CompareMetricOut(BaseModel):
    """Una métrica en ambos planes; `diff` = b - a. `better` dice qué plan es mejor."""

    key: str
    label: str
    direction: Literal["higher_is_better", "lower_is_better", "neutral"]
    a: float | None
    b: float | None
    diff: float | None
    better: Literal["a", "b", "tie", "none"]


class CompareEquityOut(CompareMetricOut):
    """Métrica de equidad de un grupo (dimensión y valor)."""

    dimension: str
    value: str


class PlanCompareOut(DisclaimerModel):
    """Dos planes de la misma corrida lado a lado; los resultados desfavorables se muestran."""

    run_id: str
    a: CompareSideOut
    b: CompareSideOut
    metrics: list[CompareMetricOut]
    equity: list[CompareEquityOut]


class ReviewIn(BaseModel):
    """Decisión del revisor sobre un plan pendiente (final)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal[ReviewStatus.APPROVED, ReviewStatus.REJECTED]
    note: str | None = Field(default=None, max_length=2000)


class ActivateIn(BaseModel):
    """Nota opcional al marcar un plan aprobado como vigente."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class ReviewRecordOut(BaseModel):
    """Registro de auditoría."""

    id: uuid.UUID
    action: ReviewAction
    user_name: str
    role: str
    note: str | None
    created_at: datetime


class ReviewListOut(DisclaimerModel):
    """Auditoría de un plan en orden cronológico."""

    plan_id: uuid.UUID
    items: list[ReviewRecordOut]


# ------------------------------------------------------------------ simulación


class SimulationOut(DisclaimerModel):
    """Resumen de `results/simulation.json` (sin las réplicas individuales)."""

    generated_at: str
    run: dict[str, Any]
    noshow_model_version: str | None
    config: dict[str, Any]
    supply_coverage: dict[str, Any]
    aggregate: dict[str, Any]
    comparisons: dict[str, Any]
    equity: dict[str, Any] = Field(
        description=(
            "Equidad por grupo (edad, previsión, comuna) por política: media, mínimo y máximo "
            "entre réplicas de cada métrica, y brecha máxima entre grupos. Se informa tal cual."
        )
    )
    limitations: list[str]


# ------------------------------------------------------------------ GES del plan


class GesItemOut(BaseModel):
    """Estado de una garantía GES en el plan."""

    entry_id: str
    obligation: str
    ges_deadline: date | None
    met: bool
    on_time: bool | None
    scheduled_date: date | None
    days_late: int | None
    first_possible_date: date | None
    cause: str | None
    text: str


class GesCauseCount(BaseModel):
    """Conteo de GES no cumplidas por causa."""

    cause: str
    count: int


class GesPageOut(DisclaimerModel):
    """Página de garantías GES del plan."""

    plan_id: uuid.UUID
    total: int
    limit: int
    offset: int
    items: list[GesItemOut]
    by_cause: list[GesCauseCount] = Field(description="Conteo de no cumplidas por causa.")


# ------------------------------------------------------------------ calendario


class CalendarItemOut(BaseModel):
    """Carga de un recurso en un día."""

    resource_id: str
    resource_label: str
    resource_kind: str
    health_service_code: int
    specialty_code: str | None
    date: date
    blocks: int = Field(description="Bloques (cupos CNE o bloques de pabellón) del día.")
    capacity: int = Field(description="Cupos CNE o minutos planificables de pabellón.")
    scheduled: int = Field(description="Citas programadas (sin sobrecupo).")
    overbooked: int = Field(description="Citas con sobrecupo.")


class CalendarPageOut(DisclaimerModel):
    """Página del calendario por recurso y día."""

    plan_id: uuid.UUID
    total: int
    limit: int
    offset: int
    items: list[CalendarItemOut]
