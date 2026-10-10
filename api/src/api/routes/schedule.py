"""Programaciones asíncronas: pedir un plan y consultar el trabajo."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from api.auth import Role, User, current_user, require_roles
from api.deps import ServicesDep, check_schedule_limits, errors, to_http
from api.jobs import JobRecord
from api.plans import PlanError
from api.schemas import JobOut, ScheduleRequestIn

router = APIRouter(prefix="/v1", tags=["programación"], dependencies=[Depends(current_user)])


def _job_out(job: JobRecord) -> JobOut:
    return JobOut(**vars(job))


@router.post(
    "/schedule-runs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir una programación (gestor)",
    responses=errors(
        401, 403, 422, 429, e403="El rol 'lectura' no puede hacer esto; se requiere: gestor."
    ),
)
def create_schedule_run(
    body: ScheduleRequestIn,
    response: Response,
    svc: ServicesDep,
    user: Annotated[User, Depends(require_roles(Role.GESTOR))],
) -> JobOut:
    """Encola la programación y responde 202 con la ubicación del trabajo.

    El plan resultante queda `pending`: requiere la aprobación de un revisor antes de usarse.
    """
    check_schedule_limits(svc.settings, body.horizon_weeks, body.time_limit_s)
    try:
        job = svc.jobs.submit(body, user)
    except PlanError as exc:
        raise to_http(exc) from exc
    response.headers["Location"] = f"/v1/schedule-runs/{job.job_id}"
    return _job_out(job)


@router.get(
    "/schedule-runs/{job_id}",
    response_model=JobOut,
    summary="Estado de un trabajo de programación",
    responses=errors(401, 404, e404="no existe el trabajo 00000000-0000-0000-0000-000000000000"),
)
def get_schedule_run(job_id: uuid.UUID, svc: ServicesDep) -> JobOut:
    """`queued`, `running`, `succeeded` (con `plan_id`) o `failed` (con `error`)."""
    try:
        return _job_out(svc.jobs.get(job_id))
    except PlanError as exc:
        raise to_http(exc) from exc
