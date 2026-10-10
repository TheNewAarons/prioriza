"""Oferta de la simulación con sesiones de duración variable (P18).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Mundos armados a mano, sin red ni generador.
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
from simulation.config import SimulationConfig
from simulation.supply import build_supply, supply_coverage
from simulation_test_support import SPEC, make_world
from synthetic.capacity import Cell

LENGTHS = (240, 180, 120, 60)


def _world_with_cells(rates: list[float]):  # type: ignore[no-untyped-def]
    """Un servicio con una celda CNE por tasa (minutos por semana)."""
    world = make_world()
    cells = [Cell(1, "consultation", f"{SPEC}{i}", 5, r, 20, 1.0, 0.0) for i, r in enumerate(rates)]
    stock = pl.concat(
        [
            world.stock.head(1).with_columns(pl.lit(c.specialty).alias("specialty_code"))
            for c in cells
        ]
    )
    return replace(
        world,
        cells=cells,
        stock=stock,
        session_lengths={"consultation": LENGTHS, "surgery": (360,)},
    )


def test_variable_duration_supply_never_exceeds_target() -> None:
    """Duraciones en D, un solo valor por celda y oferta de la ventana <= meta."""
    world = _world_with_cells([1.0, 5.0, 12.0, 40.0, 130.0, 400.0])
    cfg = SimulationConfig(weeks=26)
    supply = build_supply(world, cfg)
    assert set(supply["duration_min"].unique()) <= set(LENGTHS)
    per_cell = supply.group_by("specialty_code").agg(pl.col("duration_min").n_unique())
    assert per_cell["duration_min"].max() == 1
    n_weeks = cfg.weeks + cfg.horizon_weeks
    target = sum(c.minutes_per_week for c in world.cells if c.minutes_per_week * 26 >= 30) * n_weeks
    assert supply["duration_min"].sum() <= target + 1e-6
    # La celda de 1 min/semana (26 min en el periodo) no recibe oferta.
    assert f"{SPEC}0" not in set(supply["specialty_code"])
    assert supply.group_by("resource_id", "start_at").len()["len"].max() == 1


def test_supply_is_deterministic() -> None:
    """Dos construcciones dan exactamente el mismo plan de oferta."""
    world = _world_with_cells([3.0, 9.0, 60.0])
    cfg = SimulationConfig(weeks=12)
    assert build_supply(world, cfg).equals(build_supply(world, cfg))


def test_supply_coverage_reports_minutes_histogram_and_overbooking() -> None:
    """``supply_coverage`` informa minutos meta/ofrecidos, histograma y cupos sin sobrecupo."""
    world = _world_with_cells([2.0, 8.0, 30.0, 150.0])
    cfg = SimulationConfig(weeks=26)
    cov = supply_coverage(world, cfg)["consultation"]
    # La ventana (semanas 1..) parte de una oferta acumulada: difiere de la meta en < 1 sesión.
    assert cov["minutes_offered"] <= cov["minutes_target"] + 240
    assert cov["minutes_offered"] > 0
    assert sum(cov["duration_histogram"].values()) == cov["blocks"]
    assert set(map(int, cov["duration_histogram"])) <= set(LENGTHS)
    assert 0.0 < cov["seats_without_overbooking_share"] < 1.0
    # Sesiones de 60 min (3 cupos) no admiten sobrecupo; las de 120 min (6 cupos) admiten 1.
    only60 = _world_with_cells([60 / 26])
    cov60 = supply_coverage(only60, cfg)["consultation"]
    assert cov60["seats_without_overbooking_share"] == 1.0
    assert (
        "seats_without_overbooking_share"
        not in supply_coverage(make_world(surgery=True), cfg)["surgery"]
    )


def test_default_world_keeps_single_length_when_none_given() -> None:
    """Sin ``session_lengths`` (mundos a mano) la oferta usa solo ``session_min``."""
    world = make_world(sessions_per_week=2.0)
    supply = build_supply(world, SimulationConfig(weeks=8))
    assert set(supply["duration_min"].unique()) == {240}
