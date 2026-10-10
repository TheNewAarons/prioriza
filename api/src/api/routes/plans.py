"""Planes: consulta, revisión humana y vigencia."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from shared.db.enums import Policy, ReviewStatus
from shared.disclaimer import DISCLAIMER

from api import export
from api.auth import Role, User, current_user, require_roles
from api.catalog import CatalogUnavailable
from api.compare import compare_equity, compare_metrics
from api.deps import CatalogDep, Limit, Offset, ServicesDep, check_note, errors, to_http
from api.plans import PlanError, PlanRecord
from api.schemas import (
    ActivateIn,
    AssignmentOut,
    AssignmentPageOut,
    BlockLoadOut,
    CalendarPageOut,
    CompareSideOut,
    EntryReasonOut,
    EntryScoreOut,
    ExplanationPageOut,
    GesCauseCount,
    GesItemOut,
    GesPageOut,
    PlanCompareOut,
    PlanDetailOut,
    PlanPageOut,
    PlanSummaryOut,
    ReviewIn,
    ReviewListOut,
    ReviewRecordOut,
)

router = APIRouter(prefix="/v1", tags=["planes"], dependencies=[Depends(current_user)])

EXPORT_PAGE = 5_000
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


def _side(rec: PlanRecord) -> CompareSideOut:
    return CompareSideOut(
        plan_id=rec.id,
        policy=Policy(rec.policy),
        review_status=rec.review_status,
        is_current=rec.is_current,
        created_at=rec.created_at,
        requested_by=rec.requested_by,
        solver_status=rec.solver_status,
    )


@router.get(
    "/plans/compare",
    response_model=PlanCompareOut,
    summary="Comparar dos planes de la misma corrida",
    responses=errors(
        401, 404, 422, e422="los planes son de corridas distintas; no se pueden comparar"
    ),
)
def compare_plans(
    a: Annotated[uuid.UUID, Query(description="Id del primer plan.")],
    b: Annotated[uuid.UUID, Query(description="Id del segundo plan.")],
    svc: ServicesDep,
) -> PlanCompareOut:
    """Métricas, GES, sobrecupo, equidad por grupo y estados de revisión; diferencias `b - a`.

    Solo entre planes de la misma corrida sintética (422 si no). Muestra tal cual los resultados
    desfavorables: `better` indica qué plan gana en cada métrica, o `tie` / `none`.
    """
    if a == b:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="elige dos planes distintos"
        )
    try:
        rec_a, rec_b = svc.store.get(a), svc.store.get(b)
    except PlanError as exc:
        raise to_http(exc) from exc
    if rec_a.run_id != rec_b.run_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="los planes son de corridas distintas; no se pueden comparar",
        )
    return PlanCompareOut(
        run_id=rec_a.run_id,
        a=_side(rec_a),
        b=_side(rec_b),
        metrics=compare_metrics(rec_a, rec_b),
        equity=compare_equity(rec_a, rec_b),
    )


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
    "/plans/{plan_id}/export",
    summary="Exportar las asignaciones del plan a CSV",
    responses={
        200: {
            "description": (
                "CSV UTF-8 con coma. Las líneas que empiezan con `#` son el aviso y el estado "
                "de revisión: el lector debe saltarlas. Sin datos personales."
            ),
            "content": {
                "text/csv": {"example": f"# aviso: {DISCLAIMER}\nEntrada,Paciente sintético,..."}
            },
        },
        **errors(401, 404, 422, e404=_E404),
    },
)
def export_plan(
    plan_id: uuid.UUID,
    svc: ServicesDep,
    export_format: Annotated[
        Literal["csv"], Query(alias="format", description="Solo `csv` por ahora.")
    ] = "csv",
    limit: Annotated[
        int | None,
        Query(ge=1, description="Filas a exportar; por defecto y como máximo `max_export_rows`."),
    ] = None,
    offset: Offset = 0,
) -> Response:
    """Citas propuestas en CSV, para quien revisa el plan fuera del panel.

    Tope de filas: `PRIORIZA_API_MAX_EXPORT_ROWS` (50.000 por defecto). Si el plan tiene más,
    el archivo lo avisa en una línea `# truncado` y `offset` permite seguir. Un `limit` mayor al
    tope es 422. Las cabeceras `X-Total-Rows` y `X-Exported-Rows` traen los conteos.
    """
    cap = svc.settings.max_export_rows
    if limit is not None and limit > cap:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"limit no puede superar {cap}",
        )
    want = limit or cap
    try:
        rec = svc.store.get(plan_id)
        rows: list[dict[str, Any]] = []
        total = 0
        while len(rows) < want:
            page = svc.store.assignments(
                plan_id, limit=min(EXPORT_PAGE, want - len(rows)), offset=offset + len(rows)
            )
            total = page.total
            rows.extend(page.items)
            if not page.items:
                break
        if not rows:
            total = svc.store.assignments(plan_id, limit=1, offset=0).total
    except PlanError as exc:
        raise to_http(exc) from exc
    body = export.render_csv(
        rows,
        plan_id=str(plan_id),
        review_status=rec.review_status.value,
        total=total,
        offset=offset,
    )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="plan-{str(plan_id)[:8]}.csv"',
            "X-Total-Rows": str(total),
            "X-Exported-Rows": str(len(rows)),
        },
    )


@router.get(
    "/plans/{plan_id}/entries/{entry_id}/reason",
    response_model=EntryReasonOut,
    summary="Por qué esta entrada tiene (o no) su cupo",
    responses=errors(401, 404, e404="el plan no tiene explicación para la entrada"),
)
def entry_reason(plan_id: uuid.UUID, entry_id: str, svc: ServicesDep) -> EntryReasonOut:
    """Une la explicación del plan, la cita, la garantía GES, la carga del bloque y el puntaje.

    No inventa datos: cada bloque sale de lo que el plan guardó o de la lista de espera. La fase
    se deduce del plan (`3b` si entró por sobreagendamiento).
    """
    try:
        rec = svc.store.get(plan_id)
        rows = svc.store.entry_reason(plan_id, entry_id)
    except PlanError as exc:
        raise to_http(exc) from exc
    if rows.explanation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="el plan no tiene explicación para la entrada"
        )
    exp = rows.explanation
    assignment = AssignmentOut(**rows.assignment) if rows.assignment else None
    phase: str | None = None
    if assignment is not None:
        if rec.policy == "optimized":
            phase = "3b" if exp.get("detail") == "added_by_overbooking" else "3a"
        else:
            phase = rec.policy
    block_load = None
    if assignment is not None:
        for blk in (rec.report.get("overbooking") or {}).get("blocks", []):
            if blk.get("slot_id") == assignment.slot_id:
                block_load = BlockLoadOut(
                    capacity=blk["capacity"],
                    scheduled=blk["scheduled"],
                    overbooked=blk["overbooked"],
                    risk_exact=blk["risk_exact"],
                )
                break
    score = None
    try:
        found = svc.catalogs.get().entry_score(entry_id)
    except CatalogUnavailable:
        found = None
    if found is not None:
        score = EntryScoreOut(**found)
    return EntryReasonOut(
        plan_id=plan_id,
        entry_id=entry_id,
        policy=Policy(rec.policy),
        status=exp["status"],
        detail=exp.get("detail"),
        text=exp["text"],
        phase=phase,
        assignment=assignment,
        block_load=block_load,
        ges=GesItemOut(**rows.ges) if rows.ges else None,
        score=score,
    )


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
        422,
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
    check_note(svc.settings, body.note)
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
        422,
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
    check_note(svc.settings, note)
    try:
        return summary_out(svc.store.activate(plan_id, user, note))
    except PlanError as exc:
        raise to_http(exc) from exc
