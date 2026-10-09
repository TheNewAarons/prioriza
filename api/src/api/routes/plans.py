"""Planes: consulta, revisión humana y vigencia."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from shared.db.enums import Policy, ReviewStatus

from api.auth import Role, User, current_user, require_roles
from api.deps import CatalogDep, Limit, Offset, ServicesDep, errors, to_http
from api.plans import PlanError, PlanRecord
from api.schemas import (
    ActivateIn,
    AssignmentPageOut,
    CalendarPageOut,
    ExplanationPageOut,
    GesCauseCount,
    GesPageOut,
    PlanDetailOut,
    PlanPageOut,
    PlanSummaryOut,
    ReviewIn,
    ReviewListOut,
    ReviewRecordOut,
)

router = APIRouter(prefix="/v1", tags=["planes"], dependencies=[Depends(current_user)])

_E404 = "no existe el plan 00000000-0000-0000-0000-000000000000"


def _summary_fields(rec: PlanRecord) -> dict[str, Any]:
    return {
        "plan_id": rec.id,
        "run_id": rec.run_id,
        "policy": Policy(rec.policy),
        "review_status": rec.review_status,
        "is_current": rec.is_current,
        "requested_by": rec.requested_by,
        "created_at": rec.created_at,
        "solver_status": rec.solver_status,
        "objective_value": rec.objective_value,
        "horizon_start": rec.horizon_start,
        "horizon_end": rec.horizon_end,
    }


def summary_out(rec: PlanRecord) -> PlanSummaryOut:
    """Plan sin el detalle del informe."""
    return PlanSummaryOut(**_summary_fields(rec))


def detail_out(rec: PlanRecord) -> PlanDetailOut:
    """Plan con el resumen del informe, incluida la equidad tal cual salió."""
    return PlanDetailOut(
        **_summary_fields(rec),
        summary=rec.report.get("summary", {}),
        ges=rec.report.get("ges", {}),
        equity=rec.report.get("equity", []),
        warnings=rec.report.get("warnings", []),
        config=rec.config,
    )


@router.get(
    "/plans",
    response_model=PlanPageOut,
    summary="Listar planes",
    responses=errors(401),
)
def list_plans(
    svc: ServicesDep,
    limit: Limit = 50,
    offset: Offset = 0,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    current: Annotated[
        bool | None, Query(description="Solo vigentes (true) o no vigentes.")
    ] = None,
) -> PlanPageOut:
    """Planes del más reciente al más antiguo."""
    page = svc.store.list_plans(
        review_status=review_status, current=current, limit=limit, offset=offset
    )
    return PlanPageOut(
        total=page.total,
        limit=limit,
        offset=offset,
        items=[summary_out(r) for r in page.items],
    )


@router.get(
    "/plans/current",
    response_model=PlanDetailOut,
    summary="Plan vigente de la corrida",
    responses=errors(401, 404, 503, e404="no hay un plan vigente"),
)
def current_plan(svc: ServicesDep) -> PlanDetailOut:
    """Plan vigente de la corrida sintética configurada.

    Si la corrida no se puede ubicar responde 503: nunca devuelve el vigente de otra corrida.
    """
    run_id = svc.catalogs.run_id()
    if run_id is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="la corrida sintética configurada no está disponible",
        )
    rec = svc.store.current(run_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no hay un plan vigente")
    return detail_out(rec)


@router.get(
    "/plans/{plan_id}",
    response_model=PlanDetailOut,
    summary="Detalle de un plan",
    responses=errors(401, 404, e404=_E404),
)
def get_plan(plan_id: uuid.UUID, svc: ServicesDep) -> PlanDetailOut:
    """Resumen del informe, estado de revisión, vigencia y solicitante."""
    try:
        return detail_out(svc.store.get(plan_id))
    except PlanError as exc:
        raise to_http(exc) from exc


@router.get(
    "/plans/{plan_id}/assignments",
    response_model=AssignmentPageOut,
    summary="Citas propuestas por el plan",
    responses=errors(401, 404, e404=_E404),
)
def plan_assignments(
    plan_id: uuid.UUID, svc: ServicesDep, limit: Limit = 50, offset: Offset = 0
) -> AssignmentPageOut:
    """Asignaciones por fecha de inicio."""
    try:
        page = svc.store.assignments(plan_id, limit=limit, offset=offset)
    except PlanError as exc:
        raise to_http(exc) from exc
    return AssignmentPageOut(total=page.total, limit=limit, offset=offset, items=page.items)


@router.get(
    "/plans/{plan_id}/explanations",
    response_model=ExplanationPageOut,
    summary="Por qué cada entrada quedó o no en el plan",
    responses=errors(401, 404, e404=_E404),
)
def plan_explanations(
    plan_id: uuid.UUID,
    svc: ServicesDep,
    limit: Limit = 50,
    offset: Offset = 0,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="p. ej. scheduled, capacity_taken, no_compatible_block."),
    ] = None,
) -> ExplanationPageOut:
    """Explicaciones por entrada, filtrables por estado."""
    try:
        page = svc.store.explanations(plan_id, status=status_filter, limit=limit, offset=offset)
    except PlanError as exc:
        raise to_http(exc) from exc
    return ExplanationPageOut(total=page.total, limit=limit, offset=offset, items=page.items)


@router.get(
    "/plans/{plan_id}/ges",
    response_model=GesPageOut,
    summary="Garantías GES del plan",
    responses=errors(401, 404, e404=_E404),
)
def plan_ges(
    plan_id: uuid.UUID,
    svc: ServicesDep,
    limit: Limit = 50,
    offset: Offset = 0,
    met: Annotated[bool | None, Query(description="Cumplidas (true) o no cumplidas.")] = None,
    cause: Annotated[str | None, Query(description="Causa de incumplimiento.")] = None,
) -> GesPageOut:
    """Estado de cada garantía GES con su causa; `by_cause` cuenta todas las no cumplidas."""
    try:
        page = svc.store.ges(plan_id, met=met, cause=cause, limit=limit, offset=offset)
        causes = svc.store.ges_causes(plan_id)
    except PlanError as exc:
        raise to_http(exc) from exc
    return GesPageOut(
        plan_id=plan_id,
        total=page.total,
        limit=limit,
        offset=offset,
        items=page.items,
        by_cause=[GesCauseCount(cause=c, count=n) for c, n in causes.items()],
    )


@router.get(
    "/plans/{plan_id}/calendar",
    response_model=CalendarPageOut,
    summary="Carga del plan por recurso y día",
    responses=errors(401, 404, 503, e404=_E404),
)
def plan_calendar(
    plan_id: uuid.UUID,
    svc: ServicesDep,
    cat: CatalogDep,
    limit: Limit = 500,
    offset: Offset = 0,
    resource_kind: Annotated[Literal["specialist_agenda", "operating_room"] | None, Query()] = None,
    health_service_code: Annotated[int | None, Query()] = None,
) -> CalendarPageOut:
    """Por recurso y día local del horizonte: bloques, capacidad, citas y sobrecupos.

    Capacidad: cupos CNE (duración / unidad) en agendas y minutos planificables en pabellones.
    """
    if cat.slots.is_empty() or cat.resources.is_empty():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="la corrida sintética no tiene cupos ni recursos para armar el calendario",
        )
    try:
        record = svc.store.get(plan_id)
        counts = svc.store.slot_counts(plan_id)
    except PlanError as exc:
        raise to_http(exc) from exc
    frame = cat.calendar(
        counts,
        horizon_start=record.horizon_start,
        horizon_end=record.horizon_end,
        resource_kind=resource_kind,
        health_service_code=health_service_code,
    )
    page = frame.slice(offset, limit)
    return CalendarPageOut(
        plan_id=plan_id, total=frame.height, limit=limit, offset=offset, items=page.to_dicts()
    )


@router.get(
    "/plans/{plan_id}/reviews",
    response_model=ReviewListOut,
    summary="Auditoría de revisión y vigencia",
    responses=errors(401, 404, e404=_E404),
)
def plan_reviews(plan_id: uuid.UUID, svc: ServicesDep) -> ReviewListOut:
    """Cada aprobación, rechazo y cambio de vigencia con usuario, rol, hora y nota."""
    try:
        records = svc.store.reviews(plan_id)
    except PlanError as exc:
        raise to_http(exc) from exc
    return ReviewListOut(
        plan_id=plan_id,
        items=[
            ReviewRecordOut(
                id=r.id,
                action=r.action,
                user_name=r.user_name,
                role=r.role,
                note=r.note,
                created_at=r.created_at,
            )
            for r in records
        ],
    )


@router.post(
    "/plans/{plan_id}/review",
    response_model=PlanSummaryOut,
    summary="Aprobar o rechazar un plan pendiente (revisor)",
    responses=errors(
        401,
        403,
        404,
        409,
        e403="el revisor no puede revisar un plan que pidió él mismo (regla de cuatro ojos)",
        e404=_E404,
    ),
)
def review_plan(
    plan_id: uuid.UUID,
    body: ReviewIn,
    svc: ServicesDep,
    user: Annotated[User, Depends(require_roles(Role.REVISOR))],
) -> PlanSummaryOut:
    """Decisión final de una persona con rol `revisor`; no puede revisar su propio pedido."""
    try:
        return summary_out(svc.store.review(plan_id, user, body.decision, body.note))
    except PlanError as exc:
        raise to_http(exc) from exc


@router.post(
    "/plans/{plan_id}/activate",
    response_model=PlanSummaryOut,
    summary="Marcar vigente un plan aprobado (gestor)",
    responses=errors(
        401,
        403,
        404,
        409,
        e403="El rol 'revisor' no puede hacer esto; se requiere: gestor.",
        e404=_E404,
        e409="solo un plan 'approved' puede ser vigente; este está 'pending'",
    ),
)
def activate_plan(
    plan_id: uuid.UUID,
    svc: ServicesDep,
    user: Annotated[User, Depends(require_roles(Role.GESTOR))],
    body: ActivateIn | None = None,
) -> PlanSummaryOut:
    """Deja vigente un plan aprobado; el vigente anterior de la corrida queda desactivado."""
    note = body.note if body else None
    try:
        return summary_out(svc.store.activate(plan_id, user, note))
    except PlanError as exc:
        raise to_http(exc) from exc
