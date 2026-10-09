"""Oferta del generador repartida en semanas y días (corrección del artefacto §11.2).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.

Antes de la corrección, en la corrida canónica (N 100.000, 26 semanas) una semana tenía 3.149
de las 6.777 sesiones CNE y 3.276 de los 4.249 bloques de pabellón caían en lunes.
"""

from __future__ import annotations

from datetime import date

import polars as pl
from synthetic.capacity import _week_slots, horizon_start


def _located(ds) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    start = horizon_start(date.fromisoformat(str(ds.run["as_of"])))
    kinds = ds.tables["resource"].select(pl.col("id").alias("resource_id"), "kind")
    local = pl.col("start_at").dt.convert_time_zone("America/Santiago")
    return (
        ds.tables["slot"]
        .join(kinds, on="resource_id")
        .with_columns(
            ((local.dt.date() - pl.lit(start)).dt.total_days() // 7).alias("week"),
            local.dt.weekday().alias("weekday"),
        )
    )


def test_supply_is_spread_over_weeks_and_weekdays(make_dataset) -> None:  # type: ignore[no-untyped-def]
    slots = _located(make_dataset(10_000, 42))
    for kind in ("specialist_agenda", "operating_room"):
        k = slots.filter(pl.col("kind") == kind)
        per_week = k.group_by("week").len()["len"]
        mean = k.height / 26
        assert per_week.len() == 26, kind  # ninguna semana vacía
        assert per_week.max() <= 2.0 * mean, (kind, per_week.max(), mean)
        per_day = k.group_by("weekday").len()
        assert set(per_day["weekday"].to_list()) == {1, 2, 3, 4, 5}, kind
        assert per_day["len"].max() <= 2.0 * k.height / 5, kind
    # Un recurso nunca tiene dos sesiones a la misma hora.
    assert slots.group_by("resource_id", "start_at").len()["len"].max() == 1


def test_week_slots_spacing_and_phase() -> None:
    """Sesiones a intervalos regulares; la fase desplaza la semana de un recurso con una sola."""
    assert [w for w, _ in _week_slots(4, 8, 0.5)] == [1, 3, 5, 7]
    assert [w for w, _ in _week_slots(1, 26, 0.5)] == [13]
    assert [w for w, _ in _week_slots(1, 26, 0.1)] == [2]
    weeks = _week_slots(30, 26, 0.3)
    assert len(weeks) == 30 and max(w for w, _ in weeks) == 25
    assert max(i for _, i in weeks) == 1  # a lo más dos por semana
