"""Roles, usuarios y autenticación por clave en la cabecera `X-API-Key`.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Los usuarios salen de un archivo JSON fuera del repositorio; el código no trae claves.
La comparación usa `hmac.compare_digest` contra todas las claves, sin cortar en la primera.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = "X-API-Key"
MAX_USER_NAME = 64  # largo de `plan_review.user_name` y `schedule_run.requested_by`
MIN_KEY_LENGTH = 32
EXAMPLE_KEY_PREFIX = "EJEMPLO"


class Role(StrEnum):
    """Rol del usuario; fija qué acciones puede hacer."""

    GESTOR = "gestor"
    REVISOR = "revisor"
    LECTURA = "lectura"


@dataclass(frozen=True, slots=True)
class User:
    """Usuario autenticado."""

    name: str
    role: Role


class UserDirectory:
    """Usuarios por clave. No expone las claves."""

    def __init__(self, users: dict[str, User] | None = None) -> None:
        self._users: dict[str, User] = dict(users or {})

    def __len__(self) -> int:
        return len(self._users)

    def keys_for_redaction(self) -> list[str]:
        """Claves conocidas, solo para registrarlas en el redactor de logs (nunca se imprimen)."""
        return list(self._users)

    @classmethod
    def from_file(cls, path: Path) -> UserDirectory:
        """Lee `{api_key: {"user": nombre, "role": rol}}`; falla si el formato es inválido.

        Rechaza claves de ejemplo (prefijo `EJEMPLO`) o de menos de 32 caracteres, y nombres
        vacíos, no textuales o de más de 64 caracteres (el largo de las columnas de auditoría).
        """
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: se esperaba un objeto JSON {{clave: {{user, role}}}}")
        users: dict[str, User] = {}
        for key, entry in raw.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise ValueError(f"{path}: entrada inválida")
            if key.upper().startswith(EXAMPLE_KEY_PREFIX) or len(key) < MIN_KEY_LENGTH:
                raise ValueError(
                    f"{path}: hay una clave de ejemplo o de menos de {MIN_KEY_LENGTH} caracteres; "
                    "genera claves propias (p. ej. `python -c 'import secrets; "
                    "print(secrets.token_urlsafe(32))'`)"
                )
            name = entry.get("user")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_USER_NAME:
                raise ValueError(f"{path}: nombre de usuario vacío o de más de {MAX_USER_NAME}")
            try:
                users[key] = User(name=name.strip(), role=Role(str(entry.get("role"))))
            except ValueError as exc:
                raise ValueError(f"{path}: rol inválido ({exc})") from exc
        return cls(users)

    def authenticate(self, api_key: str) -> User | None:
        """Devuelve el usuario de la clave o `None`; recorre todas las claves."""
        found: User | None = None
        candidate = api_key.encode("utf-8")
        for key, user in self._users.items():
            if hmac.compare_digest(candidate, key.encode("utf-8")):
                found = user
        return found


_api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="Clave de API del usuario (ver `api/users.example.json`).",
)


def current_user(
    request: Request, api_key: Annotated[str | None, Depends(_api_key_header)]
) -> User:
    """401 si falta la clave o es desconocida."""
    directory: UserDirectory = request.app.state.users
    user = directory.authenticate(api_key) if api_key else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Falta la clave X-API-Key o no es válida.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    """Dependencia que exige uno de `roles` (403 en otro caso)."""
    allowed: Collection[Role] = frozenset(roles)

    def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            names = ", ".join(sorted(r.value for r in allowed))
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"El rol '{user.role.value}' no puede hacer esto; se requiere: {names}.",
            )
        return user

    return dependency
