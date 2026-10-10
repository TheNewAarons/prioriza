"""Sesión de la persona: clave de API, usuario y rol.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La sesión vive solo en `dcc.Store(storage_type="session")` del navegador. La clave nunca se
registra en logs ni aparece en mensajes. Los botones que el rol no puede usar no se muestran.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dash.development.base_component import Component
from shared.logging import register_secret

from dashboard.api_client import ApiAuthError, ApiClient, ApiError
from dashboard.components.common import empty_state, error_panel

ROLES = ("gestor", "revisor", "lectura")


@dataclass(frozen=True)
class Session:
    """Clave validada con `GET /v1/me`, usuario y rol."""

    api_key: str
    user: str
    role: str

    def to_store(self) -> dict[str, str]:
        """Contenido del `dcc.Store` de sesión."""
        return {"api_key": self.api_key, "user": self.user, "role": self.role}

    def __repr__(self) -> str:
        # Nunca se imprime la clave (logs, trazas de pytest).
        return f"Session(user={self.user!r}, role={self.role!r})"


def from_store(data: Any) -> Session | None:
    """Reconstruye la sesión desde el store; `None` si falta o está incompleta."""
    if not isinstance(data, dict):
        return None
    key, user, role = data.get("api_key"), data.get("user"), data.get("role")
    if not (isinstance(key, str) and key and isinstance(user, str) and isinstance(role, str)):
        return None
    register_secret(key)
    return Session(key, user, role)


@dataclass(frozen=True)
class LoginResult:
    """Resultado de intentar entrar: sesión o mensaje de error junto al campo."""

    session: Session | None
    error: str | None


def attempt_login(client: ApiClient, api_key: str | None) -> LoginResult:
    """Valida la clave con `GET /v1/me`."""
    key = (api_key or "").strip()
    if not key:
        return LoginResult(None, "Escribe tu clave de API para entrar.")
    try:
        me = client.me(key)
    except ApiAuthError:
        return LoginResult(None, "La clave de API no es válida. Revísala y vuelve a intentar.")
    except ApiError as exc:
        return LoginResult(None, exc.message)
    role = str(me.get("role", ""))
    if role not in ROLES:
        return LoginResult(None, "La API devolvió un rol desconocido. Revisa su versión.")
    register_secret(key)
    return LoginResult(Session(key, str(me.get("user", "")), role), None)


@dataclass(frozen=True)
class Guarded[T]:
    """Resultado de una lectura con sesión: el valor o el mensaje listo para mostrar."""

    value: T | None
    error: Component | None


def call_guarded[T](session_data: Any, fn: Callable[[Session], T]) -> Guarded[T]:
    """Ejecuta `fn` con la sesión; los errores de la API quedan como componente de aviso."""
    session = from_store(session_data)
    if session is None:
        return Guarded(None, empty_state("Entra con tu clave de API para ver esta página."))
    try:
        return Guarded(fn(session), None)
    except ApiAuthError as exc:
        return Guarded(None, error_panel(f"{exc.message} Usa «Salir» y entra de nuevo."))
    except ApiError as exc:
        return Guarded(None, error_panel(exc.message))


def render_guarded(
    session_data: Any, build: Callable[[Session], Component | list[Component]]
) -> Component | list[Component]:
    """Como `call_guarded`, pero devuelve el componente o el aviso de error."""
    result = call_guarded(session_data, build)
    return result.error if result.error is not None else result.value  # type: ignore[return-value]
