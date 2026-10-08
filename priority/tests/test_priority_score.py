"""Tests de puntaje, nivel estricto GES y test dorado A-E (priority.score)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from typing import Any

import pytest
from priority.inputs import PriorityInput
from priority.rules import RuleSet, parse_rules
from priority.score import (
    PriorityScore,
    StrictTier,
    rank,
    score_entry,
    strict_tier,
)
from priority_test_support import AS_OF, dump, make_input, rules_dict
from shared.db.enums import ClinicalPriority


def _component(s: PriorityScore, field: str) -> Any:
    return next(c for c in s.components if c.field == field)


def _wait_rules(transform: dict[str, Any]) -> RuleSet:
    d = rules_dict()
    d["components"][1]["transform"] = transform
    return parse_rules(dump(d))


# -------------------------------------------------------------- firmas / as_of


@pytest.mark.parametrize("fn", [rank, score_entry])
def test_as_of_is_keyword_only_without_default(fn: Callable[..., Any]) -> None:
    p = inspect.signature(fn).parameters["as_of"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is inspect.Parameter.empty


def test_future_entry_date_raises(default_rules: RuleSet) -> None:
    inp = PriorityInput("x", ClinicalPriority.P1, AS_OF + timedelta(days=1))
    with pytest.raises(ValueError, match=r".+"):
        score_entry(inp, default_rules, as_of=AS_OF)
    with pytest.raises(ValueError, match=r".+"):
        rank([inp], default_rules, as_of=AS_OF)


def test_entry_date_equal_as_of_is_valid(default_rules: RuleSet) -> None:
    s = score_entry(make_input("x", "p1", 0), default_rules, as_of=AS_OF)
    assert s.wait_days == 0


def test_priority_input_validation() -> None:
    with pytest.raises(ValueError, match=r".+"):
        PriorityInput("x", ClinicalPriority.P1, date(2025, 5, 2), date(2025, 5, 1))
    with pytest.raises((TypeError, ValueError)):
        PriorityInput("x", "p1", date(2025, 5, 1))  # type: ignore[arg-type]
    ok = PriorityInput("x", ClinicalPriority.P1, date(2025, 5, 1), date(2025, 5, 1))
    assert ok.is_ges is True
    assert PriorityInput("y", ClinicalPriority.P1, date(2025, 5, 1)).is_ges is False


def test_priority_input_is_frozen_and_has_no_sensitive_fields() -> None:
    import dataclasses

    inp = make_input("x", "p1", 1)
    with pytest.raises(FrozenInstanceError):
        inp.clinical_priority = ClinicalPriority.P4  # type: ignore[misc]
    names = {f.name for f in dataclasses.fields(PriorityInput)}
    assert names == {"entry_id", "clinical_priority", "entry_date", "ges_deadline"}


def test_clinical_priority_echoed_unchanged(default_rules: RuleSet) -> None:
    for prio in ("p1", "p2", "p3", "p4"):
        s = score_entry(make_input("x", prio, 100, deadline_in=-3), default_rules, as_of=AS_OF)
        assert s.clinical_priority is ClinicalPriority(prio)
    r = rank([make_input("a", "p4", 5), make_input("b", "p1", 1)], default_rules, as_of=AS_OF)
    assert {e.score.entry_id: e.score.clinical_priority for e in r.entries} == {
        "a": ClinicalPriority.P4,
        "b": ClinicalPriority.P1,
    }


def test_score_fields(default_rules: RuleSet) -> None:
    s = score_entry(make_input("x", "p2", 40, deadline_in=-2), default_rules, as_of=AS_OF)
    assert s.entry_id == "x"
    assert s.as_of == AS_OF
    assert s.wait_days == 40
    assert s.days_to_ges_deadline == -2
    non_ges = score_entry(make_input("y", "p2", 40), default_rules, as_of=AS_OF)
    assert non_ges.days_to_ges_deadline is None
    with pytest.raises(FrozenInstanceError):
        s.score = 0.0  # type: ignore[misc]


# -------------------------------------------------------- clinical_priority


@pytest.mark.parametrize(
    ("prio", "expected"), [("p1", 1.0), ("p2", 0.6), ("p3", 0.25), ("p4", 0.0)]
)
def test_clinical_mapping_steps(default_rules: RuleSet, prio: str, expected: float) -> None:
    s = score_entry(make_input("x", prio, 0), default_rules, as_of=AS_OF)
    c = _component(s, "clinical_priority")
    assert c.normalized == pytest.approx(expected)
    assert c.contribution == pytest.approx(50 * expected)
    assert s.score == pytest.approx(50 * expected, abs=1e-6)


# ----------------------------------------------------------------- wait_days


@pytest.mark.parametrize(
    ("wait", "expected"),
    [(0, 0.0), (1, 1 / 730), (729, 729 / 730), (730, 1.0), (731, 1.0), (3650, 1.0)],
)
def test_wait_linear_saturated_edges(default_rules: RuleSet, wait: int, expected: float) -> None:
    s = score_entry(make_input("x", "p4", wait), default_rules, as_of=AS_OF)
    assert _component(s, "wait_days").normalized == pytest.approx(expected)
    assert s.score == pytest.approx(35 * expected, abs=1e-6)


@pytest.mark.parametrize("wait", [0, 1, 100, 729, 730, 3650])
def test_wait_log_saturated_properties(wait: int) -> None:
    rules = _wait_rules({"type": "log_saturated", "saturation_days": 730})
    s = score_entry(make_input("x", "p4", wait), rules, as_of=AS_OF)
    v = _component(s, "wait_days").normalized
    assert 0.0 <= v <= 1.0
    if wait == 0:
        assert v == pytest.approx(0.0)
    if wait >= 730:
        assert v == pytest.approx(1.0)


def test_wait_log_saturated_is_monotone_and_concave_start() -> None:
    rules = _wait_rules({"type": "log_saturated", "saturation_days": 730})
    vals = [
        _component(
            score_entry(make_input("x", "p4", w), rules, as_of=AS_OF), "wait_days"
        ).normalized
        for w in (0, 1, 10, 100, 365, 729, 730, 1000)
    ]
    assert vals == sorted(vals)
    # Logarítmica: los primeros días valen más que los últimos.
    assert vals[2] - vals[0] > 10 / 730


@pytest.mark.parametrize(
    ("wait", "expected"),
    [(0, 0.0), (29, 0.0), (30, 0.5), (364, 0.5), (365, 1.0), (3650, 1.0)],
)
def test_wait_steps_edges(wait: int, expected: float) -> None:
    rules = _wait_rules(
        {
            "type": "steps",
            "steps": [
                {"at_days": 0, "value": 0.0},
                {"at_days": 30, "value": 0.5},
                {"at_days": 365, "value": 1.0},
            ],
        }
    )
    s = score_entry(make_input("x", "p4", wait), rules, as_of=AS_OF)
    assert _component(s, "wait_days").normalized == pytest.approx(expected)


# ------------------------------------------------------------ days_to_ges_deadline


@pytest.mark.parametrize(
    ("d", "expected"),
    [(61, 0.0), (60, 0.0), (59, 1 / 60), (30, 0.5), (1, 59 / 60), (0, 1.0), (-1, 1.0), (-500, 1.0)],
)
def test_ges_ramp_edges(default_rules: RuleSet, d: int, expected: float) -> None:
    s = score_entry(make_input("x", "p4", 600, deadline_in=d), default_rules, as_of=AS_OF)
    c = _component(s, "days_to_ges_deadline")
    assert c.normalized == pytest.approx(expected)
    assert c.contribution == pytest.approx(15 * expected)


def test_ges_ramp_none_for_non_ges(default_rules: RuleSet) -> None:
    s = score_entry(make_input("x", "p4", 10), default_rules, as_of=AS_OF)
    c = _component(s, "days_to_ges_deadline")
    assert c.normalized == 0.0
    assert c.contribution == 0.0
    assert c.raw_value is None


# ------------------------------------------------------------ pesos normalizados


def test_weights_are_normalized() -> None:
    d = rules_dict()
    for c, w in zip(d["components"], (1, 1, 2), strict=True):
        c["weight"] = w
    rules = parse_rules(dump(d))
    s = score_entry(make_input("x", "p1", 730, deadline_in=0), rules, as_of=AS_OF)
    assert s.score == pytest.approx(100.0, abs=1e-6)
    assert [c.effective_weight for c in s.components] == pytest.approx([25.0, 25.0, 50.0])
    assert [c.weight for c in s.components] == pytest.approx([1.0, 1.0, 2.0])


def test_disabled_component_weight_zero_has_no_effect() -> None:
    d = rules_dict()
    d["components"][1]["weight"] = 0
    rules = parse_rules(dump(d))
    a = score_entry(make_input("x", "p2", 0), rules, as_of=AS_OF)
    b = score_entry(make_input("x", "p2", 3000), rules, as_of=AS_OF)
    assert a.score == pytest.approx(b.score)


# ------------------------------------------------------------ nivel estricto


@pytest.mark.parametrize(
    ("d", "tier"),
    [
        (None, StrictTier.NONE),
        (-100, StrictTier.GES_OVERDUE),
        (-1, StrictTier.GES_OVERDUE),
        (0, StrictTier.GES_DUE_SOON),
        (1, StrictTier.GES_DUE_SOON),
        (14, StrictTier.GES_DUE_SOON),
        (15, StrictTier.NONE),
        (500, StrictTier.NONE),
    ],
)
def test_strict_tier_edges(default_rules: RuleSet, d: int | None, tier: StrictTier) -> None:
    assert strict_tier(d, default_rules.ges_strict) is tier


def test_strict_tier_disabled_is_always_none(build_rules: Callable[..., RuleSet]) -> None:
    rules = build_rules(enabled=False)
    for d in (None, -1, 0, 14, 15):
        assert strict_tier(d, rules.ges_strict) is StrictTier.NONE
    s = score_entry(make_input("x", "p4", 50, deadline_in=-10), rules, as_of=AS_OF)
    assert s.tier is StrictTier.NONE


def test_strict_tier_custom_threshold(build_rules: Callable[..., RuleSet]) -> None:
    rules = build_rules(due_soon_days=30)
    assert strict_tier(30, rules.ges_strict) is StrictTier.GES_DUE_SOON
    assert strict_tier(31, rules.ges_strict) is StrictTier.NONE


def test_strict_tier_ordering() -> None:
    assert StrictTier.NONE < StrictTier.GES_DUE_SOON < StrictTier.GES_OVERDUE


def test_score_entry_reports_tier(default_rules: RuleSet) -> None:
    assert (
        score_entry(make_input("x", "p4", 5, deadline_in=-1), default_rules, as_of=AS_OF).tier
        is StrictTier.GES_OVERDUE
    )
    assert (
        score_entry(make_input("x", "p4", 5, deadline_in=14), default_rules, as_of=AS_OF).tier
        is StrictTier.GES_DUE_SOON
    )


def test_strict_does_not_change_score(build_rules: Callable[..., RuleSet]) -> None:
    inp = make_input("x", "p3", 120, deadline_in=-10)
    on = score_entry(inp, build_rules(enabled=True), as_of=AS_OF).score
    off = score_entry(inp, build_rules(enabled=False), as_of=AS_OF).score
    assert on == off
    yielded = score_entry(inp, build_rules(yield_to_priorities=[]), as_of=AS_OF).score
    assert on == yielded


# ------------------------------------------------------------------ dorado A-E

_EXPECTED = {
    "A": 50 + 35 * 30 / 730,
    "B": 30 + 35 * 400 / 730,
    "C": 35.0,
    "D": 12.5 + 35 * 120 / 730 + 15,
    "E": 30 + 35 * 20 / 730 + 15 * 35 / 60,
}
_EXPECTED_TIERS = {
    "A": StrictTier.NONE,
    "B": StrictTier.NONE,
    "C": StrictTier.NONE,
    "D": StrictTier.GES_OVERDUE,
    "E": StrictTier.NONE,
}


def test_golden_scores_and_tiers(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    got = {e.score.entry_id: e.score for e in r.entries}
    for k, v in _EXPECTED.items():
        assert got[k].score == pytest.approx(v, abs=1e-6), k
        assert got[k].tier is _EXPECTED_TIERS[k], k
    # Valores redondeados citados en el plan (sección 1).
    assert round(got["A"].score, 2) == 51.44
    assert round(got["B"].score, 2) == 49.18
    assert round(got["D"].score, 2) == 33.25
    assert round(got["E"].score, 2) == 39.71


def _order(rules: RuleSet, inputs: list[PriorityInput]) -> list[str]:
    return [e.score.entry_id for e in rank(inputs, rules, as_of=AS_OF).entries]


def test_golden_order_default_rules_yield_p1(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    assert _order(default_rules, golden_inputs) == ["A", "D", "B", "E", "C"]


def test_golden_order_default_yaml_file(golden_inputs: list[PriorityInput]) -> None:
    from priority.rules import load_default_rules

    assert _order(load_default_rules(), golden_inputs) == ["A", "D", "B", "E", "C"]


def test_golden_order_yield_empty(
    build_rules: Callable[..., RuleSet], golden_inputs: list[PriorityInput]
) -> None:
    assert _order(build_rules(yield_to_priorities=[]), golden_inputs) == [
        "D", "A", "B", "E", "C",
    ]  # fmt: skip


def test_golden_order_strict_disabled(
    build_rules: Callable[..., RuleSet], golden_inputs: list[PriorityInput]
) -> None:
    assert _order(build_rules(enabled=False), golden_inputs) == ["A", "B", "E", "C", "D"]


def test_golden_ranks_start_at_one_and_are_consecutive(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    assert [e.rank for e in r.entries] == [1, 2, 3, 4, 5]
    assert r.get("D").rank == 2
    assert r.as_of == AS_OF
    assert r.rules_id == default_rules.rules_id
    assert r.rules_version == default_rules.rules_version
    assert r.rules_digest == default_rules.digest()
    assert "Herramienta de investigación con datos sintéticos" in r.disclaimer


def test_empty_ranking(default_rules: RuleSet) -> None:
    assert rank([], default_rules, as_of=AS_OF).entries == ()


def test_rank_does_not_mutate_inputs(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    before = list(golden_inputs)
    rank(golden_inputs, default_rules, as_of=AS_OF)
    assert golden_inputs == before


def test_rank_accepts_generator(default_rules: RuleSet, golden_inputs: list[PriorityInput]) -> None:
    r = rank((i for i in golden_inputs), default_rules, as_of=AS_OF)
    assert len(r.entries) == 5
