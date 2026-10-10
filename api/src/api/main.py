"""Aplicación FastAPI de Prioriza.

Se levanta como fábrica (`uvicorn --factory api.main:create_app`): importar el módulo no lee
el entorno ni el archivo de usuarios.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import logging
import stat
from collections.abc import AsyncIterator
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from shared.disclaimer import DISCLAIMER
from shared.logging import install_redaction, register_secret
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.auth import UserDirectory
from api.catalog import CatalogProvider
from api.deps import Services
from api.jobs import JobManager
from api.plans import MemoryPlanStore, PlanStore
from api.routes import plans, schedule, simulation, system, waitlist
from api.security import RateLimitMiddleware, RequestLimitsMiddleware, SecurityHeadersMiddleware
from api.settings import ApiSettings

log = logging.getLogger("api")

DESCRIPTION = f"""**{DISCLAIMER}**

El sistema apoya, no decide: la prioridad clínica es un dato de entrada, todo plan nace
`pending` y requiere la aprobación de un `revisor` antes de poder ser vigente.
Autenticación con la cabecera `X-API-Key`; roles `gestor`, `revisor` y `lectura`.
"""


class InsecureConfiguration(RuntimeError):
    """La configuración no es aceptable para el entorno (p. ej. producción sin usuarios)."""


def check_users_file(settings: ApiSettings) -> None:
    """Valida el archivo de usuarios según el entorno.

    Producción: debe estar definido, existir y no ser legible por grupo ni otros (permisos 600
    o más estrictos); si no, `InsecureConfiguration`. Desarrollo: solo advierte.
    """
    production = settings.environment == "production"
    path = settings.users_file
    if path is None:
        if production:
            raise InsecureConfiguration(
                "en producción PRIORIZA_API_USERS_FILE es obligatorio (sin usuarios no hay acceso)"
            )
        return
    if not path.is_file():
        if production:
            raise InsecureConfiguration("el archivo de usuarios configurado no existe")
        return  # en desarrollo `UserDirectory.from_file` informa el error al leerlo
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        message = (
            "el archivo de usuarios es accesible por grupo u otros; usa permisos 600 (`chmod 600`)"
        )
        if production:
            raise InsecureConfiguration(message)
        log.warning(message)


def create_app(
    settings: ApiSettings | None = None,
    *,
    store: PlanStore | None = None,
    executor: Executor | None = None,
    users: UserDirectory | None = None,
) -> FastAPI:
    """Crea la app. `store`, `executor` y `users` permiten inyectar dobles en los tests."""
    settings = settings or ApiSettings()
    install_redaction()
    if users is None:
        check_users_file(settings)
        if settings.users_file is not None:
            users = UserDirectory.from_file(settings.users_file)
        else:
            users = UserDirectory()
            log.warning("PRIORIZA_API_USERS_FILE no está definido: toda ruta protegida da 401")
    if store is None:
        if settings.store == "sql":
            from shared.db.session import session_factory

            from api.sql_store import SqlPlanStore

            store = SqlPlanStore(session_factory())
        else:
            store = MemoryPlanStore()
    owns_executor = executor is None
    pool: Executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="schedule")
    catalogs = CatalogProvider(settings)
    jobs = JobManager(executor=pool, store=store, catalogs=catalogs, settings=settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_executor:
            pool.shutdown(wait=False, cancel_futures=True)

    # Nunca se registra una clave de API: ni en el access log ni en mensajes.
    for known_key in users.keys_for_redaction():
        register_secret(known_key)

    docs = settings.docs_active
    app = FastAPI(
        title="Prioriza API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    # El último agregado es el más externo: cabeceras -> Host -> CORS -> límite -> límites.
    # Las cabeceras de seguridad van por fuera de todo, también en los 400 de Host no permitido.
    app.add_middleware(RequestLimitsMiddleware, settings=settings)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["X-API-Key", "Content-Type"],
        )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware)
    app.state.users = users
    app.state.services = Services(settings=settings, store=store, jobs=jobs, catalogs=catalogs)
    for module in (system, waitlist, simulation, schedule, plans):
        app.include_router(module.router)
    return app
