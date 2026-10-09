"""Aplicación FastAPI de Prioriza.

Se levanta como fábrica (`uvicorn --factory api.main:create_app`): importar el módulo no lee
el entorno ni el archivo de usuarios.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from shared.disclaimer import DISCLAIMER

from api.auth import UserDirectory
from api.catalog import CatalogProvider
from api.deps import Services
from api.jobs import JobManager
from api.plans import MemoryPlanStore, PlanStore
from api.routes import plans, schedule, simulation, system, waitlist
from api.settings import ApiSettings

log = logging.getLogger("api")

DESCRIPTION = f"""**{DISCLAIMER}**

El sistema apoya, no decide: la prioridad clínica es un dato de entrada, todo plan nace
`pending` y requiere la aprobación de un `revisor` antes de poder ser vigente.
Autenticación con la cabecera `X-API-Key`; roles `gestor`, `revisor` y `lectura`.
"""


def create_app(
    settings: ApiSettings | None = None,
    *,
    store: PlanStore | None = None,
    executor: Executor | None = None,
    users: UserDirectory | None = None,
) -> FastAPI:
    """Crea la app. `store`, `executor` y `users` permiten inyectar dobles en los tests."""
    settings = settings or ApiSettings()
    if users is None:
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

    app = FastAPI(
        title="Prioriza API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.users = users
    app.state.services = Services(settings=settings, store=store, jobs=jobs, catalogs=catalogs)
    for module in (system, waitlist, simulation, schedule, plans):
        app.include_router(module.router)
    return app
