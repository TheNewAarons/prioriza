"""Adaptadores entre el cálculo de prioridad y el ORM / DataFrames de polars.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La partición (servicio, especialidad, tipo de atención) define la cola en la que compite cada
entrada; nunca cambia el puntaje.
"""

from collections.abc import Sequence
from datetime import date

import polars as pl
from shared.db.enums import ClinicalPriority, EntryStatus
from shared.db.models import WaitlistEntry

from priority.inputs import PriorityInput
from priority.rules import RuleSet
from priority.score import Ranking, rank

_REQUIRED = ("id", "clinical_priority", "entry_date", "ges_deadline")


def from_waitlist_entry(e: WaitlistEntry) -> PriorityInput:
    """Convierte una entrada ORM; ``ValueError`` si no está en estado ``waiting``."""
    if e.status != EntryStatus.WAITING:
        raise ValueError(
            f"la entrada {e.id} está en estado '{EntryStatus(e.status).value}'; "
            "solo se priorizan entradas en espera"
        )
    return PriorityInput(
        entry_id=str(e.id),
        clinical_priority=ClinicalPriority(e.clinical_priority),
        entry_date=e.entry_date,
        ges_deadline=e.ges_deadline,
    )


def _check_status(df: pl.DataFrame) -> None:
    if "status" not in df.columns:
        return
    bad = df.filter(
        pl.col("status").is_null() | (pl.col("status").cast(pl.String) != EntryStatus.WAITING.value)
    )
    if bad.height:
        raise ValueError(
            f"{bad.height} entradas no están en estado 'waiting'; "
            "solo se priorizan entradas en espera"
        )


def _convert(df: pl.DataFrame) -> list[PriorityInput]:
    """Convierte todas las filas; junta las inválidas en un solo ``ValueError``."""
    out: list[PriorityInput] = []
    bad: list[str] = []
    for i, p, ed, gd in df.select(_REQUIRED).iter_rows():
        try:
            out.append(
                PriorityInput(
                    entry_id=str(i),
                    clinical_priority=ClinicalPriority(p),
                    entry_date=ed,
                    ges_deadline=gd,
                )
            )
        except (ValueError, TypeError):
            bad.append(str(i))
    if bad:
        raise ValueError(
            f"{len(bad)} filas inválidas (ids de ejemplo: {', '.join(bad[:10])}); "
            "revisa prioridad clínica y fechas de ingreso y plazo GES"
        )
    return out


def inputs_from_frame(df: pl.DataFrame) -> list[PriorityInput]:
    """Convierte un DataFrame a entradas; solo lee id, prioridad, ingreso y plazo (y status)."""
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas requeridas: {missing}")
    _check_status(df)
    return _convert(df)


def rank_frame(
    df: pl.DataFrame,
    rules: RuleSet,
    *,
    as_of: date,
    partition_by: Sequence[str] = ("health_service_code", "specialty_code", "care_type"),
) -> dict[tuple[object, ...], Ranking]:
    """Ordena cada cola (partición) por separado; la clave es la tupla de valores."""
    missing = [c for c in partition_by if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas de partición: {missing}")
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas requeridas: {missing}")
    _check_status(df)
    inputs = _convert(df)
    if not partition_by:
        return {(): rank(inputs, rules, as_of=as_of)}
    idx = df.select(list(partition_by)).with_row_index("__row")
    parts = idx.partition_by(list(partition_by), as_dict=True, maintain_order=True)
    return {
        tuple(key): rank([inputs[j] for j in sub["__row"].to_list()], rules, as_of=as_of)
        for key, sub in parts.items()
    }
