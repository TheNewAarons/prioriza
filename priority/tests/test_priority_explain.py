"""Tests de explicaciones y rendimiento."""

from __future__ import annotations

import inspect
import random
import time
import uuid
from datetime import timedelta
from typing import Any

import pytest
from priority.explain import Explanation, explain, explain_ranked, explanation_to_dict
from priority.inputs import PriorityInput
from priority.rules import RuleSet
from priority.score import StrictTier, rank, score_entry
from priority_test_support import AS_OF, make_input
from shared.db.enums import ClinicalPriority


def _es(x: float) -> str:
    """Formato es-CL con dos decimales."""
    return f"{x:.2f}".replace(".", ",")


def test_explanation_contains_label_value_weight_and_contribution(
    default_rules: RuleSet,
) -> None:
    s = score_entry(make_input("A", "p1", 30), default_rules, as_of=AS_OF)
    ex = explain(s, default_rules, rank=2, total=5)
    assert isinstance(ex, Explanation)
    text = ex.text
    for comp, rule in zip(s.components, default_rules.components, strict=True):
        assert rule.label in text
        assert _es(comp.contribution) in text
        if comp.raw_value is not None:  # "no aplica" no muestra peso (ejemplo del plan)
            assert f"{rule.weight:g}" in text
    assert "p1" in text
    assert "30" in text
    assert _es(s.score) in text  # 51,44
    assert "51,44" in text
    assert ex.rank == 2
    assert ex.total == 5
    assert ex.tier is StrictTier.NONE
    assert ex.tier_reason is None
    assert ex.score == s.score


def test_explanation_uses_decimal_comma(default_rules: RuleSet) -> None:
    s = score_entry(make_input("A", "p1", 30), default_rules, as_of=AS_OF)
    assert "1,44" in explain(s, default_rules).text


def test_explanation_strict_tier_reason_mentions_deadline_and_days(
    default_rules: RuleSet,
) -> None:
    s = score_entry(make_input("D", "p3", 120, deadline_in=-10), default_rules, as_of=AS_OF)
    ex = explain(s, default_rules, rank=2, total=5)
    assert ex.tier is StrictTier.GES_OVERDUE
    assert ex.tier_reason is not None
    assert "2025-09-20" in ex.tier_reason
    assert "10" in ex.tier_reason
    assert ex.tier_reason in ex.text
    assert _es(s.score) in ex.text


def test_explanation_due_soon_reason(default_rules: RuleSet) -> None:
    s = score_entry(make_input("S", "p2", 20, deadline_in=5), default_rules, as_of=AS_OF)
    ex = explain(s, default_rules)
    assert ex.tier is StrictTier.GES_DUE_SOON
    assert ex.tier_reason is not None
    assert str(AS_OF + timedelta(days=5)) in ex.tier_reason
    assert "5" in ex.tier_reason
    assert ex.rank is None
    assert ex.total is None


def test_explain_ranked_matches_explain(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    for e in r.entries:
        ex = explain_ranked(r, e.score.entry_id, default_rules)
        assert ex.entry_id == e.score.entry_id
        assert ex.rank == e.rank
        assert ex.total == 5
        assert ex == explain(e.score, default_rules, rank=e.rank, total=5)


def test_explain_ranked_unknown_id(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    with pytest.raises((KeyError, ValueError)):
        explain_ranked(r, "no-existe", default_rules)


def test_saturated_wait_explained(default_rules: RuleSet) -> None:
    s = score_entry(make_input("C", "p4", 1500), default_rules, as_of=AS_OF)
    text = explain(s, default_rules).text
    assert "35,00" in text
    assert "1.500" in text or "1500" in text


def test_explanation_to_dict(default_rules: RuleSet) -> None:
    s = score_entry(make_input("D", "p3", 120, deadline_in=-10), default_rules, as_of=AS_OF)
    d: dict[str, Any] = explanation_to_dict(explain(s, default_rules, rank=1, total=3))
    assert d["entry_id"] == "D"
    assert d["rank"] == 1
    assert d["total"] == 3
    assert d["score"] == pytest.approx(s.score)
    import json

    json.dumps(d)  # serializable para la API
    assert "p3" in json.dumps(d, ensure_ascii=False) or d.get("lines")


def test_explain_has_no_as_of_parameter() -> None:
    # La explicación se genera desde un PriorityScore ya calculado con as_of explícito.
    assert "as_of" not in inspect.signature(explain).parameters


# ------------------------------------------------------------------ rendimiento


def test_rank_100k_entries_under_5_seconds(default_rules: RuleSet) -> None:
    rng = random.Random(20251008)
    items: list[PriorityInput] = []
    prios = list(ClinicalPriority)
    for _ in range(100_000):
        wait = rng.randint(0, 3650)
        deadline = None
        if rng.random() < 0.07:
            deadline = AS_OF + timedelta(days=rng.randint(-max(wait, 1), 120))
        items.append(
            PriorityInput(
                entry_id=str(uuid.UUID(int=rng.getrandbits(128))),
                clinical_priority=rng.choice(prios),
                entry_date=AS_OF - timedelta(days=wait),
                ges_deadline=deadline,
            )
        )
    t0 = time.perf_counter()
    ranking = rank(items, default_rules, as_of=AS_OF)
    elapsed = time.perf_counter() - t0
    assert len(ranking.entries) == 100_000
    assert ranking.entries[0].rank == 1
    assert ranking.entries[-1].rank == 100_000
    assert elapsed < 5.0, f"rank tardó {elapsed:.2f} s"
