"""Oferta estacionaria de la simulación (diseño §3): no usa los ``slot`` del generador.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Las sesiones salen de ``synthetic.capacity.session_schedule`` (la misma función pura del
generador): cada celda usa una duración fija (240, 180, 120 o 60 min en CNE; 360 en pabellón) y
las sesiones se reparten en el tiempo por déficit acumulado dentro de cada grupo
(servicio, tipo), de modo que la oferta de un grupo nunca supera sus minutos meta y queda a menos
de una sesión larga de ellos. Sin azar.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from scheduler.config import OverbookingConfig
from scheduler.instance import BLOCK_COLUMNS
from shared.schemas import CareType
from synthetic.capacity import Cell, session_schedule

from simulation.config import SimulationConfig
from simulation.world import World

WORKDAYS = 5
UTC = ZoneInfo("UTC")
OVERBOOK_FRACTION = OverbookingConfig().max_fraction


def _hospital_sequence(hospitals: list[tuple[str, float]]) -> list[str]:
    """Secuencia determinista de hospitales ponderada por ``hospital_complexity_weights``."""
    if not hospitals:
        return []
    total = sum(w for _, w in hospitals)
    if total <= 0:
        return [c for c, _ in hospitals]
    seq: list[str] = []
    for code, w in hospitals:
        seq.extend([code] * max(1, round(w / total * 100)))
    return seq


def schedule(
    world: World, config: SimulationConfig, care: str, cells: list[Cell]
) -> list[tuple[int, Cell, int]]:
    """Sesiones ``(semana, celda, minutos)`` de un tipo de atención en las semanas simuladas."""
    lengths = world.session_lengths.get(care) or (world.session_min[care],)
    return session_schedule(
        cells,
        lengths,
        config.weeks + config.horizon_weeks,
        config.capacity_multiplier,
        world.session_reference_weeks,
    )


def build_supply(world: World, config: SimulationConfig) -> pl.DataFrame:
    """Bloques de las semanas 0..T+H-1 (el planificador de la semana k usa k+1..k+H)."""
    start = world.horizon_start
    tz = world.timezone
    cne_starts = world.cne_starts
    iq_start = world.iq_start
    run_id = world.run_id

    cne_cells = sorted(
        (c for c in world.cells if c.care_type == CareType.CONSULTATION.value),
        key=lambda c: (c.service, c.specialty),
    )
    iq_cells = sorted(
        (c for c in world.cells if c.care_type == CareType.SURGERY.value),
        key=lambda c: (c.service, c.specialty),
    )

    rows: list[dict[str, Any]] = []

    def add_block(
        *,
        resource_id: str,
        service: int,
        hosp: str,
        spec: str,
        kind: str,
        local: datetime,
        minutes: int,
        unit: int | None,
    ) -> None:
        rows.append(
            {
                "slot_id": str(uuid.uuid5(uuid.UUID(run_id), f"sim-slot:{len(rows)}")),
                "resource_id": resource_id,
                "resource_kind": kind,
                "health_service_code": service,
                "establishment_code": hosp,
                "specialty_code": spec,
                "start_at": local.astimezone(UTC),
                "duration_min": minutes,
                "unit_min": unit,
            }
        )

    # CNE: sesión de duración variable por celda; posición k mod 10, agenda por cada 10 sesiones
    # de la celda.
    per_cell: dict[tuple[int, str], list[tuple[int, int]]] = {}
    for week, cell, minutes in schedule(world, config, CareType.CONSULTATION.value, cne_cells):
        per_cell.setdefault((cell.service, cell.specialty), []).append((week, minutes))
    unit_of = {(c.service, c.specialty): c.unit_min for c in cne_cells}
    for (service, spec), sessions in sorted(per_cell.items()):
        hospitals = _hospital_sequence(world.hospitals_by_service.get(service, []))
        for g, (week, minutes) in enumerate(sessions):
            pos = g % 10
            day, half = pos // 2, pos % 2
            begin = cne_starts[half % len(cne_starts)]
            local = datetime.combine(start + timedelta(weeks=week, days=day), begin, tzinfo=tz)
            hosp = hospitals[g % len(hospitals)] if hospitals else ""
            add_block(
                resource_id=f"sim:{service}:{spec}:a{g // 10}",
                service=service,
                hosp=hosp,
                spec=spec,
                kind="specialist_agenda",
                local=local,
                minutes=minutes,
                unit=unit_of[(service, spec)],
            )

    # Pabellón: bloque a las 08:00; ronda continua por servicio, especialidades ordenadas por
    # código; un pabellón por cada 5 bloques del día.
    per_service: dict[int, list[tuple[int, str, int]]] = {}
    for week, cell, minutes in schedule(world, config, CareType.SURGERY.value, iq_cells):
        per_service.setdefault(cell.service, []).append((week, cell.specialty, minutes))
    for service in sorted(per_service):
        hospitals = _hospital_sequence(world.hospitals_by_service.get(service, []))
        flat = sorted(per_service[service])
        for g, (week, spec, minutes) in enumerate(flat):
            local = datetime.combine(
                start + timedelta(weeks=week, days=g % WORKDAYS), iq_start, tzinfo=tz
            )
            hosp = hospitals[g % len(hospitals)] if hospitals else ""
            add_block(
                resource_id=f"sim:{service}:or{g // WORKDAYS}",
                service=service,
                hosp=hosp,
                spec=spec,
                kind="operating_room",
                local=local,
                minutes=minutes,
                unit=None,
            )

    schema = {
        "slot_id": pl.String,
        "resource_id": pl.String,
        "resource_kind": pl.String,
        "health_service_code": pl.Int64,
        "establishment_code": pl.String,
        "specialty_code": pl.String,
        "start_at": pl.Datetime("us", "UTC"),
        "duration_min": pl.Int64,
        "unit_min": pl.Int64,
    }
    if not rows:
        return pl.DataFrame({c: [] for c in BLOCK_COLUMNS}, schema=schema)
    return pl.DataFrame(rows, schema=schema).select(BLOCK_COLUMNS).sort("start_at", "slot_id")


def supply_coverage(world: World, config: SimulationConfig) -> dict[str, dict[str, Any]]:
    """Celdas con alguna sesión en las semanas confirmables y parte del stock que cubren.

    Mide la granularidad de la oferta (diseño §3): a tamaños chicos muchas celdas no reciben
    ninguna sesión en el periodo simulado y su stock no puede atenderse con ninguna política.
    Además informa los minutos meta de la ventana (``minutes_target``: minutos por semana de las
    celdas por ``capacity_multiplier`` por las semanas de la ventana) y los ofrecidos
    (``minutes_offered``), el histograma de duraciones de sesión y, en consulta, qué proporción
    de los cupos queda en sesiones sin sobrecupo posible (``floor(0,25·C_b) = 0``; un cambio de
    equidad frente a sesiones de 240 min).
    """
    supply = build_supply(world, config)
    local = pl.col("start_at").dt.convert_time_zone(str(world.timezone)).dt.date()
    first = world.horizon_start + timedelta(days=7)
    last = world.horizon_start + timedelta(days=7 * (config.weeks + config.commit_weeks))
    window_weeks = (last - first).days // 7
    in_window = supply.filter((local >= first) & (local < last))
    out: dict[str, dict[str, Any]] = {}
    for kind, care in (
        ("specialist_agenda", CareType.CONSULTATION.value),
        ("operating_room", CareType.SURGERY.value),
    ):
        blocks = in_window.filter(pl.col("resource_kind") == kind)
        served = set(blocks.select("health_service_code", "specialty_code").unique().iter_rows())
        cells = {(c.service, c.specialty) for c in world.cells if c.care_type == care}
        stock = world.stock.filter(pl.col("care_type") == care)
        keys = stock.select("health_service_code", "specialty_code").iter_rows()
        in_served = sum(1 for k in keys if k in served)
        target = (
            sum(c.minutes_per_week for c in world.cells if c.care_type == care)
            * config.capacity_multiplier
            * window_weeks
        )
        hist = Counter(blocks["duration_min"].to_list())
        entry: dict[str, Any] = {
            "blocks": blocks.height,
            "cells": len(cells),
            "cells_with_block": len(served & cells),
            "stock": stock.height,
            "stock_in_cells_with_block": in_served,
            "minutes_target": target,
            "minutes_offered": int(blocks["duration_min"].sum() or 0),
            "duration_histogram": {str(d): hist[d] for d in sorted(hist, reverse=True)},
        }
        if care == CareType.CONSULTATION.value:
            seats = [
                int(d) // int(u)
                for d, u in blocks.select("duration_min", "unit_min").iter_rows()
                if u
            ]
            no_overbook = [x for x in seats if math.floor(OVERBOOK_FRACTION * x) < 1]
            entry["seats"] = sum(seats)
            entry["seats_without_overbooking_share"] = (
                sum(no_overbook) / sum(seats) if seats else 0.0
            )
            entry["blocks_without_overbooking_share"] = (
                len(no_overbook) / len(seats) if seats else 0.0
            )
        out[care] = entry
    return out
