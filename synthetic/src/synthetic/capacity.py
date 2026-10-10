"""Oferta sintética: recursos (agendas de especialista, pabellones) y sesiones (slots).

Throughput por ley de Little, theta = 7·L/m entradas por semana (sección 3 del plan).
Las sesiones se reparten sin aleatoriedad: ``session_schedule`` (duración variable por
celda y reparto en el tiempo por déficit acumulado dentro de cada grupo servicio-tipo), un
reparto ponderado determinista entre hospitales y rotación determinista de día y jornada.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import polars as pl
from shared.schemas import CareType

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
    """Duración máxima de una sesión: 240 min en consulta CNE, 360 min en bloque de pabellón."""
    key = "cne_session_min" if care_type == CareType.CONSULTATION.value else "iq_block_min"
    return int(a.value(key))


def session_lengths(a: Assumptions, care_type: str) -> tuple[int, ...]:
    """Duraciones posibles de una sesión (supuestos ``cne_session_lengths_min`` y similar)."""
    key = (
        "cne_session_lengths_min"
        if care_type == CareType.CONSULTATION.value
        else "iq_block_lengths_min"
    )
    return tuple(sorted((int(x) for x in a.value(key)), reverse=True))


def capacity_targets(
    t: CalibrationTargets, a: Assumptions, cfg: RunConfig, entries: pl.DataFrame
) -> pl.DataFrame:
    """Minutos programables por semana objetivo, por (servicio, tipo), solo grupos con entradas.

    ``target_min_per_week`` suma solo las celdas que pueden recibir sesiones (ver
    ``session_length``): la oferta de la ventana de ``H`` semanas queda a menos de ``session_min``
    minutos de ``H`` veces esta meta, por ambos lados. ``unserved_min_per_week`` suma las celdas
    sin oferta posible (menos de media sesión de la menor duración en el periodo de referencia).
    """
    ref_weeks = int(a.value("cne_session_reference_weeks"))
    agg: dict[tuple[int, str], float] = {}
    unserved: dict[tuple[int, str], float] = {}
    for c in capacity_cells(t, a, cfg, entries):
        key = (c.service, c.care_type)
        agg.setdefault(key, 0.0)
        unserved.setdefault(key, 0.0)
        if session_length(c.minutes_per_week, session_lengths(a, c.care_type), ref_weeks):
            agg[key] += c.minutes_per_week
        else:
            unserved[key] += c.minutes_per_week
    keys = sorted(agg)
    return pl.DataFrame(
        {
            "health_service_code": [k[0] for k in keys],
            "care_type": [k[1] for k in keys],
            "target_min_per_week": [agg[k] for k in keys],
            "unserved_min_per_week": [unserved[k] for k in keys],
            "session_min": [session_minutes(a, k[1]) for k in keys],
        },
        schema={
            "health_service_code": pl.Int64,
            "care_type": pl.String,
            "target_min_per_week": pl.Float64,
            "unserved_min_per_week": pl.Float64,
            "session_min": pl.Int64,
        },
    )


class SessionCell(Protocol):
    """Lo que ``session_schedule`` necesita de una celda (la satisface ``Cell``)."""

    @property
    def service(self) -> int: ...

    @property
    def care_type(self) -> str: ...

    @property
    def specialty(self) -> str: ...

    @property
    def minutes_per_week(self) -> float: ...


REFERENCE_WEEKS = 26
_EPS = 1e-9


def session_length(
    minutes_per_week: float, lengths: Sequence[int], reference_weeks: int
) -> int | None:
    """Duración fija de las sesiones de una celda, o ``None`` si no recibe oferta.

    Es la mayor duración ``d`` de ``lengths`` con ``minutes_per_week * reference_weeks >= d``
    (la celda llena al menos una sesión completa en el periodo de referencia). Si ni la menor
    cabe entera, usa la menor mientras la celda acumule al menos media sesión de esa duración;
    con menos que eso la celda queda sin oferta (limitación declarada).
    """
    total = minutes_per_week * reference_weeks
    ordered = sorted(lengths, reverse=True)
    for d in ordered:
        if total >= d - _EPS:
            return d
    smallest = ordered[-1]
    return smallest if total >= smallest / 2.0 - _EPS else None


def session_schedule[C: SessionCell](
    cells: Sequence[C],
    lengths: Sequence[int],
    weeks: int,
    multiplier: float,
    reference_weeks: int = REFERENCE_WEEKS,
    warmup_weeks: int | None = None,
) -> list[tuple[int, C, int]]:
    """Reparte sesiones de duración variable en ``weeks`` semanas (pura y determinista).

    **Calentamiento.** El reparto se simula desde la semana ``-W`` hasta ``weeks - 1`` y se
    descartan las sesiones con semana negativa, con ``W = warmup_weeks`` (por defecto
    ``reference_weeks``). Sin él, el déficit acumulado parte de cero y las primeras semanas casi
    no tienen sesiones (rampa de arranque en frío de unas 5 semanas). Con él, la semana 0 ya
    está en régimen. Dentro de la ventana ``[0, weeks)`` la oferta de un grupo queda a no más de
    ``max(lengths)`` minutos de ``rate * (w + 1)`` en cada semana ``w`` (``rate`` = minutos por
    semana del grupo): la oferta acumulada total está en ``[T - L, T]`` y se le resta la del
    calentamiento, que también está en ``[T0 - L, T0]``; la diferencia queda en ``(-L, L)``
    (``L = max(lengths)``).

    Devuelve ``(semana, celda, duración en minutos)``. Cada celda usa una sola duración
    (``session_length``). El reparto es por grupo ``(servicio, tipo)``: la semana ``w`` el grupo
    puede haber ofrecido a lo más ``T(w) = sum_c m_c * (w + 1)`` minutos, con ``m_c`` los
    minutos por semana de la celda por ``multiplier`` (solo celdas con oferta). Mientras quepa
    (``ofrecido + d <= T(w)``) se emite una sesión a la celda con mayor ``déficit / d``
    (``déficit = m_c * (w + 1 + W) - ofrecido_c``; desempate por especialidad y posición) si su
    déficit llega a ``d / 2``; si ninguna llega y todavía sobran ``max(lengths)`` minutos, a la
    de mayor déficit positivo. Por construcción la oferta acumulada de cada grupo nunca supera
    ``T`` y queda a menos de ``max(lengths)`` minutos de ella. Sin azar: no hay semilla.
    """
    if weeks <= 0 or multiplier <= 0 or not lengths:
        return []
    longest = max(lengths)
    warm = reference_weeks if warmup_weeks is None else max(0, warmup_weeks)
    groups: dict[tuple[int, str], list[int]] = {}
    for i, c in enumerate(cells):
        groups.setdefault((c.service, c.care_type), []).append(i)
    out: list[tuple[int, C, int]] = []
    for key in sorted(groups):
        idx = sorted(groups[key], key=lambda i: (cells[i].specialty, i))
        rate: list[float] = []
        dur: list[int] = []
        members: list[int] = []
        for i in idx:
            m = cells[i].minutes_per_week * multiplier
            d = session_length(m, lengths, reference_weeks)
            if d is None or m <= 0:
                continue
            members.append(i)
            rate.append(m)
            dur.append(d)
        if not members:
            continue
        given = [0] * len(members)
        total_rate = sum(rate)
        offered = 0
        for w in range(-warm, weeks):
            steps = w + warm + 1
            target = total_rate * steps
            while True:
                best = -1
                best_score = -1.0
                for k in range(len(members)):
                    d = dur[k]
                    deficit = rate[k] * steps - given[k] * d
                    if deficit < d / 2.0 - _EPS or offered + d > target + _EPS:
                        continue
                    score = deficit / d
                    if score > best_score + _EPS:
                        best, best_score = k, score
                if best < 0 and target - offered >= longest - _EPS:
                    for k in range(len(members)):
                        deficit = rate[k] * steps - given[k] * dur[k]
                        if deficit > _EPS and offered + dur[k] <= target + _EPS:
                            score = deficit / dur[k]
                            if score > best_score + _EPS:
                                best, best_score = k, score
                if best < 0:
                    break
                given[best] += 1
                offered += dur[best]
                if w >= 0:
                    out.append((w, cells[members[best]], dur[best]))
    return out


def _weighted_sequence(items: Sequence[tuple[str, float]], n: int) -> list[str]:
    """``n`` códigos repartidos de forma ponderada y pareja (reparto suave por crédito)."""
    total = sum(w for _, w in items)
    credit = dict.fromkeys((c for c, _ in items), 0.0)
    seq: list[str] = []
    for _ in range(n):
        for code, w in items:
            credit[code] += w
        pick = max(items, key=lambda x: credit[x[0]])[0]
        credit[pick] -= total
        seq.append(pick)
    return seq


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
    cne = CareType.CONSULTATION.value
    ref_weeks = int(a.value("cne_session_reference_weeks"))
    schedule: dict[str, list[tuple[int, Cell, int]]] = {}
    for care in (cne, CareType.SURGERY.value):
        schedule[care] = session_schedule(
            [c for c in cells if c.care_type == care],
            session_lengths(a, care),
            h,
            1.0,  # capacity_multiplier ya está en minutes_per_week
            ref_weeks,
        )

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

    def add_slot(
        rid: str, spec: str, week: int, pos: int, care: str, unit: int | None, minutes: int
    ) -> None:
        if care == cne:
            day, half = pos // 2, pos % 2
            begin = cne_starts[half % len(cne_starts)]
        else:
            day, begin = pos, iq_start
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

    for care in (cne, CareType.SURGERY.value):
        by_service: dict[int, list[tuple[int, Cell, int]]] = {}
        for item in schedule[care]:
            by_service.setdefault(item[1].service, []).append(item)
        for svc in sorted(by_service):
            ordered = sorted(
                by_service[svc], key=lambda x: (x[1].specialty, x[0])
            )  # reparto de hospitales por especialidad y semana
            hosp = hospitals[svc]
            codes = _weighted_sequence(hosp, len(ordered))
            per_hosp: dict[str, list[tuple[int, Cell, int]]] = {code: [] for code, _ in hosp}
            for code, item in zip(codes, ordered, strict=True):
                per_hosp[code].append(item)
            for code, _ in hosp:
                mine = per_hosp[code]
                if not mine:
                    continue
                if care == cne:
                    by_spec: dict[str, list[tuple[int, Cell, int]]] = {}
                    for item in mine:
                        by_spec.setdefault(item[1].specialty, []).append(item)
                    for sp in sorted(by_spec):
                        sess = sorted(by_spec[sp], key=lambda x: x[0])
                        peak = max(Counter(w for w, _, _ in sess).values())
                        n_ag = math.ceil(peak / (2 * WORKDAYS))
                        rids = [
                            new_resource(
                                "specialist_agenda",
                                code,
                                svc,
                                sp,
                                f"{specs[sp].name[:44]} #{i + 1}",
                            )
                            for i in range(n_ag)
                        ]
                        offset = len(res_rows) % (2 * WORKDAYS)
                        seen: dict[int, int] = {}
                        for week, cell, minutes in sess:
                            j = seen.get(week, 0)
                            seen[week] = j + 1
                            ag, pos = divmod(j, 2 * WORKDAYS)
                            add_slot(
                                rids[ag],
                                sp,
                                week,
                                (pos + offset) % (2 * WORKDAYS),
                                care,
                                cell.unit_min,
                                minutes,
                            )
                else:
                    blocks = sorted(mine, key=lambda x: (x[0], x[1].specialty))
                    peak = max(Counter(w for w, _, _ in blocks).values())
                    n_or = math.ceil(peak / WORKDAYS)
                    rids = [
                        new_resource("operating_room", code, svc, None, f"Pabellón {i + 1}")
                        for i in range(n_or)
                    ]
                    first = len(res_rows) - n_or
                    seen = {}
                    for week, cell, minutes in blocks:
                        j = seen.get(week, 0)
                        seen[week] = j + 1
                        room, pos = divmod(j, WORKDAYS)
                        # El día rota por pabellón: sin la rotación, todo pabellón con a lo más
                        # un bloque por semana operaba solo los lunes (formulación §11.2).
                        add_slot(
                            rids[room],
                            cell.specialty,
                            week,
                            (pos + first + room) % WORKDAYS,
                            care,
                            None,
                            minutes,
                        )

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
