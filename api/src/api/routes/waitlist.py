"""Lista de espera y pacientes sintéticos."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from shared.db.enums import ClinicalPriority
from shared.schemas import CareType

from api.auth import current_user
from api.deps import CatalogDep, Limit, Offset, errors
from api.schemas import (
    PatientOut,
    StrictTierName,
    WaitlistOrder,
    WaitlistPageOut,
    WaitlistSummaryOut,
)

router = APIRouter(prefix="/v1", dependencies=[Depends(current_user)])


@router.get(
    "/waitlist",
    response_model=WaitlistPageOut,
    tags=["lista de espera"],
    summary="Lista de espera con puntaje y puesto",
    responses=errors(401, 503),
)
def waitlist(
    cat: CatalogDep,
    limit: Limit = 50,
    offset: Offset = 0,
    health_service_code: Annotated[int | None, Query()] = None,
    specialty_code: Annotated[str | None, Query()] = None,
    care_type: Annotated[CareType | None, Query()] = None,
    clinical_priority: Annotated[ClinicalPriority | None, Query()] = None,
    is_ges: Annotated[bool | None, Query()] = None,
    tier: Annotated[StrictTierName | None, Query()] = None,
    order_by: Annotated[WaitlistOrder, Query()] = WaitlistOrder.RANK,
) -> WaitlistPageOut:
    """Entradas en espera de la corrida sintética, con su puntaje de priorización.

    La prioridad clínica es un dato de entrada: el sistema no la infiere ni la cambia.
    """
    filters: dict[str, Any] = {
        "health_service_code": health_service_code,
        "specialty_code": specialty_code,
        "care_type": care_type.value if care_type else None,
        "clinical_priority": clinical_priority.value if clinical_priority else None,
        "is_ges": is_ges,
        "tier": tier.value if tier else None,
    }
    total, items = cat.waitlist_page(
        filters=filters, order_by=order_by.value, limit=limit, offset=offset
    )
    return WaitlistPageOut(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/waitlist/summary",
    response_model=WaitlistSummaryOut,
    tags=["lista de espera"],
    summary="Resumen agregado de la lista de espera",
    responses=errors(401, 503),
)
def waitlist_summary(
    cat: CatalogDep,
    health_service_code: Annotated[int | None, Query()] = None,
    specialty_code: Annotated[str | None, Query()] = None,
    care_type: Annotated[CareType | None, Query()] = None,
    clinical_priority: Annotated[ClinicalPriority | None, Query()] = None,
    is_ges: Annotated[bool | None, Query()] = None,
    tier: Annotated[StrictTierName | None, Query()] = None,
) -> WaitlistSummaryOut:
    """Total, mediana y p90 de espera, GES en riesgo y vencidas, y distribución de la espera.

    Mismos filtros que `/v1/waitlist`. Se calcula una vez por corrida y combinación de filtros.
    """
    filters: dict[str, Any] = {
        "health_service_code": health_service_code,
        "specialty_code": specialty_code,
        "care_type": care_type.value if care_type else None,
        "clinical_priority": clinical_priority.value if clinical_priority else None,
        "is_ges": is_ges,
        "tier": tier.value if tier else None,
    }
    return WaitlistSummaryOut(**cat.waitlist_summary(filters))


@router.get(
    "/patients/{patient_id}",
    response_model=PatientOut,
    tags=["lista de espera"],
    summary="Paciente sintético y explicación del puntaje de sus entradas",
    responses=errors(
        401, 404, 503, e404="no existe el paciente 00000000-0000-0000-0000-000000000000"
    ),
)
def patient(patient_id: str, cat: CatalogDep) -> PatientOut:
    """Atributos agregados del paciente sintético y sus entradas con la explicación del puntaje."""
    found = cat.patient(patient_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no existe el paciente {patient_id}")
    return PatientOut(**found)
