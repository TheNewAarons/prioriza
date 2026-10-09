"""Trabajos de programación asíncronos.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Un `ThreadPoolExecutor` de un hilo corre un trabajo a la vez (CP-SAT ya usa un hilo en modo
determinista y una corrida canónica tarda minutos). El resultado entra al `PlanStore` como
`pending`; el trabajo nunca aprueba ni activa nada.

Los trabajos viven en memoria: se pierden al reiniciar el proceso (el plan ya guardado no).
Se limita cuántos puede haber pendientes o en curso, por usuario y en total, y los terminados
se olvidan pasadas `job_ttl_hours`. Los mensajes de error que ve el usuario no incluyen rutas
ni detalles internos: el detalle va al log del servidor con una referencia.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Executor, Future
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from scheduler.adapters import instance_from_run
from scheduler.config import OverbookingConfig, SchedulerConfig, SolverConfig
from scheduler.plan import SchedulePlan, greedy_schedule, solve
from shared.db.enums import Policy

from api.auth import User
from api.catalog import CatalogProvider, CatalogUnavailable
from api.plans import NewPlan, NotFound, PlanError, PlanStore
from api.schemas import JobStatus, ScheduleRequestIn
from api.settings import ApiSettings

log = logging.getLogger("api.jobs")

ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)


class JobLimitExceeded(PlanError):
    """Hay demasiados trabajos pendientes o en curso (del usuario o en total)."""


def user_message(exc: BaseException, ref: str) -> str:
    """Mensaje para el usuario: causas esperadas sin rutas; el resto, genérico con referencia."""
    if isinstance(exc, CatalogUnavailable):
        return "la corrida sintética configurada no está disponible"
    if isinstance(exc, FileNotFoundError) and "modelo de inasistencias" in str(exc):
        return (
            "no existe el modelo de inasistencias de la corrida; ejecuta `make train-noshow` "
            "o pide la programación con overbooking=false"
        )
    return f"error interno al calcular el plan (referencia {ref}; ver el log del servidor)"


@dataclass(frozen=True)
class JobRecord:
    """Estado de un trabajo."""

    job_id: uuid.UUID
    status: JobStatus
    policy: Policy
    requested_by: str
    created_at: datetime
    plan_id: uuid.UUID | None = None
    error: str | None = None


class InlineExecutor(Executor):
    """Ejecutor que corre el trabajo en el acto; pensado para tests deterministas."""

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


def build_config(request: ScheduleRequestIn) -> SchedulerConfig:
    """Configuración del programador; fifo y priority no usan sobrecupo ni modelo."""
    use_overbooking = request.policy is Policy.OPTIMIZED and request.overbooking
    return SchedulerConfig(
        horizon_weeks=request.horizon_weeks,
        overbooking=OverbookingConfig(enabled=use_overbooking, alpha=request.alpha),
        time_limit_s=request.time_limit_s,
        solver=SolverConfig(),
    )


@dataclass
class JobManager:
    """Registro de trabajos y ejecución en segundo plano."""

    executor: Executor
    store: PlanStore
    catalogs: CatalogProvider
    settings: ApiSettings
    _jobs: dict[uuid.UUID, JobRecord] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def submit(self, request: ScheduleRequestIn, user: User) -> JobRecord:
        """Registra el trabajo como `queued` y lo envía al ejecutor.

        `JobLimitExceeded` si el usuario o el total ya tienen el máximo de trabajos activos.
        """
        now = datetime.now(UTC)
        job = JobRecord(
            job_id=uuid.uuid4(),
            status=JobStatus.QUEUED,
            policy=request.policy,
            requested_by=user.name,
            created_at=now,
        )
        with self._lock:
            self._purge(now)
            active = [j for j in self._jobs.values() if j.status in ACTIVE]
            mine = [j for j in active if j.requested_by == user.name]
            if len(mine) >= self.settings.max_active_jobs_per_user:
                raise JobLimitExceeded(
                    f"ya tienes {len(mine)} programaciones pendientes o en curso; espera a que "
                    "terminen"
                )
            if len(active) >= self.settings.max_active_jobs:
                raise JobLimitExceeded("hay demasiadas programaciones en cola; reintenta después")
            self._jobs[job.job_id] = job
        try:
            self.executor.submit(self._run, job.job_id, request, user)
        except RuntimeError as exc:  # ejecutor apagado
            ref = job.job_id.hex[:8]
            log.exception("no se pudo encolar el trabajo %s", ref)
            self._update(job.job_id, status=JobStatus.FAILED, error=user_message(exc, ref))
        return self.get(job.job_id)

    def _purge(self, now: datetime) -> None:
        """Olvida los trabajos terminados más antiguos que `job_ttl_hours` (con el lock)."""
        cutoff = now - timedelta(hours=self.settings.job_ttl_hours)
        old = [k for k, j in self._jobs.items() if j.status not in ACTIVE and j.created_at < cutoff]
        for k in old:
            del self._jobs[k]

    def get(self, job_id: uuid.UUID) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"no existe el trabajo {job_id}")
        return job

    def _update(self, job_id: uuid.UUID, **changes: Any) -> None:
        with self._lock:
            self._jobs[job_id] = replace(self._jobs[job_id], **changes)

    def _run(self, job_id: uuid.UUID, request: ScheduleRequestIn, user: User) -> None:
        self._update(job_id, status=JobStatus.RUNNING)
        try:
            plan_id = self._compute(request, user)
        except Exception as exc:
            ref = job_id.hex[:8]
            log.exception("falló el trabajo de programación %s", ref)
            self._update(job_id, status=JobStatus.FAILED, error=user_message(exc, ref))
            return
        self._update(job_id, status=JobStatus.SUCCEEDED, plan_id=plan_id)

    def _compute(self, request: ScheduleRequestIn, user: User) -> uuid.UUID:
        config = build_config(request)
        instance, info = instance_from_run(
            self.catalogs.run_dir(),
            config,
            models_dir=self.settings.models_dir,
            seed=self.settings.seed,
        )
        plan: SchedulePlan
        if request.policy is Policy.OPTIMIZED:
            plan = solve(instance, config)
        else:
            plan = greedy_schedule(
                instance, config, "fifo" if request.policy is Policy.FIFO else "priority"
            )
        record = self.store.add(
            NewPlan(
                run_id=info.run_id,
                plan=plan,
                instance=instance,
                horizon_end_exclusive=instance.horizon_start
                + timedelta(days=7 * config.horizon_weeks),
                requested_by=user.name,
                config={
                    "request": request.model_dump(mode="json"),
                    "scheduler": config.model_dump(mode="json"),
                    "config_digest": config.digest(),
                },
            )
        )
        return record.id


__all__ = ["InlineExecutor", "JobLimitExceeded", "JobManager", "JobRecord", "build_config"]
