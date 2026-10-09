"""Oferta estacionaria de la simulación (diseño §3): no usa los ``slot`` del generador.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La celda ``c`` recibe en la semana ``w`` ``floor(r_c·(w+1) + φ_c) - floor(r_c·w + φ_c)``
sesiones, con una fase ``φ_c`` distinta por celda (secuencia de Weyl con la razón áurea). Sin la
fase, toda celda con ``r_c < 1`` (tamaños chicos) no tendría sesiones o las tendría todas en las
mismas semanas; con ella el total de sesiones de cada semana queda cerca de ``Σ r_c`` y cada
celda recibe ``r_c`` sesiones por semana en promedio.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from scheduler.instance import BLOCK_COLUMNS
from shared.schemas import CareType

from simulation.config import SimulationConfig
from simulation.world import World

WORKDAYS = 5
UTC = ZoneInfo("UTC")


GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0


def _weeks_of(rate: float, phase: float, n_weeks: int) -> list[int]:
    """Semana de cada sesión de una celda con ``rate`` sesiones por semana y fase ``phase``."""
    out: list[int] = []
    for w in range(n_weeks):
        n = math.floor(rate * (w + 1) + phase) - math.floor(rate * w + phase)
        out.extend([w] * n)
    return out


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


def build_supply(world: World, config: SimulationConfig) -> pl.DataFrame:
    """Bloques de las semanas 0..T+H-1 (el planificador de la semana k usa k+1..k+H)."""
    n_weeks = config.weeks + config.horizon_weeks
    start = world.horizon_start
    tz = world.timezone
    cne_starts = world.cne_starts
    iq_start = world.iq_start
    run_id = world.run_id

    cne_cells = [c for c in world.cells if c.care_type == CareType.CONSULTATION.value]
    iq_cells = [c for c in world.cells if c.care_type == CareType.SURGERY.value]

    rows: list[dict[str, Any]] = []

    def add_block(
        *,
        resource_id: str,
        service: int,
        hosp: str,
        spec: str,
        kind: str,
        care: str,
        local: datetime,
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
                "duration_min": world.session_min[care],
                "unit_min": unit,
            }
        )

    def rate(cell: Any) -> float:
        return (
            cell.minutes_per_week / world.session_min[cell.care_type] * config.capacity_multiplier
        )

    # CNE: sesión de 240 min; posición k mod 10, agenda por cada 10 sesiones de la celda.
    for ci, cell in enumerate(sorted(cne_cells, key=lambda c: (c.service, c.specialty))):
        service, spec = cell.service, cell.specialty
        hospitals = _hospital_sequence(world.hospitals_by_service.get(service, []))
        weeks = _weeks_of(rate(cell), (ci + 1) * GOLDEN % 1.0, n_weeks)
        for g, week in enumerate(weeks):
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
                care=cell.care_type,
                local=local,
                unit=cell.unit_min,
            )

    # Pabellón: bloque de 360 min a las 08:00; ronda continua por servicio, especialidades
    # ordenadas por código; un pabellón por cada 5 bloques del día.
    per_service: dict[int, list[tuple[int, str]]] = {}
    for ci, cell in enumerate(sorted(iq_cells, key=lambda c: (c.service, c.specialty))):
        phase = (ci + 1) * GOLDEN % 1.0
        for week in _weeks_of(rate(cell), phase, n_weeks):
            per_service.setdefault(cell.service, []).append((week, cell.specialty))
    for service in sorted(per_service):
        hospitals = _hospital_sequence(world.hospitals_by_service.get(service, []))
        flat = sorted(per_service[service])
        for g, (week, spec) in enumerate(flat):
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
                care=CareType.SURGERY.value,
                local=local,
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
    """
    supply = build_supply(world, config)
    local = pl.col("start_at").dt.convert_time_zone(str(world.timezone)).dt.date()
    first = world.horizon_start + timedelta(days=7)
    last = world.horizon_start + timedelta(days=7 * (config.weeks + config.commit_weeks))
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
        out[care] = {
            "blocks": blocks.height,
            "cells": len(cells),
            "cells_with_block": len(served & cells),
            "stock": stock.height,
            "stock_in_cells_with_block": in_served,
        }
    return out
