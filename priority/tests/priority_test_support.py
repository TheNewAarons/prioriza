"""Utilidades compartidas de los tests de priority (100% sintéticas, sin red ni DB)."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

import yaml
from priority.inputs import PriorityInput
from shared.db.enums import ClinicalPriority

AS_OF = date(2025, 9, 30)

# Copia independiente de las reglas por defecto de docs/design/priority-plan.md §2 y §8.
DEFAULT_RULES_DICT: dict[str, Any] = {
    "schema_version": 1,
    "rules_id": "test-default",
    "rules_version": "test-1",
    "description": "Reglas de prueba equivalentes a las por defecto.",
    "components": [
        {
            "field": "clinical_priority",
            "label": "Prioridad clínica declarada",
            "weight": 50,
            "mapping": {"p1": 1.0, "p2": 0.6, "p3": 0.25, "p4": 0.0},
        },
        {
            "field": "wait_days",
            "label": "Días de espera",
            "weight": 35,
            "transform": {"type": "linear_saturated", "saturation_days": 730},
        },
        {
            "field": "days_to_ges_deadline",
            "label": "Cercanía al plazo GES",
            "weight": 15,
            "transform": {"type": "ramp_down", "start_days": 60, "end_days": 0},
        },
    ],
    "ges_strict": {
        "enabled": True,
        "due_soon_days": 14,
        "order_within": "deadline",
        "yield_to_priorities": ["p1"],
    },
}


def rules_dict(**strict: Any) -> dict[str, Any]:
    """Copia del dict por defecto con ``ges_strict`` sobreescrito."""
    d = copy.deepcopy(DEFAULT_RULES_DICT)
    if strict.get("enabled") is False and "yield_to_priorities" not in strict:
        # Con la regla desactivada, una cesión no vacía es un error de validación (M1).
        d["ges_strict"]["yield_to_priorities"] = []
    d["ges_strict"].update(strict)
    return d


def dump(d: dict[str, Any]) -> str:
    """Serializa un dict a YAML."""
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True)


def make_input(
    entry_id: str,
    prio: str,
    wait: int,
    *,
    deadline_in: int | None = None,
    as_of: date = AS_OF,
) -> PriorityInput:
    """Entrada sintética con ``wait`` días de espera y plazo GES a ``deadline_in`` días."""
    return PriorityInput(
        entry_id=entry_id,
        clinical_priority=ClinicalPriority(prio),
        entry_date=as_of - timedelta(days=wait),
        ges_deadline=None if deadline_in is None else as_of + timedelta(days=deadline_in),
    )
