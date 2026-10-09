"""Salud y usuario actual."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import User, current_user
from api.deps import errors
from api.schemas import MeOut

router = APIRouter()


class HealthOut(BaseModel):
    """Estado del servicio."""

    status: str


@router.get("/healthz", response_model=HealthOut, tags=["sistema"], summary="Sonda de salud")
def healthz() -> HealthOut:
    """Sonda de salud para Docker y orquestadores (sin clave)."""
    return HealthOut(status="ok")


@router.get(
    "/v1/me",
    response_model=MeOut,
    tags=["sistema"],
    summary="Usuario y rol de la clave",
    responses=errors(401),
)
def me(user: Annotated[User, Depends(current_user)]) -> MeOut:
    """Devuelve el usuario y el rol asociados a la clave."""
    return MeOut(user=user.name, role=user.role.value)
