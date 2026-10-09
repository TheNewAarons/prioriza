"""Oferta sintética: recursos (agendas de especialista, pabellones) y sesiones (slots).

Throughput por ley de Little, theta = 7·L/m entradas por semana (sección 3 del plan).
Las sesiones se reparten sin aleatoriedad: Hamilton jerárquico (grupo, especialidad,
hospital) y rotación determinista de semana, día y jornada.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import polars as pl
from shared.schemas import CareType

from synthetic.allocation import hamilton
from synthetic.catalog import SpecialtyInfo, procedure_durations, specialty_index
from synthetic.config import RunConfig
from synthetic.noshow_truth import noshow_rates
from synthetic.population import resolve_as_of
from synthetic.targets import Assumptions, CalibrationTargets
from synthetic.universe import build_universe

RESOURCE_COLUMNS = [
    "id",
    "run_id",
    "kind",
    "establishment_code",
    "health_service_code",
    "specialty_code",
    "label",
]
SLOT_COLUMNS = [
    "id",
    "run_id",
    "resource_id",
    "specialty_code",
    "start_at",
    "duration_min",
    "unit_min",
]
WORKDAYS = 5


@dataclass(frozen=True)
class Cell:
    """Celda (servicio, especialidad) con su demanda de minutos por semana.

    ``throughput_per_week`` (θ) y ``ges_throughput_per_week`` (la parte GES de θ) son las
    entradas por semana de la celda por la ley de Little (§2 de ``docs/simulation-design.md``).
    """

    service: int
    care_type: str
    specialty: str
    entries: int
    minutes_per_week: float
    unit_min: int
    throughput_per_week: float
    ges_throughput_per_week: float


def horizon_start(as_of: date) -> date:
    """Primer lunes estrictamente posterior a ``as_of``."""
    days = (7 - as_of.weekday()) % 7
    return as_of + timedelta(days=days or 7)


def capacity_cells(
    t: CalibrationTargets, a: Assumptions, cfg: RunConfig, entries: pl.DataFrame
) -> list[Cell]:
    """Celdas (servicio, tipo, especialidad) con su oferta y sus llegadas esperadas por semana.

    ``throughput_per_week`` y ``ges_throughput_per_week`` se escalan igual que
    ``minutes_per_week``; no cambia nada de lo que el generador escribe (digest idéntico).
    """
    uni = build_universe(t, a)
    specs = specialty_index(t)
    durations = procedure_durations(t, a)
    scale = cfg.size / uni.total * float(a.value("capacity_multiplier"))
    rates = noshow_rates(t, a)
    turnover = float(a.value("iq_turnover_min"))
    util = float(a.value("iq_utilization"))

    theta: dict[tuple[int, str], float] = {}
    ges_theta: dict[tuple[int, str], float] = {}
    for r in t.service_rows:
        theta[(r.health_service_code, r.care_type)] = 7.0 * r.waiting_count / r.mean_wait_days
    ges_total = sum(g.waiting_count for g in t.ges_services)
    for g in uni.ges:
        care = specs[g.specialty_code].care_type.value
        for s in t.ges_services:
            key = (s.health_service_code, care)
            share = s.waiting_count / ges_total
            add = g.ytd_new_cases / 52.0 * share
            theta[key] = theta.get(key, 0.0) + add
            ges_theta[key] = ges_theta.get(key, 0.0) + add

    rows = (
        entries.with_columns(
            pl.col("procedure_code").replace_strict(durations, return_dtype=pl.Int64).alias("dur")
        )
        .group_by("health_service_code", "care_type", "specialty_code", maintain_order=False)
        .agg(pl.len().alias("n"), pl.col("dur").mean().alias("dur_mean"))
        .sort("health_service_code", "care_type", "specialty_code")
    )
    group_n: dict[tuple[int, str], int] = {}
    for r in rows.iter_rows(named=True):
        key = (int(r["health_service_code"]), str(r["care_type"]))
        group_n[key] = group_n.get(key, 0) + int(r["n"])

    cells: list[Cell] = []
    for r in rows.iter_rows(named=True):
        s, c, sp = int(r["health_service_code"]), str(r["care_type"]), str(r["specialty_code"])
        info: SpecialtyInfo = specs[sp]
        w = int(r["n"]) / group_n[(s, c)]
        th = theta.get((s, c), 0.0) * scale * w
        gth = ges_theta.get((s, c), 0.0) * scale * w
        no_show = rates.get((s, CareType(c)), 0.0)
        dur = float(r["dur_mean"])
        if c == CareType.CONSULTATION.value:
            minutes = th / (1.0 - no_show) * dur
            unit = round(dur)
        else:
            minutes = th / (1.0 - no_show) * (dur + turnover) / util
            unit = 0
        cells.append(Cell(s, c, info.code, int(r["n"]), minutes, unit, th, gth))
    return cells


_cells = capacity_cells  # alias privado histórico


def session_minutes(a: Assumptions, care_type: str) -> int:
    """Duración de una sesión: 240 min en consulta CNE, 360 min en bloque de pabellón."""
    key = "cne_session_min" if care_type == CareType.CONSULTATION.value else "iq_block_min"
    return int(a.value(key))


def capacity_targets(
    t: CalibrationTargets, a: Assumptions, cfg: RunConfig, entries: pl.DataFrame
) -> pl.DataFrame:
    """Minutos programables por semana objetivo, por (servicio, tipo), solo grupos con entradas."""
    agg: dict[tuple[int, str], float] = {}
    for c in capacity_cells(t, a, cfg, entries):
        agg[(c.service, c.care_type)] = agg.get((c.service, c.care_type), 0.0) + c.minutes_per_week
    keys = sorted(agg)
    return pl.DataFrame(
        {
            "health_service_code": [k[0] for k in keys],
            "care_type": [k[1] for k in keys],
            "target_min_per_week": [agg[k] for k in keys],
            "session_min": [session_minutes(a, k[1]) for k in keys],
        },
        schema={
            "health_service_code": pl.Int64,
            "care_type": pl.String,
            "target_min_per_week": pl.Float64,
            "session_min": pl.Int64,
        },
    )


GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0


def resource_phase(n: int) -> float:
    """Fase en [0, 1) del recurso ``n`` (secuencia de Weyl con la razón áurea)."""
    return ((n + 1) * GOLDEN) % 1.0


def _week_slots(count: int, horizon: int, phase: float) -> list[tuple[int, int]]:
    """Para ``count`` sesiones, devuelve (semana, índice dentro de la semana) por sesión.

    Las sesiones quedan a intervalos regulares de ``horizon / count`` semanas, desplazadas por
    ``phase``. Con la misma fase (antes, 0,5 para todos) cada recurso con una sola sesión caía
    en la semana ``horizon // 2`` y la oferta se concentraba ahí (formulación §11.2); con una
    fase distinta por recurso el total por semana queda parejo.
    """
    out: list[tuple[int, int]] = []
    seen: dict[int, int] = {}
    for k in range(count):
        week = min(horizon - 1, int((k + phase) * horizon / count))
        out.append((week, seen.get(week, 0)))
        seen[week] = seen.get(week, 0) + 1
    return out


def _interleave(counts: dict[str, int]) -> list[str]:
    """Orden determinista que reparte cada especialidad de forma pareja a lo largo de la lista."""
    items: list[tuple[float, str]] = []
    for sp in sorted(counts):
        c = counts[sp]
        items += [((i + 0.5) / c, sp) for i in range(c)]
    items.sort()
    return [sp for _, sp in items]


def generate_capacity(
    t: CalibrationTargets,
    a: Assumptions,
    cfg: RunConfig,
    entries: pl.DataFrame,
    run_id: UUID,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Genera ``resource`` y ``slot`` para el horizonte de ``cfg.horizon_weeks`` semanas."""
    as_of = resolve_as_of(cfg, a)
    h = cfg.horizon_weeks
    start = horizon_start(as_of)
    tz = ZoneInfo(str(a.value("timezone")))
    cne_starts = [time.fromisoformat(x) for x in a.value("cne_session_starts")]
    iq_start = time.fromisoformat(a.value("iq_block_start"))
    specs = specialty_index(t)
    hw = a.value("hospital_complexity_weights")
    hospitals: dict[int, list[tuple[str, float]]] = {}
    for e in sorted(t.establishments, key=lambda x: x.code):
        hospitals.setdefault(e.health_service_code, []).append(
            (e.code, float(hw.get(e.complexity or "", 1.0)))
        )

    cells = capacity_cells(t, a, cfg, entries)
    groups: dict[tuple[int, str], list[Cell]] = {}
    for c in cells:
        groups.setdefault((c.service, c.care_type), []).append(c)
    group_keys = sorted(groups)
    weights = {
        k: h * sum(c.minutes_per_week for c in groups[k]) / session_minutes(a, k[1])
        for k in group_keys
    }
    total_sessions = round(sum(weights.values()))
    group_sessions = hamilton(weights, total_sessions)

    res_rows: list[dict[str, object]] = []
    slot_rows: list[dict[str, object]] = []

    def new_resource(kind: str, hosp: str, svc: int, spec: str | None, label: str) -> str:
        rid = str(uuid.uuid5(run_id, f"resource:{len(res_rows)}"))
        res_rows.append(
            {
                "id": rid,
                "run_id": str(run_id),
                "kind": kind,
                "establishment_code": hosp,
                "health_service_code": svc,
                "specialty_code": spec,
                "label": label[:64],
            }
        )
        return rid

    def add_slot(rid: str, spec: str, week: int, pos: int, care: str, unit: int | None) -> None:
        if care == CareType.CONSULTATION.value:
            day, half = pos // 2, pos % 2
            begin = cne_starts[half % len(cne_starts)]
            minutes = session_minutes(a, care)
        else:
            day, begin = pos, iq_start
            minutes = session_minutes(a, care)
        local = datetime.combine(start + timedelta(weeks=week, days=day), begin, tzinfo=tz)
        slot_rows.append(
            {
                "id": str(uuid.uuid5(run_id, f"slot:{len(slot_rows)}")),
                "run_id": str(run_id),
                "resource_id": rid,
                "specialty_code": spec,
                "start_at": local.astimezone(ZoneInfo("UTC")),
                "duration_min": minutes,
                "unit_min": unit,
            }
        )

    for key in group_keys:
        svc, care = key
        sessions = group_sessions[key]
        if sessions == 0:
            continue
        cell_list = sorted(groups[key], key=lambda c: c.specialty)
        by_spec = hamilton({c.specialty: c.minutes_per_week for c in cell_list}, sessions)
        unit_of = {c.specialty: c.unit_min for c in cell_list}
        hosp = hospitals[svc]
        # sesiones por (hospital, especialidad)
        per_hosp: dict[str, dict[str, int]] = {code: {} for code, _ in hosp}
        for sp in sorted(by_spec):
            if by_spec[sp] == 0:
                continue
            counts = hamilton(dict(hosp), by_spec[sp])
            for code, cnt in counts.items():
                if cnt:
                    per_hosp[code][sp] = cnt
        if care == CareType.CONSULTATION.value:
            for code, _ in hosp:
                for sp in sorted(per_hosp[code]):
                    cnt = per_hosp[code][sp]
                    n_ag = max(1, math.ceil(cnt / (2 * WORKDAYS * h)))
                    rids = [
                        new_resource(
                            "specialist_agenda", code, svc, sp, f"{specs[sp].name[:44]} #{i + 1}"
                        )
                        for i in range(n_ag)
                    ]
                    offset = len(res_rows) % (2 * WORKDAYS)
                    first = len(res_rows) - n_ag
                    for ai in range(n_ag):
                        mine = len(range(ai, cnt, n_ag))
                        for week, idx in _week_slots(mine, h, resource_phase(first + ai)):
                            pos = (idx + offset) % (2 * WORKDAYS)
                            add_slot(rids[ai], sp, week, pos, care, unit_of[sp])
        else:
            for code, _ in hosp:
                blocks = _interleave(per_hosp[code])
                if not blocks:
                    continue
                n_or = max(1, math.ceil(len(blocks) / (WORKDAYS * h)))
                rids = [
                    new_resource("operating_room", code, svc, None, f"Pabellón {i + 1}")
                    for i in range(n_or)
                ]
                first = len(res_rows) - n_or
                for oi in range(n_or):
                    mine = blocks[oi::n_or]
                    # El día rota por pabellón: sin la rotación, todo pabellón con a lo más un
                    # bloque por semana operaba solo los lunes (formulación §11.2).
                    n = first + oi
                    slots = _week_slots(len(mine), h, resource_phase(n))
                    for sp, (week, idx) in zip(mine, slots, strict=True):
                        add_slot(rids[oi], sp, week, (idx + n) % WORKDAYS, care, None)

    resource = pl.DataFrame(
        res_rows,
        schema={
            "id": pl.String,
            "run_id": pl.String,
            "kind": pl.String,
            "establishment_code": pl.String,
            "health_service_code": pl.Int64,
            "specialty_code": pl.String,
            "label": pl.String,
        },
    ).select(RESOURCE_COLUMNS)
    slot = pl.DataFrame(
        slot_rows,
        schema={
            "id": pl.String,
            "run_id": pl.String,
            "resource_id": pl.String,
            "specialty_code": pl.String,
            "start_at": pl.Datetime("us", "UTC"),
            "duration_min": pl.Int64,
            "unit_min": pl.Int64,
        },
    ).select(SLOT_COLUMNS)
    return resource, slot
