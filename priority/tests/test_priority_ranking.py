"""Tests de orden, desempates e invariantes I1-I3 con los pesos por defecto."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import timedelta

import pytest
from priority.inputs import PriorityInput
from priority.rules import RuleSet
from priority.score import StrictTier, rank, score_entry, sort_key
from priority_test_support import AS_OF, make_input
from shared.db.enums import ClinicalPriority


def _ids(rules: RuleSet, inputs: list[PriorityInput]) -> list[str]:
    return [e.score.entry_id for e in rank(inputs, rules, as_of=AS_OF).entries]


# ---------------------------------------------------------------- desempates


def test_same_score_older_entry_date_first(default_rules: RuleSet) -> None:
    # Ambas saturadas (>= 730 días): puntaje idéntico, gana la fecha más antigua.
    older = make_input("z-id", "p3", 2000)
    newer = make_input("a-id", "p3", 900)
    s1 = score_entry(older, default_rules, as_of=AS_OF).score
    s2 = score_entry(newer, default_rules, as_of=AS_OF).score
    assert s1 == s2
    assert _ids(default_rules, [newer, older]) == ["z-id", "a-id"]
    assert _ids(default_rules, [older, newer]) == ["z-id", "a-id"]


def test_same_date_smaller_entry_id_first(default_rules: RuleSet) -> None:
    a = make_input("00000000-0000-0000-0000-000000000001", "p2", 50)
    b = make_input("00000000-0000-0000-0000-000000000002", "p2", 50)
    c = make_input("ffffffff-0000-0000-0000-000000000000", "p2", 50)
    for perm in itertools.permutations([a, b, c]):
        assert _ids(default_rules, list(perm)) == [a.entry_id, b.entry_id, c.entry_id]


def test_equal_score_different_priority_levels_tie_by_date(default_rules: RuleSet) -> None:
    # p2 con 365 días más de espera iguala exactamente a p3 (30,0 vs 12,5 + 17,5).
    p2 = make_input("p2", "p2", 10)
    p3 = make_input("p3", "p3", 10 + 365)
    assert (
        score_entry(p2, default_rules, as_of=AS_OF).score
        == score_entry(p3, default_rules, as_of=AS_OF).score
    )
    # Mismo puntaje: va primero la fecha de ingreso más antigua (p3).
    assert _ids(default_rules, [p2, p3]) == ["p3", "p2"]


def test_ranking_invariant_to_input_order(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    expected = rank(golden_inputs, default_rules, as_of=AS_OF)
    for perm in itertools.permutations(golden_inputs):
        assert rank(list(perm), default_rules, as_of=AS_OF).entries == expected.entries


def test_duplicate_entry_id_raises(default_rules: RuleSet) -> None:
    with pytest.raises(ValueError, match=r"dup|repet"):
        rank([make_input("x", "p1", 1), make_input("x", "p2", 2)], default_rules, as_of=AS_OF)


def test_get_unknown_entry_raises(default_rules: RuleSet) -> None:
    r = rank([make_input("x", "p1", 1)], default_rules, as_of=AS_OF)
    assert r.get("x").rank == 1
    with pytest.raises((KeyError, ValueError)):
        r.get("nope")


def test_sort_key_is_total_and_consistent_with_rank(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    by_id = {i.entry_id: i for i in golden_inputs}
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    keys = [sort_key(e.score, by_id[e.score.entry_id], default_rules) for e in r.entries]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


# ------------------------------------------------------------- order_within


def _two_overdue(rules: RuleSet) -> list[str]:
    # X: p4, muy atrasada (puntaje bajo). Y: p2, poco atrasada (puntaje alto).
    x = make_input("X", "p4", 200, deadline_in=-100)
    y = make_input("Y", "p2", 200, deadline_in=-5)
    return _ids(rules, [y, x])


def test_order_within_deadline_is_edf(build_rules: Callable[..., RuleSet]) -> None:
    assert _two_overdue(build_rules(yield_to_priorities=[], order_within="deadline")) == [
        "X",
        "Y",
    ]


def test_order_within_score(build_rules: Callable[..., RuleSet]) -> None:
    assert _two_overdue(build_rules(yield_to_priorities=[], order_within="score")) == ["Y", "X"]


def test_overdue_before_due_soon_even_with_lower_score(
    build_rules: Callable[..., RuleSet],
) -> None:
    rules = build_rules(yield_to_priorities=[], order_within="score")
    overdue = make_input("over", "p4", 1, deadline_in=-1)
    soon = make_input("soon", "p2", 600, deadline_in=0)
    assert _ids(rules, [soon, overdue]) == ["over", "soon"]


def test_ties_inside_strict_tier_use_score_then_date(
    build_rules: Callable[..., RuleSet],
) -> None:
    rules = build_rules(yield_to_priorities=[])
    a = make_input("a", "p3", 100, deadline_in=-5)
    b = make_input("b", "p2", 100, deadline_in=-5)  # mismo plazo, mayor puntaje
    assert _ids(rules, [a, b]) == ["b", "a"]


# ------------------------------------------------------------ yield_to_priorities


def test_yield_p1_goes_before_everything(default_rules: RuleSet) -> None:
    p1_plain = make_input("p1-plain", "p1", 0)
    overdue_p2 = make_input("p2-over", "p2", 3000, deadline_in=-400)
    assert _ids(default_rules, [overdue_p2, p1_plain]) == ["p1-plain", "p2-over"]


def test_yield_group_internal_order(default_rules: RuleSet) -> None:
    # Dentro de p1: vencida, por vencer, resto (mismo orden de la sección 1).
    plain = make_input("plain", "p1", 2000)
    soon = make_input("soon", "p1", 1, deadline_in=3)
    over = make_input("over", "p1", 1, deadline_in=-1)
    assert _ids(default_rules, [plain, soon, over]) == ["over", "soon", "plain"]


def test_yield_then_strict_then_rest(default_rules: RuleSet) -> None:
    items = [
        make_input("rest", "p2", 700),
        make_input("soon", "p4", 5, deadline_in=14),
        make_input("over", "p3", 5, deadline_in=-1),
        make_input("p1", "p1", 0),
    ]
    assert _ids(default_rules, items) == ["p1", "over", "soon", "rest"]


def test_yield_multiple_priorities(build_rules: Callable[..., RuleSet]) -> None:
    rules = build_rules(yield_to_priorities=["p1", "p2"])
    items = [
        make_input("over-p3", "p3", 5, deadline_in=-1),
        make_input("p2", "p2", 0),
        make_input("p1", "p1", 0),
    ]
    assert _ids(rules, items) == ["p1", "p2", "over-p3"]


def test_strict_disabled_with_empty_yield_orders_by_score(
    build_rules: Callable[..., RuleSet], golden_inputs: list[PriorityInput]
) -> None:
    rules = build_rules(enabled=False, yield_to_priorities=[])
    assert _ids(rules, golden_inputs) == ["A", "B", "E", "C", "D"]


# ------------------------------------------------------------- invariantes I1-I3


def _score(rules: RuleSet, prio: str, wait: int, deadline_in: int | None = None) -> float:
    return score_entry(
        make_input("x", prio, wait, deadline_in=deadline_in), rules, as_of=AS_OF
    ).score


@pytest.mark.parametrize("low", ["p3", "p4"])
def test_i1_wait_alone_never_lifts_p3_p4_above_p1(default_rules: RuleSet, low: str) -> None:
    assert _score(default_rules, low, 3650) < _score(default_rules, "p1", 0)
    top = make_input("low", low, 3650)
    base = make_input("p1", "p1", 0)
    assert _ids(default_rules, [top, base]) == ["p1", "low"]


@pytest.mark.parametrize(
    ("better", "worse", "days_needed"),
    [("p1", "p2", 418), ("p2", "p3", 365), ("p3", "p4", 261)],
)
def test_i2_adjacent_level_can_be_overcome_with_extra_wait(
    build_rules: Callable[..., RuleSet], better: str, worse: str, days_needed: int
) -> None:
    # Sin cesión de p1: aquí se prueba solo el puntaje (la cesión es una regla de orden aparte).
    default_rules = build_rules(yield_to_priorities=[])
    base = 10
    top = make_input("top", better, base)
    # Un día menos de lo necesario: el nivel superior sigue adelante.
    short = make_input("worse", worse, base + days_needed - 1)
    assert _ids(default_rules, [short, top]) == ["top", "worse"]
    # Con los días necesarios la espera compensa (p2-p3: empate exacto, gana la fecha).
    enough = make_input("worse", worse, base + days_needed)
    assert _ids(default_rules, [top, enough]) == ["worse", "top"]


def test_i2_p2_over_p1_needs_about_417_days(default_rules: RuleSet) -> None:
    # 417 días aún no alcanzan (49,993 < 50); 418 sí.
    assert _score(default_rules, "p2", 417) < _score(default_rules, "p1", 0)
    assert _score(default_rules, "p2", 418) > _score(default_rules, "p1", 0)


def test_i3_soft_ges_component_is_at_most_15_points(default_rules: RuleSet) -> None:
    max_ges = _score(default_rules, "p4", 0, deadline_in=0)
    assert max_ges == pytest.approx(15.0, abs=1e-6)
    jumps = {
        "p1-p2": _score(default_rules, "p1", 0) - _score(default_rules, "p2", 0),
        "p2-p3": _score(default_rules, "p2", 0) - _score(default_rules, "p3", 0),
        "p3-p4": _score(default_rules, "p3", 0) - _score(default_rules, "p4", 0),
    }
    assert jumps["p1-p2"] == pytest.approx(20.0, abs=1e-6)
    assert jumps["p2-p3"] == pytest.approx(17.5, abs=1e-6)
    assert jumps["p3-p4"] == pytest.approx(12.5, abs=1e-6)
    assert max_ges < jumps["p1-p2"]
    assert max_ges < jumps["p2-p3"]
    assert max_ges > jumps["p3-p4"]


def test_default_weights_sum_to_100(default_rules: RuleSet) -> None:
    s = score_entry(make_input("x", "p1", 730, deadline_in=0), default_rules, as_of=AS_OF)
    assert s.score == pytest.approx(100.0, abs=1e-6)
    assert [c.effective_weight for c in s.components] == pytest.approx([50, 35, 15])


def test_priority_enum_roundtrip() -> None:
    assert {p.value for p in ClinicalPriority} == {"p1", "p2", "p3", "p4"}
    assert StrictTier.GES_OVERDUE > StrictTier.GES_DUE_SOON
    assert timedelta(days=1).days == 1
