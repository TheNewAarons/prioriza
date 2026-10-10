"""Instancia del programador: entradas, bloques, inasistencia y grupos (formulación §2).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

El núcleo solo recibe ``polars.DataFrame``; no lee la base de datos ni importa ``noshow``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

LOCAL_TZ = ZoneInfo("America/Santiago")
CONSULTATION = "consultation"
SURGERY = "surgery"
SPECIALIST_AGENDA = "specialist_agenda"
OPERATING_ROOM = "operating_room"
KIND_FOR_CARE = {CONSULTATION: SPECIALIST_AGENDA, SURGERY: OPERATING_ROOM}

ENTRY_COLUMNS = (
    "entry_id",
    "patient_id",
    "health_service_code",
    "establishment_code",
    "specialty_code",
    "care_type",
    "duration_min",
    "clinical_priority",
    "is_ges",
    "ges_deadline",
    "entry_date",
    "score",
    "rank",
)
BLOCK_COLUMNS = (
    "slot_id",
    "resource_id",
    "resource_kind",
    "health_service_code",
    "establishment_code",
    "specialty_code",
    "start_at",
    "duration_min",
    "unit_min",
)
NOSHOW_COLUMNS = ("entry_id", "slot_id", "p")
GROUP_COLUMNS = ("patient_id", "age_group", "insurance", "commune_code")
BUSY_COLUMNS = ("patient_id", "local_date")


@dataclass(frozen=True, slots=True)
class Entry:
    """Entrada en espera con su puntaje P4 (S y puesto en la cola)."""

    entry_id: str
    patient_id: str
    health_service_code: int
    establishment_code: str
    specialty_code: str
    care_type: str
    duration_min: int
    clinical_priority: str
    is_ges: bool
    ges_deadline: date | None
    entry_date: date
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class Block:
    """Bloque programable (un ``slot``): sesión CNE o bloque de pabellón."""

    slot_id: str
    resource_id: str
    resource_kind: str
    health_service_code: int
    establishment_code: str
    specialty_code: str
    start_at: datetime
    duration_min: int
    unit_min: int | None
    prebooked_units: int = 0
    prebooked_min: int = 0

    @property
    def local_date(self) -> date:
        """Fecha local (America/Santiago) del inicio del bloque."""
        return self.start_at.astimezone(LOCAL_TZ).date()

    @property
    def is_cne(self) -> bool:
        """Verdadero si es una sesión CNE (agenda de especialista)."""
        return self.resource_kind == SPECIALIST_AGENDA


@dataclass(frozen=True)
class SchedulingInstance:
    """Datos de entrada de una corrida del programador."""

    as_of: date
    horizon_start: date
    entries: tuple[Entry, ...]
    blocks: tuple[Block, ...]
    noshow: Mapping[tuple[str, str], float]
    groups: Mapping[str, Mapping[str, str]]
    rules_digest: str
    rules_version: str
    yield_priorities: tuple[str, ...] = ("p1",)
    noshow_model_version: str | None = None
    seed: int = 42
    # (paciente, fecha local) con una cita ya confirmada en el horizonte (citas congeladas de una
    # planificación anterior o ``scheduled`` previas): R4 con lado derecho 1 - busy (§4).
    busy_patient_days: frozenset[tuple[str, date]] = frozenset()
    _entry_index: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Valida identificadores únicos y valores básicos."""
        index = {e.entry_id: i for i, e in enumerate(self.entries)}
        if len(index) != len(self.entries):
            raise ValueError("entry_id duplicado en entries")
        if len({b.slot_id for b in self.blocks}) != len(self.blocks):
            raise ValueError("slot_id duplicado en blocks")
        for e in self.entries:
            if e.care_type not in KIND_FOR_CARE:
                raise ValueError(f"care_type no programable en {e.entry_id}: {e.care_type!r}")
            if e.duration_min <= 0:
                raise ValueError(f"duration_min no positivo en {e.entry_id}")
            if e.is_ges and e.ges_deadline is None:
                raise ValueError(f"entrada GES sin plazo: {e.entry_id}")
        for b in self.blocks:
            if b.resource_kind not in (SPECIALIST_AGENDA, OPERATING_ROOM):
                raise ValueError(f"resource_kind desconocido en {b.slot_id}: {b.resource_kind!r}")
            if b.start_at.tzinfo is None:
                raise ValueError(f"start_at sin zona horaria en {b.slot_id}")
            if b.is_cne and not b.unit_min:
                raise ValueError(f"sesión CNE sin unit_min en {b.slot_id}")
        for key, p in self.noshow.items():
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"p fuera de [0, 1] en {key}: {p}")
        for item in self.busy_patient_days:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not _is_date(item[1])
            ):
                raise ValueError(f"busy_patient_days espera (patient_id, fecha local): {item!r}")
        object.__setattr__(self, "_entry_index", index)

    def entry(self, entry_id: str) -> Entry:
        """Entrada por id."""
        return self.entries[self._entry_index[entry_id]]

    @classmethod
    def from_frames(
        cls,
        *,
        as_of: date,
        horizon_start: date,
        entries: pl.DataFrame,
        blocks: pl.DataFrame,
        noshow: pl.DataFrame | None = None,
        groups: pl.DataFrame | None = None,
        rules_digest: str,
        rules_version: str,
        yield_priorities: Sequence[str] = ("p1",),
        noshow_model_version: str | None = None,
        seed: int = 42,
        busy: pl.DataFrame | None = None,
    ) -> SchedulingInstance:
        """Construye y valida la instancia desde las tablas de la formulación §2.2.

        ``busy`` (opcional) trae ``patient_id`` y ``local_date`` (fecha local, no ``datetime``) de
        las citas ya confirmadas dentro del horizonte.
        """
        _require(entries, ENTRY_COLUMNS, "entries")
        _require(blocks, BLOCK_COLUMNS, "blocks")
        entry_rows = [
            Entry(
                entry_id=str(r["entry_id"]),
                patient_id=str(r["patient_id"]),
                health_service_code=int(r["health_service_code"]),
                establishment_code=str(r["establishment_code"]),
                specialty_code=str(r["specialty_code"]),
                care_type=str(r["care_type"]),
                duration_min=int(r["duration_min"]),
                clinical_priority=str(r["clinical_priority"]),
                is_ges=bool(r["is_ges"]),
                ges_deadline=r["ges_deadline"],
                entry_date=r["entry_date"],
                score=float(r["score"]),
                rank=int(r["rank"]),
            )
            for r in entries.select(ENTRY_COLUMNS).iter_rows(named=True)
        ]
        pre_units = "prebooked_units" in blocks.columns
        pre_min = "prebooked_min" in blocks.columns
        block_rows = [
            Block(
                slot_id=str(r["slot_id"]),
                resource_id=str(r["resource_id"]),
                resource_kind=str(r["resource_kind"]),
                health_service_code=int(r["health_service_code"]),
                establishment_code=str(r["establishment_code"]),
                specialty_code=str(r["specialty_code"]),
                start_at=_utc(r["start_at"]),
                duration_min=int(r["duration_min"]),
                unit_min=None if r["unit_min"] is None else int(r["unit_min"]),
                prebooked_units=int(r["prebooked_units"] or 0) if pre_units else 0,
                prebooked_min=int(r["prebooked_min"] or 0) if pre_min else 0,
            )
            for r in blocks.iter_rows(named=True)
        ]
        p_map: dict[tuple[str, str], float] = {}
        if noshow is not None:
            _require(noshow, NOSHOW_COLUMNS, "noshow")
            for e_id, s_id, p in noshow.select(NOSHOW_COLUMNS).iter_rows():
                p_map[(str(e_id), str(s_id))] = float(p)
        g_map: dict[str, dict[str, str]] = {}
        if groups is not None:
            _require(groups, ("patient_id",), "groups")
            dims = [c for c in GROUP_COLUMNS[1:] if c in groups.columns]
            for r in groups.iter_rows(named=True):
                g_map[str(r["patient_id"])] = {d: str(r[d]) for d in dims}
        busy_set: set[tuple[str, date]] = set()
        if busy is not None:
            _require(busy, BUSY_COLUMNS, "busy")
            for pid, day in busy.select(BUSY_COLUMNS).iter_rows():
                if not _is_date(day):
                    raise ValueError(
                        f"busy.local_date debe ser una fecha (date), no {type(day).__name__}"
                    )
                busy_set.add((str(pid), day))
        return cls(
            as_of=as_of,
            horizon_start=horizon_start,
            entries=tuple(entry_rows),
            blocks=tuple(block_rows),
            noshow=p_map,
            groups=g_map,
            rules_digest=rules_digest,
            rules_version=rules_version,
            yield_priorities=tuple(yield_priorities),
            noshow_model_version=noshow_model_version,
            seed=seed,
            busy_patient_days=frozenset(busy_set),
        )


def _require(df: pl.DataFrame, cols: Sequence[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas en {name}: {missing}")


def _is_date(value: Any) -> bool:
    """Fecha sin hora (``datetime`` es subclase de ``date`` y se rechaza)."""
    return isinstance(value, date) and not isinstance(value, datetime)


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"start_at debe ser datetime, no {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError("start_at debe tener zona horaria (UTC)")
    return value
