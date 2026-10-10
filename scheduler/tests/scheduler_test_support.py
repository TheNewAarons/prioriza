"""Constructores de instancias sintéticas pequeñas para los tests del programador.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
from shared.db.enums import ClinicalPriority

from priority import PriorityInput, load_default_rules, rank
from scheduler import SchedulingInstance

AS_OF = date(2025, 9, 30)
HORIZON_START = date(2025, 10, 6)
CNE_SPEC = "cne_medical:x"
IQ_SPEC = "iq:y"


@dataclass(frozen=True)
class E:
    """Entrada de prueba."""

    entry_id: str
    priority: str
    entry_date: date
    deadline: date | None = None
    patient_id: str | None = None
    specialty: str = CNE_SPEC
    duration: int = 20
    service: int = 1
    groups: dict[str, str] | None = None


@dataclass(frozen=True)
class B:
    """Bloque de prueba (``start`` en UTC)."""

    slot_id: str
    start: datetime
    duration: int = 40
    specialty: str = CNE_SPEC
    unit: int | None = 20
    service: int = 1
    resource_id: str | None = None
    prebooked: int = 0  # unidades (CNE) o minutos (pabellón) ya tomados


def utc(y: int, m: int, d: int, h: int = 11, mi: int = 30) -> datetime:
    """Fecha y hora en UTC (11:30 UTC = 08:30 en Santiago en octubre de 2025)."""
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def build_instance(
    entries: Sequence[E],
    blocks: Sequence[B],
    probs: dict[tuple[str, str], float] | dict[str, float] | None = None,
    *,
    as_of: date = AS_OF,
    horizon_start: date = HORIZON_START,
    seed: int = 42,
    busy: Sequence[tuple[str, date]] | None = None,
) -> SchedulingInstance:
    """Instancia con puntaje y puesto P4 reales (reglas por defecto).

    ``busy``: pares (paciente, fecha local) con una cita ya confirmada en el horizonte.
    """
    rules = load_default_rules()
    ranking = rank(
        [
            PriorityInput(
                entry_id=e.entry_id,
                clinical_priority=ClinicalPriority(e.priority),
                entry_date=e.entry_date,
                ges_deadline=e.deadline,
            )
            for e in entries
        ],
        rules,
        as_of=as_of,
    )
    rows: list[dict[str, Any]] = []
    for e in entries:
        r = ranking.get(e.entry_id)
        rows.append(
            {
                "entry_id": e.entry_id,
                "patient_id": e.patient_id or f"pat_{e.entry_id}",
                "health_service_code": e.service,
                "establishment_code": f"H{e.service}",
                "specialty_code": e.specialty,
                "care_type": "surgery" if e.specialty.startswith("iq:") else "consultation",
                "duration_min": e.duration,
                "clinical_priority": e.priority,
                "is_ges": e.deadline is not None,
                "ges_deadline": e.deadline,
                "entry_date": e.entry_date,
                "score": r.score.score,
                "rank": r.rank,
            }
        )
    block_rows = [
        {
            "slot_id": b.slot_id,
            "resource_id": b.resource_id or f"R_{b.slot_id}",
            "resource_kind": "operating_room" if b.unit is None else "specialist_agenda",
            "health_service_code": b.service,
            "establishment_code": f"H{b.service}",
            "specialty_code": b.specialty,
            "start_at": b.start,
            "duration_min": b.duration,
            "unit_min": b.unit,
            "prebooked_units": b.prebooked if b.unit is not None else 0,
            "prebooked_min": b.prebooked if b.unit is None else 0,
        }
        for b in blocks
    ]
    noshow_rows: list[dict[str, Any]] = []
    if probs is not None:
        for e in entries:
            for b in blocks:
                if b.unit is None:
                    continue
                key_pair = (e.entry_id, b.slot_id)
                p = probs.get(key_pair, probs.get(e.entry_id))  # type: ignore[call-overload]
                if p is not None:
                    noshow_rows.append({"entry_id": e.entry_id, "slot_id": b.slot_id, "p": p})
    groups = [
        {"patient_id": e.patient_id or f"pat_{e.entry_id}", **e.groups} for e in entries if e.groups
    ]
    return SchedulingInstance.from_frames(
        as_of=as_of,
        horizon_start=horizon_start,
        entries=pl.DataFrame(rows),
        blocks=pl.DataFrame(block_rows, schema_overrides={"unit_min": pl.Int64}),
        noshow=pl.DataFrame(noshow_rows) if noshow_rows else None,
        groups=pl.DataFrame(groups) if groups else None,
        rules_digest=rules.digest(),
        rules_version=rules.rules_version,
        yield_priorities=[str(p) for p in rules.ges_strict.yield_to_priorities],
        seed=seed,
        busy=None
        if busy is None
        else pl.DataFrame(
            list(busy), schema={"patient_id": pl.String, "local_date": pl.Date}, orient="row"
        ),
    )


# Ejemplo resuelto a mano de la formulación (§13).
EXAMPLE_P = {"A": 0.10, "C": 0.45, "D": 0.08, "E": 0.10, "F": 0.50}


def example_entries(e_deadline: date = date(2025, 10, 25), groups: bool = False) -> list[E]:
    """Entradas A, C, D, E, F del ejemplo (puntajes de ``docs/priority.md``)."""

    def g(age: str) -> dict[str, str] | None:
        return {"age_group": age} if groups else None

    return [
        E("A", "p1", date(2025, 8, 31), groups=g("45_64")),
        E("C", "p4", date(2021, 8, 22), groups=g("65_plus")),
        E("D", "p3", date(2025, 6, 2), date(2025, 9, 20), groups=g("45_64")),
        E("E", "p2", date(2025, 9, 10), e_deadline, groups=g("45_64")),
        E("F", "p4", date(2025, 6, 22), groups=g("65_plus")),
    ]


def example_blocks() -> list[B]:
    """B1 (martes 2025-10-07 08:30) y B2 (martes 2025-10-14 08:30), 2 cupos de 20 min."""
    return [
        B("B1", utc(2025, 10, 7), resource_id="R1"),
        B("B2", utc(2025, 10, 14), resource_id="R1"),
    ]


def example_instance(
    e_deadline: date = date(2025, 10, 25), groups: bool = False
) -> SchedulingInstance:
    """Instancia del ejemplo §13."""
    return build_instance(example_entries(e_deadline, groups), example_blocks(), EXAMPLE_P)


def plan_map(plan: Any) -> dict[str, set[str]]:
    """Bloque -> conjunto de entradas del plan."""
    out: dict[str, set[str]] = {}
    for slot, entry in plan.assignments.select("slot_id", "entry_id").iter_rows():
        out.setdefault(slot, set()).add(entry)
    return out
