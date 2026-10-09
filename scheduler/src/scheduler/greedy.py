"""Políticas de referencia ``fifo`` y ``priority`` (formulación §10).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Sin CP-SAT y sin sobrecupo: cada entrada, en orden, toma el primer bloque compatible por
``(local_date, start_at, slot_id)`` con capacidad residual y sin otra cita del paciente ese día.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date
from typing import Literal

from scheduler.prepare import Prepared

Order = Literal["fifo", "priority"]


def order_key(prep: Prepared, order: Order, i: int) -> tuple[object, ...]:
    """Clave de orden de la entrada ``i``.

    ``priority``: puesto P4 dentro de su cola; entre colas, por puesto y luego por cola, de modo
    que las colas avanzan a la par (solo compiten por el día del paciente, R4).
    ``fifo``: fecha de ingreso.
    """
    e = prep.entry(i)
    if order == "fifo":
        return (e.entry_date, e.entry_id)
    return (e.rank, prep.queue[i], e.entry_id)


def greedy_assign(
    prep: Prepared,
    entries: Iterable[int],
    order: Order,
    allowed: Collection[int] | None = None,
) -> frozenset[int]:
    """Pares elegidos por la política voraz sobre ``entries`` (solo pares de ``allowed``)."""
    used: dict[int, int] = {}
    busy: set[tuple[str, date]] = set()
    chosen: list[int] = []
    for i in sorted(entries, key=lambda i: order_key(prep, order, i)):
        patient = prep.entry(i).patient_id
        for pid in prep.pairs_of_entry.get(i, []):
            if allowed is not None and pid not in allowed:
                continue
            bi = prep.pair_block[pid]
            day = prep.block(bi).local_date
            load = prep.pair_load(pid)
            if (patient, day) in busy or used.get(bi, 0) + load > prep.capacity[bi]:
                continue
            used[bi] = used.get(bi, 0) + load
            busy.add((patient, day))
            chosen.append(pid)
            break
    return frozenset(chosen)
