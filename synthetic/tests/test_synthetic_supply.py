"""Oferta del generador repartida en semanas y días (corrección del artefacto §11.2).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.

Antes de la corrección, en la corrida canónica (N 100.000, 26 semanas) una semana tenía 3.149
de las 6.777 sesiones CNE y 3.276 de los 4.249 bloques de pabellón caían en lunes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st
from synthetic.capacity import horizon_start, session_length, session_schedule


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


LENGTHS = (240, 180, 120, 60)
REF = 26


@dataclass(frozen=True)
class FakeCell:
    """Celda mínima para ``session_schedule`` (sin generador)."""

    service: int
    care_type: str
    specialty: str
    minutes_per_week: float


def test_session_length_rule() -> None:
    """Mayor duración que cabe entera en el periodo; media sesión de la menor como piso."""
    assert session_length(10.0, LENGTHS, REF) == 240  # 260 min en 26 semanas
    assert session_length(240 / REF, LENGTHS, REF) == 240
    assert session_length(239 / REF, LENGTHS, REF) == 180
    assert session_length(100 / REF, LENGTHS, REF) == 60
    assert session_length(60 / REF, LENGTHS, REF) == 60
    assert session_length(30 / REF, LENGTHS, REF) == 60  # justo media sesión de 60
    assert session_length(29.9 / REF, LENGTHS, REF) is None
    assert session_length(180 / REF, (360,), REF) == 360
    assert session_length(179 / REF, (360,), REF) is None


def _cells(rates: list[float], services: list[int]) -> list[FakeCell]:
    return [
        FakeCell(services[i % len(services)], "consultation", f"s{i:03d}", r)
        for i, r in enumerate(rates)
    ]


@settings(max_examples=60, deadline=None, derandomize=True)
@given(
    rates=st.lists(st.floats(0.2, 400.0), min_size=1, max_size=30),
    n_services=st.integers(1, 3),
    weeks=st.integers(1, 40),
    multiplier=st.sampled_from([0.5, 1.0, 1.5]),
)
def test_schedule_capacity_properties(
    rates: list[float], n_services: int, weeks: int, multiplier: float
) -> None:
    """Con calentamiento, la oferta acumulada de la ventana queda a menos de 240 min de la meta.

    Cota exacta: la oferta total hasta la semana ``w`` está en ``[T - L, T]`` (``T`` incluye las
    ``W`` semanas de calentamiento) y la del calentamiento en ``[T0 - L, T0]``; la oferta de la
    ventana hasta ``w`` queda en ``(rate*(w+1) - L, rate*(w+1) + L)`` con ``L = 240``.
    """
    cells = _cells(rates, list(range(1, n_services + 1)))
    out = session_schedule(cells, LENGTHS, weeks, multiplier, REF)
    assert out == session_schedule(cells, LENGTHS, weeks, multiplier, REF)  # determinista
    length_of: dict[FakeCell, int] = {}
    for week, cell, d in out:
        assert 0 <= week < weeks  # sin sesiones del calentamiento
        assert d in LENGTHS
        assert length_of.setdefault(cell, d) == d  # una duración por celda
        want = session_length(cell.minutes_per_week * multiplier, LENGTHS, REF)
        assert want == d  # solo celdas con oferta posible
    served = {c for c in cells if session_length(c.minutes_per_week * multiplier, LENGTHS, REF)}
    assert set(length_of) <= served
    for svc in {c.service for c in cells}:
        members = [c for c in served if c.service == svc]
        rate = sum(c.minutes_per_week * multiplier for c in members)
        for w in range(weeks):
            offered = sum(d for wk, c, d in out if c.service == svc and wk <= w)
            target = rate * (w + 1)
            assert offered <= target + 240 + 1e-6
            if members:
                assert offered >= target - 240 - 1e-6


@settings(max_examples=40, deadline=None, derandomize=True)
@given(
    rates=st.lists(st.floats(0.5, 300.0), min_size=8, max_size=40),
    weeks=st.integers(10, 30),
)
def test_schedule_has_no_cold_start_ramp(rates: list[float], weeks: int) -> None:
    """Sin rampa: las semanas 0 y 1 no ofrecen menos de 40 % de la mediana de las demás.

    Sin calentamiento, el déficit acumulado partía de cero y las primeras semanas casi no
    tenían sesiones. La cota es holgada (la oferta de un grupo pequeño es granular) y no
    depende de la semilla.
    """
    cells = _cells(rates, [1])
    out = session_schedule(cells, LENGTHS, weeks, 1.0, REF)
    per_week = [0] * weeks
    for wk, _, d in out:
        per_week[wk] += d
    rate = sum(r for r in rates if session_length(r, LENGTHS, REF))
    if rate * 8 < 3 * 240:  # menos de unas pocas sesiones en 8 semanas: demasiado granular
        return
    mid = sorted(per_week[3:])[len(per_week[3:]) // 2]
    # Con tamaños chicos la mediana puede ser 0; comparar con la meta de 2 semanas.
    assert per_week[0] + per_week[1] >= 0.4 * 2 * min(mid, rate) - 240


def test_schedule_monotone_in_multiplier_and_empty_cases() -> None:
    """Más multiplicador no ofrece menos minutos; entradas vacías dan lista vacía."""
    cells = _cells([5.0, 12.0, 0.5, 40.0], [1])
    assert session_schedule([], LENGTHS, 10, 1.0) == []
    assert session_schedule(cells, LENGTHS, 0, 1.0) == []
    low = sum(d for _, _, d in session_schedule(cells, LENGTHS, 26, 1.0))
    high = sum(d for _, _, d in session_schedule(cells, LENGTHS, 26, 2.0))
    assert high >= low


def test_generated_supply_durations_and_coverage(make_dataset) -> None:  # type: ignore[no-untyped-def]
    """Duraciones válidas y múltiplos de ``unit_min``; metas de cobertura de P18 (N 10.000)."""
    ds = make_dataset(10_000, 42)
    slot, res = ds.tables["slot"], ds.tables["resource"]
    s = slot.join(
        res.select(pl.col("id").alias("resource_id"), "kind", "health_service_code"),
        on="resource_id",
    )
    cne = s.filter(pl.col("kind") == "specialist_agenda")
    iq = s.filter(pl.col("kind") == "operating_room")
    assert set(cne["duration_min"].unique()) <= set(LENGTHS)
    assert len(cne["duration_min"].unique()) >= 3  # hay sesiones de varias duraciones
    assert set(iq["duration_min"].unique()) == {360}
    assert (cne["duration_min"] % cne["unit_min"] == 0).all()
    # Una agenda nunca tiene dos sesiones que se traslapen (mismo inicio ni mismo medio día).
    assert cne.group_by("resource_id", "start_at").len()["len"].max() == 1
    # Con calentamiento, medido: 91,7 % CNE y ~89 % pabellón; pisos con holgura.
    entry = ds.tables["waitlist_entry"].filter(pl.col("status") == "waiting")
    for sub, care, floor_stock in ((cne, "consultation", 0.90), (iq, "surgery", 0.88)):
        have = set(zip(sub["health_service_code"], sub["specialty_code"], strict=True))
        e = entry.filter(pl.col("care_type") == care)
        keys = list(zip(e["health_service_code"], e["specialty_code"], strict=True))
        share = sum(k in have for k in keys) / len(keys)
        assert share >= floor_stock, (care, share)


def test_generated_supply_per_group_never_exceeds_target(
    make_dataset, targets, assumptions
) -> None:  # type: ignore[no-untyped-def]
    """C8 con calentamiento: minutos por semana de cada grupo a menos de una sesión larga/H."""
    from shared.db.enums import NoShowScenario
    from synthetic.capacity import capacity_targets
    from synthetic.config import RunConfig

    ds = make_dataset(10_000, 42)
    cfg = RunConfig(size=10_000, seed=42, scenario=NoShowScenario("baseline"))
    cap = capacity_targets(targets, assumptions, cfg, ds.tables["waitlist_entry"])
    res = ds.tables["resource"].select(
        pl.col("id").alias("resource_id"), "kind", "health_service_code"
    )
    slot = (
        ds.tables["slot"]
        .join(res, on="resource_id")
        .with_columns(
            pl.when(pl.col("kind") == "operating_room")
            .then(pl.lit("surgery"))
            .otherwise(pl.lit("consultation"))
            .alias("care_type")
        )
    )
    got = {
        (r[0], r[1]): r[2] / 26
        for r in slot.group_by("health_service_code", "care_type")
        .agg(pl.col("duration_min").sum())
        .iter_rows()
    }
    for r in cap.iter_rows(named=True):
        g = got.get((r["health_service_code"], r["care_type"]), 0.0)
        assert g <= r["target_min_per_week"] + r["session_min"] / 26 + 1e-9
        assert r["target_min_per_week"] - g <= r["session_min"] / 26 + 1e-9
