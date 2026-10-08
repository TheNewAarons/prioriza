"""Fixtures compartidas de los tests de priority (100% sintéticas, sin red ni base de datos)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

# Con --import-mode=importlib el directorio de tests no está en sys.path.
sys.path.insert(0, str(Path(__file__).parent))

from priority.inputs import PriorityInput
from priority.rules import RuleSet, parse_rules
from priority_test_support import (
    AS_OF,
    DEFAULT_RULES_DICT,
    dump,
    make_input,
    rules_dict,
)


@pytest.fixture(scope="session")
def as_of() -> date:
    """Fecha de corte fija."""
    return AS_OF


@pytest.fixture(scope="session")
def default_rules() -> RuleSet:
    """Reglas por defecto (yield_to_priorities: [p1])."""
    return parse_rules(dump(DEFAULT_RULES_DICT))


@pytest.fixture
def build_rules() -> Callable[..., RuleSet]:
    """Fábrica de RuleSet con ``ges_strict`` sobreescrito."""

    def _build(**strict: Any) -> RuleSet:
        return parse_rules(dump(rules_dict(**strict)))

    return _build


@pytest.fixture(scope="session")
def golden_inputs() -> list[PriorityInput]:
    """Entradas A-E de la sección 1 del plan."""
    return [
        make_input("A", "p1", 30),
        make_input("B", "p2", 400),
        make_input("C", "p4", 1500),
        make_input("D", "p3", 120, deadline_in=-10),
        make_input("E", "p2", 20, deadline_in=25),
    ]
