"""Motor SimPy de la simulación: estados, llegadas, planificación y resolución (diseño §4/§6).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import simpy
from scheduler.adapters import entries_from_frames, noshow_from_frames
from scheduler.instance import SchedulingInstance
from scheduler.plan import SchedulePlan
from shared.schemas import CareType

from simulation import truth
from simulation.arrivals import arrival_cells
from simulation.config import SimulationConfig
from simulation.metrics import PolicyResult, build_result
from simulation.policies import apply, scheduler_config
from simulation.supply import build_supply
from simulation.world import World

LOCAL_TZ = ZoneInfo("America/Santiago")

STREAM_KEYS = ("arrivals", "donor", "frailty", "attend", "abandon")


@dataclass
class Appointment:
    """Cita vigente de una entrada reservada."""

    slot_id: str
    scheduled_start: datetime
    local_date: date
    resource_kind: str
    duration_min: int
    predicted_p: float | None
    is_overbooked: bool
    block_capacity: int  # CNE: unidades; pabellón: minutos de llenado


@dataclass
class Entry:
    """Entrada de la lista (stock o llegada) con su estado y sus uniformes de asistencia."""

    entry_id: str
    patient_id: str
    health_service_code: int
    establishment_code: str
    specialty_code: str
    procedure_code: str
    care_type: str
    clinical_priority: str
    is_ges: bool
    ges_deadline: date | None
    entry_date: date
    uniforms: tuple[float, ...]
    arrival_day: int | None
    state: str = "waiting"
    booked_on: date | None = None
    no_show_count: int = 0
    appointment: Appointment | None = None
    resolved_on: date | None = None
    first_planned_day: int | None = None
    first_planned_scheduled: bool = False


def _attrs(patient_frame: pl.DataFrame) -> dict[str, dict[str, str]]:
    return {
        str(r["patient_id"]): {
            "age_group": str(r["age_group"]),
            "insurance": str(r["insurance"]),
            "commune_code": str(r["commune_code"]),
        }
        for r in patient_frame.iter_rows(named=True)
    }


def _frailty(patient_frame: pl.DataFrame) -> dict[str, float]:
    return {
        str(r["patient_id"]): float(r["noshow_frailty"])
        for r in patient_frame.iter_rows(named=True)
    }


def _waitlist_frame(waiting: list[Entry]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "id": e.entry_id,
                "patient_id": e.patient_id,
                "health_service_code": e.health_service_code,
                "establishment_code": e.establishment_code,
                "specialty_code": e.specialty_code,
                "procedure_code": e.procedure_code,
                "care_type": e.care_type,
                "clinical_priority": e.clinical_priority,
                "is_ges": e.is_ges,
                "ges_deadline": e.ges_deadline,
                "entry_date": e.entry_date,
            }
            for e in waiting
        ],
        schema={
            "id": pl.String,
            "patient_id": pl.String,
            "health_service_code": pl.Int64,
            "establishment_code": pl.String,
            "specialty_code": pl.String,
            "procedure_code": pl.String,
            "care_type": pl.String,
            "clinical_priority": pl.String,
            "is_ges": pl.Boolean,
            "ges_deadline": pl.Date,
            "entry_date": pl.Date,
        },
    )


def _history_frame(world: World, sim_history: list[dict[str, Any]]) -> pl.DataFrame:
    if not sim_history:
        return world.history
    sim = pl.DataFrame(
        sim_history,
        schema={
            "patient_id": pl.String,
            "scheduled_start": pl.Datetime("us", "UTC"),
            "status": pl.String,
        },
    )
    return pl.concat([world.history, sim])


def _groups_frame(entries_df: pl.DataFrame, attrs: dict[str, dict[str, str]]) -> pl.DataFrame:
    """Tabla ``groups`` del programador (límites de equidad por grupo, P6) para la instancia."""
    pids = sorted(set(entries_df["patient_id"].to_list()))
    return pl.DataFrame(
        [{"patient_id": pid, **attrs[pid]} for pid in pids],
        schema={
            "patient_id": pl.String,
            "age_group": pl.String,
            "insurance": pl.String,
            "commune_code": pl.String,
        },
    )


def _blocks_in_horizon(supply: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    local = pl.col("start_at").dt.convert_time_zone("America/Santiago").dt.date()
    return supply.filter((local >= start) & (local < end))


def simulate(world: World, policy: str, config: SimulationConfig, seed: int) -> PolicyResult:
    """Una política sobre el mundo con una semilla; no lee archivos (diseño §9)."""
    env = simpy.Environment()
    ss = np.random.SeedSequence(seed)
    rng = {
        k: np.random.default_rng(child)
        for k, child in zip(STREAM_KEYS, ss.spawn(len(STREAM_KEYS)), strict=True)
    }

    params = truth.true_params(world.truth_params)

    entries: dict[str, Entry] = {}
    patient_attrs = _attrs(world.patient_frame)
    frailty = _frailty(world.patient_frame)

    events: list[tuple[int, str, str, str, str]] = []

    # Stock inicial (espera fija entre réplicas); uniformes por intento en orden de entrada.
    for r in world.stock.sort("id").iter_rows(named=True):
        eid = str(r["id"])
        uniforms = tuple(float(x) for x in rng["attend"].random(config.max_no_shows))
        entries[eid] = Entry(
            entry_id=eid,
            patient_id=str(r["patient_id"]),
            health_service_code=int(r["health_service_code"]),
            establishment_code=str(r["establishment_code"]),
            specialty_code=str(r["specialty_code"]),
            procedure_code=str(r["procedure_code"]),
            care_type=str(r["care_type"]),
            clinical_priority=str(r["clinical_priority"]),
            is_ges=bool(r["is_ges"]),
            ges_deadline=r["ges_deadline"],
            entry_date=r["entry_date"],
            uniforms=uniforms,
            arrival_day=None,
        )
        events.append((0, eid, "", "waiting", "stock"))

    # Llegadas pregeneradas (números comunes entre políticas): Poisson + donante + fragilidad.
    cells = arrival_cells(world)
    arrivals: list[tuple[int, Entry]] = []
    counter: dict[tuple[int, int], int] = {}
    for day in range(config.weeks * 7):
        day_date = world.horizon_start + timedelta(days=day)
        for ci, cell in enumerate(cells):
            n = int(rng["arrivals"].poisson(cell.throughput_per_week / 7.0))
            for _ in range(n):
                if cell.throughput_per_week > 0:
                    is_ges = rng["arrivals"].random() < (
                        cell.ges_throughput_per_week / cell.throughput_per_week
                    )
                else:
                    is_ges = False
                pool = cell.ges_donors if is_ges else cell.non_ges_donors
                if not pool:
                    # arrival_cells deja GES solo en celdas con donantes GES; sin donantes no
                    # GES (celda solo GES) la llegada no GES copia una fila GES sin su plazo.
                    pool = cell.donors
                donor = pool[int(rng["donor"].integers(0, len(pool)))]
                k = counter.get((ci, day), 0)
                counter[(ci, day)] = k + 1
                pid = f"sim-pat-{day}-{ci}-{k}"
                eid = f"sim-arr-{day}-{ci}-{k}"
                frailty[pid] = float(rng["frailty"].normal(0.0, world.sigma_u))
                patient_attrs[pid] = {
                    "age_group": str(donor["age_group"]),
                    "insurance": str(donor["insurance"]),
                    "commune_code": str(donor["commune_code"]),
                }
                deadline: date | None = None
                if is_ges:
                    deadline = day_date + (donor["ges_deadline"] - donor["entry_date"])
                arrivals.append(
                    (
                        day,
                        Entry(
                            entry_id=eid,
                            patient_id=pid,
                            health_service_code=cell.service,
                            establishment_code=str(donor["establishment_code"]),
                            specialty_code=cell.specialty,
                            procedure_code=str(donor["procedure_code"]),
                            care_type=cell.care_type,
                            clinical_priority=str(donor["clinical_priority"]),
                            is_ges=is_ges,
                            ges_deadline=deadline,
                            entry_date=day_date,
                            uniforms=tuple(
                                float(x) for x in rng["attend"].random(config.max_no_shows)
                            ),
                            arrival_day=day,
                        ),
                    )
                )

    supply = build_supply(world, config)
    slot_info: dict[str, dict[str, Any]] = {}
    for r in supply.iter_rows(named=True):
        slot_info[str(r["slot_id"])] = {
            "local_date": r["start_at"].astimezone(LOCAL_TZ).date(),
            "resource_kind": str(r["resource_kind"]),
            "duration_min": int(r["duration_min"]),
            "unit_min": None if r["unit_min"] is None else int(r["unit_min"]),
        }

    slot_scheduled: dict[str, int] = {}
    slot_attendees: dict[str, int] = {}
    slot_no_shows: dict[str, int] = {}
    slot_attended_min: dict[str, int] = {}
    slot_no_show_min: dict[str, int] = {}
    slot_scheduled_min: dict[str, int] = {}

    sim_history: list[dict[str, Any]] = []
    pred_realized: list[tuple[float, bool]] = []
    appointments_log: list[dict[str, Any]] = []
    weekly: list[dict[str, Any]] = []
    scheduler_weekly: list[dict[str, Any]] = []

    scfg = scheduler_config(config, policy)
    or_turnover = scfg.or_turnover_min
    or_max_fill = scfg.or_max_fill

    def resolve(eid: str, local_date: date) -> Any:
        # env.timeout es relativo al reloj actual: la cita se resuelve a las d + 0,5.
        yield env.timeout((local_date - world.horizon_start).days + 0.5 - env.now)
        e = entries.get(eid)
        if e is None or e.state != "booked" or e.appointment is None:
            return
        day = (local_date - world.horizon_start).days
        appt = e.appointment
        wait_days = float((appt.local_date - e.entry_date).days)
        med = float(
            world.median_wait.get((e.health_service_code, e.care_type), max(wait_days, 1.0))
        )
        lead_days = float((appt.local_date - e.booked_on).days) if e.booked_on else 0.0
        intercept = params.intercepts[(e.health_service_code, CareType(e.care_type))]
        attrs = patient_attrs.get(e.patient_id, {})
        features = pl.DataFrame(
            {
                "intercept": [intercept],
                "specialty_code": [e.specialty_code],
                "age_group": [attrs.get("age_group", "")],
                "insurance": [attrs.get("insurance", "")],
                "wait_days": [wait_days],
                "median_wait_days": [med],
                "lead_days": [lead_days],
            }
        )
        p = float(
            truth.attendance_probability(params, features, np.array([frailty[e.patient_id]]))[0]
        )
        attempt = e.no_show_count + 1
        u = (
            e.uniforms[attempt - 1]
            if attempt - 1 < len(e.uniforms)
            else float(rng["attend"].random())
        )
        no_show = u < p
        if appt.predicted_p is not None:
            pred_realized.append((appt.predicted_p, no_show))
        appointments_log.append(
            {
                "patient_id": e.patient_id,
                "care_type": e.care_type,
                "slot_id": appt.slot_id,
                "attended": not no_show,
                "is_overbooked": appt.is_overbooked,
            }
        )
        if no_show:
            e.no_show_count += 1
            events.append((day, eid, "booked", "no_show", "no_show"))
            sim_history.append(
                {
                    "patient_id": e.patient_id,
                    "scheduled_start": appt.scheduled_start,
                    "status": "no_show",
                }
            )
            slot_no_shows[appt.slot_id] = slot_no_shows.get(appt.slot_id, 0) + 1
            slot_no_show_min[appt.slot_id] = (
                slot_no_show_min.get(appt.slot_id, 0) + appt.duration_min + or_turnover
            )
            if e.no_show_count >= config.max_no_shows:
                e.state = "removed_no_show"
                e.appointment = None
                events.append((day, eid, "no_show", "removed_no_show", "two_no_shows"))
            else:
                e.state = "waiting"
                e.appointment = None
                events.append((day, eid, "no_show", "waiting", "return_waiting"))
        else:
            e.state = "resolved"
            e.resolved_on = local_date
            e.appointment = None
            events.append((day, eid, "booked", "resolved", "attended"))
            sim_history.append(
                {
                    "patient_id": e.patient_id,
                    "scheduled_start": appt.scheduled_start,
                    "status": "attended",
                }
            )
            slot_attendees[appt.slot_id] = slot_attendees.get(appt.slot_id, 0) + 1
            slot_attended_min[appt.slot_id] = (
                slot_attended_min.get(appt.slot_id, 0) + appt.duration_min + or_turnover
            )

    def plan_monday(Dk: date, k: int) -> None:
        waitlist = _waitlist_frame([e for e in entries.values() if e.state == "waiting"])
        entries_df = entries_from_frames(waitlist, world.procedures, world.rules, as_of=Dk)
        horizon_start = Dk + timedelta(days=7)
        horizon_end = horizon_start + timedelta(days=7 * config.horizon_weeks)
        # Citas ya confirmadas en el horizonte (solo con commit_weeks > 1).
        blocks_df = _blocks_in_horizon(supply, horizon_start, horizon_end).with_columns(
            pl.col("slot_id")
            .replace_strict(slot_scheduled, default=0, return_dtype=pl.Int64)
            .alias("prebooked_units"),
            pl.col("slot_id")
            .replace_strict(slot_scheduled_min, default=0, return_dtype=pl.Int64)
            .alias("prebooked_min"),
        )
        blocks_df = blocks_df.with_columns(
            pl.when(pl.col("resource_kind") == "specialist_agenda")
            .then(pl.col("prebooked_units"))
            .otherwise(0)
            .alias("prebooked_units"),
            pl.when(pl.col("resource_kind") == "operating_room")
            .then(pl.col("prebooked_min"))
            .otherwise(0)
            .alias("prebooked_min"),
        )
        # Días con una cita congelada dentro del horizonte (solo con commit_weeks > 1): R4 debe
        # verlos aunque la cita sea de otra especialidad (M-03).
        busy_df = pl.DataFrame(
            sorted(
                {
                    (e.patient_id, e.appointment.local_date)
                    for e in entries.values()
                    if e.state == "booked"
                    and e.appointment is not None
                    and horizon_start <= e.appointment.local_date < horizon_end
                }
            ),
            schema={"patient_id": pl.String, "local_date": pl.Date},
            orient="row",
        )
        noshow_df: pl.DataFrame | None = None
        model_version: str | None = None
        if scfg.overbooking.enabled:
            noshow_df, model_version = noshow_from_frames(
                entries_df,
                blocks_df,
                _history_frame(world, sim_history),
                world.specialties,
                world.bundle,
                scfg,
                as_of=Dk,
            )
        instance = SchedulingInstance.from_frames(
            as_of=Dk,
            horizon_start=horizon_start,
            entries=entries_df,
            blocks=blocks_df,
            noshow=noshow_df,
            groups=_groups_frame(entries_df, patient_attrs),
            rules_digest=world.rules.digest(),
            rules_version=world.rules.rules_version,
            yield_priorities=[str(p) for p in world.rules.ges_strict.yield_to_priorities],
            noshow_model_version=model_version,
            seed=world.seed,
            busy=busy_df,
        )
        plan = apply(instance, scfg, policy)
        scheduler_weekly.append(_scheduler_summary(plan))
        assigned = set(str(x) for x in plan.assignments["entry_id"])
        first = horizon_start
        last = first + timedelta(days=7 * config.commit_weeks)
        for row in plan.assignments.iter_rows(named=True):
            local_date = row["scheduled_start"].astimezone(LOCAL_TZ).date()
            if not (first <= local_date < last):
                continue
            eid = str(row["entry_id"])
            e = entries.get(eid)
            if e is None or e.state != "waiting":
                continue
            slot_id = str(row["slot_id"])
            info = slot_info[slot_id]
            cap = (
                info["duration_min"] // info["unit_min"]
                if info["resource_kind"] == "specialist_agenda"
                else int(or_max_fill * info["duration_min"])
            )
            e.state = "booked"
            e.booked_on = Dk
            e.appointment = Appointment(
                slot_id=slot_id,
                scheduled_start=row["scheduled_start"],
                local_date=local_date,
                resource_kind=str(row["resource_kind"]),
                duration_min=int(row["duration_min"]),
                predicted_p=row["predicted_noshow_prob"],
                is_overbooked=bool(row["is_overbooked"]),
                block_capacity=cap,
            )
            slot_scheduled[slot_id] = slot_scheduled.get(slot_id, 0) + 1
            slot_scheduled_min[slot_id] = (
                slot_scheduled_min.get(slot_id, 0) + int(row["duration_min"]) + or_turnover
            )
            events.append((7 * k, eid, "waiting", "booked", "commit"))
            env.process(resolve(eid, local_date))
        for e in entries.values():
            if e.arrival_day is not None and e.first_planned_day is None:
                e.first_planned_day = k
                e.first_planned_scheduled = e.entry_id in assigned

    def planner() -> Any:
        for k in range(config.weeks):
            if k > 0:
                yield env.timeout(7)
            Dk = world.horizon_start + timedelta(days=7 * k)
            if config.abandon_weekly_rate > 0:
                waiting = sorted(
                    (e for e in entries.values() if e.state == "waiting"), key=lambda e: e.entry_id
                )
                for e in waiting:
                    if rng["abandon"].random() < config.abandon_weekly_rate:
                        e.state = "abandoned"
                        events.append((7 * k, e.entry_id, "waiting", "abandoned", "abandon"))
            plan_monday(Dk, k)
            waiting_n = sum(1 for e in entries.values() if e.state == "waiting")
            booked_n = sum(1 for e in entries.values() if e.state == "booked")
            weekly.append(
                {
                    "week": k,
                    "date": Dk.isoformat(),
                    "list_size": waiting_n + booked_n,
                    "waiting": waiting_n,
                    "booked": booked_n,
                }
            )

    def _arrive(day: int, entry: Entry) -> Any:
        yield env.timeout(day + 0.25)
        entries[entry.entry_id] = entry
        events.append((day, entry.entry_id, "", "waiting", "arrival"))

    env.process(planner())
    for day, entry in arrivals:
        env.process(_arrive(day, entry))

    env.run()

    return build_result(
        world=world,
        config=config,
        policy=policy,
        seed=seed,
        entries=entries,
        events=events,
        weekly=weekly,
        scheduler_weekly=scheduler_weekly,
        slot_info=slot_info,
        slot_scheduled=slot_scheduled,
        slot_attendees=slot_attendees,
        slot_no_shows=slot_no_shows,
        slot_attended_min=slot_attended_min,
        slot_no_show_min=slot_no_show_min,
        slot_scheduled_min=slot_scheduled_min,
        patient_attrs=patient_attrs,
        pred_realized=pred_realized,
        appointments_log=appointments_log,
    )


def _scheduler_summary(plan: SchedulePlan) -> dict[str, Any]:
    s = plan.report["solver"]
    gaps = [g for g in s.get("gap_by_phase", {}).values() if g is not None]
    return {
        "status": s.get("status"),
        "status_by_phase": s.get("status_by_phase", {}),
        "gap": s.get("gap"),
        "gap_by_phase": s.get("gap_by_phase", {}),
        "max_gap": max(gaps) if gaps else None,
        "deterministic_time": s.get("time", {}).get("plan", {}).get("deterministic_time"),
        "wall_time_s": s.get("time", {}).get("plan", {}).get("wall_time_s"),
    }
