"""Servicios compartidos de la app y utilidades comunes de las rutas.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Request, status

from api.catalog import CatalogProvider, CatalogUnavailable, RunCatalog
from api.jobs import JobLimitExceeded, JobManager
from api.plans import InvalidTransition, NotFound, PermissionDenied, PlanError, PlanStore
from api.schemas import ErrorOut
from api.settings import ApiSettings


@dataclass(frozen=True)
class Services:
    """Dependencias de las rutas, guardadas en `app.state.services`."""

    settings: ApiSettings
    store: PlanStore
    jobs: JobManager
    catalogs: CatalogProvider


def services(request: Request) -> Services:
    """Servicios de la app."""
    svc: Services = request.app.state.services
    return svc


ServicesDep = Annotated[Services, Depends(services)]


def catalog(svc: ServicesDep) -> RunCatalog:
    """Corrida sintética cargada; 503 si no se puede ubicar o leer."""
    try:
        return svc.catalogs.get()
    except CatalogUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


CatalogDep = Annotated[RunCatalog, Depends(catalog)]

Limit = Annotated[int, Query(ge=1, le=500, description="Elementos por página (1-500).")]
Offset = Annotated[int, Query(ge=0, description="Elementos que se saltan.")]


def check_schedule_limits(settings: ApiSettings, horizon_weeks: int, time_limit_s: float) -> None:
    """422 si la programación pedida supera los topes configurados."""
    if horizon_weeks > settings.max_horizon_weeks:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"horizon_weeks no puede superar {settings.max_horizon_weeks}",
        )
    if time_limit_s > settings.max_time_limit_s:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"time_limit_s no puede superar {settings.max_time_limit_s:g}",
        )


def check_note(settings: ApiSettings, note: str | None) -> None:
    """422 si la nota de revisión supera `max_note_length`."""
    if note is not None and len(note) > settings.max_note_length:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"la nota no puede superar {settings.max_note_length} caracteres",
        )


def to_http(exc: PlanError) -> HTTPException:
    """Traduce un error de dominio a 404, 403 o 409."""
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionDenied):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, InvalidTransition):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, JobLimitExceeded):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


_DESCRIPTIONS = {
    401: ("Falta la clave X-API-Key o no es válida.", "Falta la clave X-API-Key o no es válida."),
    403: ("El rol o el usuario no puede hacer la acción.", "El rol 'lectura' no puede hacer esto."),
    404: ("El recurso no existe.", "no existe el plan 00000000-0000-0000-0000-000000000000"),
    409: (
        "La acción no corresponde al estado actual.",
        "el plan ya está 'approved'; la decisión de revisión es final",
    ),
    422: ("Un parámetro supera los límites configurados.", "horizon_weeks no puede superar 12"),
    429: (
        "Demasiadas programaciones pendientes o en curso.",
        "ya tienes 2 programaciones pendientes o en curso; espera a que terminen",
    ),
    503: ("La corrida sintética no está disponible.", "la corrida sintética no está disponible"),
}


def errors(*codes: int, **examples: str) -> dict[int | str, dict[str, Any]]:
    """Documenta respuestas de error en OpenAPI; `e403="texto"` cambia el ejemplo del 403."""
    out: dict[int | str, dict[str, Any]] = {}
    for code in codes:
        description, example = _DESCRIPTIONS[code]
        out[code] = {
            "model": ErrorOut,
            "description": description,
            "content": {
                "application/json": {"example": {"detail": examples.get(f"e{code}", example)}}
            },
        }
    return out
