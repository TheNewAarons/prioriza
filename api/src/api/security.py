"""Controles de seguridad de la API como middlewares ASGI puros.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

- `SecurityHeadersMiddleware`: cabeceras defensivas en toda respuesta (también 413, 422, 429).
- `RateLimitMiddleware`: ventana deslizante en memoria por usuario autenticado (o por IP si la
  clave falta o es inválida, para que rotar claves falsas no evada el límite). `/healthz` exento.
- `RequestLimitsMiddleware`: tope del cuerpo (413) y del largo de ids y parámetros (422), antes
  de que FastAPI lea o valide nada.

Los límites viven en `ApiSettings`. El limitador es por proceso: con varias réplicas el tope
efectivo se multiplica (ver `docs/security.md`).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import deque
from collections.abc import Callable, MutableMapping
from urllib.parse import parse_qsl

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.auth import API_KEY_HEADER, UserDirectory
from api.settings import ApiSettings

RATE_WINDOW_S = 60.0
# Tope de cubos del limitador; al superarlo se descartan los inactivos (memoria acotada).
MAX_RATE_BUCKETS = 10_000
EXEMPT_PATHS = frozenset({"/healthz"})
DOCS_PATHS = ("/docs", "/redoc")

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI y ReDoc cargan scripts y estilos desde un CDN (jsdelivr) y usan código en línea.
DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


async def _send_json(
    send: Send, status: int, detail: str, headers: dict[str, str] | None = None
) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    raw = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Añade cabeceras defensivas; `Cache-Control: no-store` salvo que la ruta ya lo defina."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        csp = DOCS_CSP if path.startswith(DOCS_PATHS) else API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Content-Security-Policy"] = csp
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """Máximo `rate_limit_per_minute` peticiones por usuario en una ventana deslizante."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: ApiSettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.limit = settings.rate_limit_per_minute
        self.clock = clock
        self._hits: MutableMapping[str, deque[float]] = {}

    def _bucket(self, scope: Scope) -> str:
        headers = Headers(scope=scope)
        key = headers.get(API_KEY_HEADER)
        directory: UserDirectory | None = getattr(scope["app"].state, "users", None)
        if key and directory is not None:
            user = directory.authenticate(key)
            if user is not None:
                # Se hace un hash del nombre: el cubo no guarda ni la clave ni datos legibles.
                return "u:" + hashlib.sha256(user.name.encode()).hexdigest()[:16]
        client = scope.get("client")
        return "ip:" + (client[0] if client else "desconocido")

    def _prune(self, now: float) -> None:
        cutoff = now - RATE_WINDOW_S
        for name in [n for n, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[name]

    def check(self, bucket: str) -> int | None:
        """Registra la petición; devuelve los segundos de espera si se excede el límite."""
        now = self.clock()
        queue = self._hits.get(bucket)
        if queue is None:
            if len(self._hits) >= MAX_RATE_BUCKETS:
                self._prune(now)
            queue = self._hits[bucket] = deque()
        while queue and queue[0] <= now - RATE_WINDOW_S:
            queue.popleft()
        if len(queue) >= self.limit:
            return max(1, math.ceil(queue[0] + RATE_WINDOW_S - now))
        queue.append(now)
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        retry_after = self.check(self._bucket(scope))
        if retry_after is not None:
            await _send_json(
                send,
                429,
                "Demasiadas peticiones; reintenta más tarde.",
                {"Retry-After": str(retry_after)},
            )
            return
        await self.app(scope, receive, send)


class RequestLimitsMiddleware:
    """413 por cuerpo grande y 422 por ids o parámetros demasiado largos."""

    def __init__(self, app: ASGIApp, *, settings: ApiSettings) -> None:
        self.app = app
        self.max_body = settings.max_body_bytes
        self.max_id = settings.max_id_length

    def _too_long(self, scope: Scope) -> str | None:
        for segment in scope["path"].split("/"):
            if len(segment) > self.max_id:
                return f"un segmento de la ruta supera {self.max_id} caracteres"
        query = scope.get("query_string", b"").decode("latin-1")
        for name, value in parse_qsl(query, keep_blank_values=True):
            if len(name) > self.max_id or len(value) > self.max_id:
                return f"un parámetro de consulta supera {self.max_id} caracteres"
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        problem = self._too_long(scope)
        if problem is not None:
            await _send_json(send, 422, problem)
            return
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_body
            except ValueError:
                await _send_json(send, 400, "Content-Length inválido.")
                return
            if too_big:
                await self._reject(send)
                return

        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, started, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    # FastAPI convierte cualquier excepción al leer el cuerpo en un 400: se
                    # responde 413 desde aquí y se simula una desconexión para cortar la lectura.
                    rejected = True
                    if not started:
                        started = True
                        await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # la respuesta 413 ya se envió; se descarta lo que genere la app
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)

    async def _reject(self, send: Send) -> None:
        await _send_json(send, 413, f"El cuerpo supera el máximo de {self.max_body} bytes.")
