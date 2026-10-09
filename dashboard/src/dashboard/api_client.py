"""Cliente HTTP de la API de Prioriza.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La clave de API viaja por petición en la cabecera `X-API-Key` y nunca se registra: el cliente no
la guarda, no la escribe en logs y la caché usa solo un resumen irreversible (SHA-256) como parte
de la llave. Los errores son tipados y sus mensajes dicen qué pasó y qué hacer.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

CACHE_TTL_S = 30.0


class ApiError(Exception):
    """Error de la API con un mensaje listo para mostrar a la persona."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class ApiUnavailable(ApiError):
    """La API no responde (conexión rechazada, tiempo agotado o respuesta ilegible)."""


class ApiAuthError(ApiError):
    """401: la clave falta o no es válida."""


class ApiForbidden(ApiError):
    """403: el rol o el usuario no puede hacer la acción."""


class ApiNotFound(ApiError):
    """404: el recurso no existe."""


class ApiConflict(ApiError):
    """409: la acción no corresponde al estado actual."""


def _detail(response: httpx.Response) -> str | None:
    """Texto de `detail` de un error de la API, si lo trae."""
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        return str(first.get("msg")) if isinstance(first, dict) else str(first)
    return None


def error_for(response: httpx.Response) -> ApiError:
    """Traduce una respuesta de error a la excepción tipada con su mensaje."""
    status = response.status_code
    detail = _detail(response)
    if status == 401:
        return ApiAuthError(
            "La clave de API no es válida o ya no está vigente. Entra de nuevo con otra clave.",
            status,
        )
    if status == 403:
        return ApiForbidden(detail or "Tu rol no puede hacer esta acción.", status)
    if status == 404:
        if detail in (None, "Not Found"):
            return ApiNotFound(
                "La API no tiene este recurso; puede ser una versión anterior. "
                "Reinicia la API con `make api`.",
                status,
            )
        return ApiNotFound(detail, status)
    if status == 409:
        return ApiConflict(detail or "La acción no corresponde al estado actual.", status)
    if status == 422:
        return ApiError(f"La petición no es válida: {detail or 'revisa los valores'}.", status)
    if status == 429:
        return ApiError(
            detail or "Hay demasiadas programaciones en curso. Espera a que terminen.", status
        )
    if status == 503:
        return ApiError(
            detail or "La corrida sintética no está disponible. Genera datos con `make synth`.",
            status,
        )
    return ApiError(f"La API respondió con un error ({status}). Revisa su registro.", status)


class ApiClient:
    """Cliente síncrono; seguro entre hilos. Cada método recibe la clave del usuario."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        cache_ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)
        self._ttl = cache_ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def close(self) -> None:
        """Cierra las conexiones."""
        self._http.close()

    # ------------------------------------------------------------------ núcleo

    @staticmethod
    def _cache_key(path: str, params: Mapping[str, Any] | None, api_key: str) -> str:
        digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"{digest}|{path}|{json.dumps(params or {}, sort_keys=True, default=str)}"

    def request(
        self,
        method: str,
        path: str,
        api_key: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        cached: bool = False,
    ) -> Any:
        """Hace la petición y devuelve el JSON; `cached` aplica solo a lecturas estables."""
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        key = self._cache_key(path, clean, api_key) if cached else ""
        if cached:
            with self._lock:
                hit = self._cache.get(key)
            if hit is not None and self._clock() - hit[0] < self._ttl:
                return hit[1]
        try:
            response = self._http.request(
                method,
                path,
                params=clean or None,
                json=dict(body) if body is not None else None,
                headers={"X-API-Key": api_key},
            )
        except httpx.HTTPError as exc:
            raise ApiUnavailable(
                f"La API no responde en {self.base_url}. Levántala con `make api`."
            ) from exc
        if response.status_code >= 400:
            raise error_for(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiUnavailable(
                f"La respuesta de la API en {self.base_url} no es válida. Revisa su registro."
            ) from exc
        if cached:
            with self._lock:
                self._cache[key] = (self._clock(), data)
        return data

    def clear_cache(self) -> None:
        """Descarta la caché (p. ej. al salir)."""
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------ sistema

    def me(self, api_key: str) -> dict[str, Any]:
        """Usuario y rol de la clave (`GET /v1/me`)."""
        return dict(self.request("GET", "/v1/me", api_key))

    # ------------------------------------------------------------------ lista de espera

    def waitlist(self, api_key: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Una página de la lista de espera; nunca se baja la lista completa."""
        return dict(self.request("GET", "/v1/waitlist", api_key, params=params))

    def waitlist_summary(
        self, api_key: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Resumen agregado (con caché corta)."""
        return dict(
            self.request("GET", "/v1/waitlist/summary", api_key, params=params, cached=True)
        )

    def patient(self, api_key: str, patient_id: str) -> dict[str, Any]:
        """Paciente sintético con sus entradas y la explicación del puntaje."""
        return dict(self.request("GET", f"/v1/patients/{patient_id}", api_key))

    # ------------------------------------------------------------------ programación

    def create_schedule_run(self, api_key: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Pide una programación (gestor)."""
        return dict(self.request("POST", "/v1/schedule-runs", api_key, body=body))

    def schedule_run(self, api_key: str, job_id: str) -> dict[str, Any]:
        """Estado de un trabajo."""
        return dict(self.request("GET", f"/v1/schedule-runs/{job_id}", api_key))

    def plans(self, api_key: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Planes del más reciente al más antiguo."""
        return dict(self.request("GET", "/v1/plans", api_key, params=params))

    def current_plan(self, api_key: str) -> dict[str, Any]:
        """Plan vigente (404 si no hay)."""
        return dict(self.request("GET", "/v1/plans/current", api_key))

    def plan(self, api_key: str, plan_id: str) -> dict[str, Any]:
        """Detalle de un plan."""
        return dict(self.request("GET", f"/v1/plans/{plan_id}", api_key))

    def plan_ges(
        self, api_key: str, plan_id: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Garantías GES del plan."""
        return dict(self.request("GET", f"/v1/plans/{plan_id}/ges", api_key, params=params))

    def plan_calendar(
        self, api_key: str, plan_id: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Carga del plan por recurso y día."""
        return dict(self.request("GET", f"/v1/plans/{plan_id}/calendar", api_key, params=params))

    def plan_explanations(
        self, api_key: str, plan_id: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Explicaciones por entrada."""
        return dict(
            self.request("GET", f"/v1/plans/{plan_id}/explanations", api_key, params=params)
        )

    def plan_reviews(self, api_key: str, plan_id: str) -> dict[str, Any]:
        """Auditoría del plan."""
        return dict(self.request("GET", f"/v1/plans/{plan_id}/reviews", api_key))

    def review_plan(
        self, api_key: str, plan_id: str, decision: str, note: str | None
    ) -> dict[str, Any]:
        """Aprueba o rechaza un plan pendiente (revisor)."""
        body = {"decision": decision, "note": note}
        return dict(self.request("POST", f"/v1/plans/{plan_id}/review", api_key, body=body))

    def activate_plan(self, api_key: str, plan_id: str, note: str | None) -> dict[str, Any]:
        """Marca vigente un plan aprobado (gestor)."""
        body = {"note": note}
        return dict(self.request("POST", f"/v1/plans/{plan_id}/activate", api_key, body=body))

    # ------------------------------------------------------------------ simulación

    def simulation(self, api_key: str) -> dict[str, Any]:
        """Resultados de `make simulate` (con caché corta)."""
        return dict(self.request("GET", "/v1/simulation", api_key, cached=True))
