"""Propiedades (hypothesis) del puntaje y el orden de prioridad.

Perfil determinista (``derandomize=True``); los ids son UUID generados y nunca hay datos reales.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from priority.inputs import PriorityInput
from priority.rules import RuleSet, parse_rules
from priority.score import StrictTier, rank, score_entry
from priority_test_support import AS_OF, dump, make_input, rules_dict
from shared.db.enums import ClinicalPriority

PROFILE = settings(derandomize=True, max_examples=150, deadline=None, print_blob=True)

RULES_YIELD_P1 = parse_rules(dump(rules_dict(yield_to_priorities=["p1"])))
RULES_YIELD_NONE = parse_rules(dump(rules_dict(yield_to_priorities=[])))
RULES_DISABLED = parse_rules(dump(rules_dict(enabled=False, yield_to_priorities=[])))
DEFAULT_LIKE = st.sampled_from([RULES_YIELD_P1, RULES_YIELD_NONE])

PRIOS = list(ClinicalPriority)
_RANK_OF = {p: i for i, p in enumerate(PRIOS)}  # p1 = 0 (mejor)


@st.composite
def inputs_st(draw: st.DrawFn) -> PriorityInput:
    """Entrada sintética con id UUID generado."""
    wait = draw(st.integers(0, 4000))
    is_ges = draw(st.booleans())
    deadline = None
    if is_ges:
        d = draw(st.integers(max(-wait, -400), 120))
        deadline = AS_OF + timedelta(days=d)
    return PriorityInput(
        entry_id=str(draw(st.uuids())),
        clinical_priority=draw(st.sampled_from(PRIOS)),
        entry_date=AS_OF - timedelta(days=wait),
        ges_deadline=deadline,
    )


def lists_st(min_size: int = 1, max_size: int = 12) -> st.SearchStrategy[list[PriorityInput]]:
    """Listas de entradas con ids únicos."""
    return st.lists(
        inputs_st(), min_size=min_size, max_size=max_size, unique_by=lambda i: i.entry_id
    )


def _pos(rules: RuleSet, items: list[PriorityInput]) -> dict[str, int]:
    return {e.score.entry_id: e.rank for e in rank(items, rules, as_of=AS_OF).entries}


# ------------------------------------------------------------- 1. monotonía en espera


@PROFILE
@given(items=lists_st(), data=st.data(), rules=DEFAULT_LIKE)
def test_more_wait_never_lowers_score_or_rank(
    items: list[PriorityInput], data: st.DataObject, rules: RuleSet
) -> None:
    idx = data.draw(st.integers(0, len(items) - 1))
    extra = data.draw(st.integers(0, 3000))
    target = items[idx]
    longer = PriorityInput(
        target.entry_id,
        target.clinical_priority,
        target.entry_date - timedelta(days=extra),
        target.ges_deadline,
    )
    changed = [*items[:idx], longer, *items[idx + 1 :]]
    s0 = score_entry(target, rules, as_of=AS_OF)
    s1 = score_entry(longer, rules, as_of=AS_OF)
    assert s1.score >= s0.score
    assert s1.tier is s0.tier
    assert _pos(rules, changed)[target.entry_id] <= _pos(rules, items)[target.entry_id]


# ----------------------------------------------- 2. mejor prioridad clínica no empeora


@PROFILE
@given(items=lists_st(), data=st.data(), rules=DEFAULT_LIKE)
def test_better_clinical_priority_never_worsens_rank(
    items: list[PriorityInput], data: st.DataObject, rules: RuleSet
) -> None:
    idx = data.draw(st.integers(0, len(items) - 1))
    target = items[idx]
    better = data.draw(
        st.sampled_from([p for p in PRIOS if _RANK_OF[p] <= _RANK_OF[target.clinical_priority]])
    )
    improved = PriorityInput(target.entry_id, better, target.entry_date, target.ges_deadline)
    changed = [*items[:idx], improved, *items[idx + 1 :]]
    assert (
        score_entry(improved, rules, as_of=AS_OF).score
        >= score_entry(target, rules, as_of=AS_OF).score
    )
    assert _pos(rules, changed)[target.entry_id] <= _pos(rules, items)[target.entry_id]


# ---------------------------------------------------- 3. GES estricta antes que NONE


@PROFILE
@given(items=lists_st(min_size=2), rules=DEFAULT_LIKE)
def test_strict_ges_never_behind_none_unless_yielding(
    items: list[PriorityInput], rules: RuleSet
) -> None:
    ranking = rank(items, rules, as_of=AS_OF)
    yields = set(rules.ges_strict.yield_to_priorities)
    for a in ranking.entries:
        for b in ranking.entries:
            sa, sb = a.score, b.score
            if (
                sa.tier is StrictTier.NONE
                and sb.tier is not StrictTier.NONE
                and sa.clinical_priority not in yields
            ):
                assert b.rank < a.rank, (sb, sa)
            same_group = (sa.clinical_priority in yields) == (sb.clinical_priority in yields)
            if (
                same_group
                and sa.tier is StrictTier.GES_OVERDUE
                and sb.tier is StrictTier.GES_DUE_SOON
            ):
                assert a.rank < b.rank, (sa, sb)


@PROFILE
@given(items=lists_st(min_size=2))
def test_with_p1_yield_no_p1_is_behind_a_non_p1(items: list[PriorityInput]) -> None:
    ranking = rank(items, RULES_YIELD_P1, as_of=AS_OF)
    seen_non_p1 = False
    for e in ranking.entries:
        if e.score.clinical_priority is ClinicalPriority.P1:
            assert not seen_non_p1
        else:
            seen_non_p1 = True


@PROFILE
@given(items=lists_st(min_size=2))
def test_yield_empty_overdue_never_behind_non_strict(items: list[PriorityInput]) -> None:
    ranking = rank(items, RULES_YIELD_NONE, as_of=AS_OF)
    tiers = [e.score.tier for e in ranking.entries]
    assert tiers == sorted(tiers, reverse=True)


# --------------------------------- 4. contraejemplo con la regla desactivada


def test_disabled_rule_counterexample_overdue_behind_non_ges() -> None:
    d = make_input("D", "p3", 120, deadline_in=-10)
    c = make_input("C", "p4", 1500)
    with_rule = _pos(RULES_YIELD_NONE, [c, d])
    without = _pos(RULES_DISABLED, [c, d])
    assert with_rule["D"] < with_rule["C"]
    assert without["D"] > without["C"]


@PROFILE
@given(items=lists_st(min_size=2))
def test_disabled_rule_order_follows_score_only(items: list[PriorityInput]) -> None:
    ranking = rank(items, RULES_DISABLED, as_of=AS_OF)
    scores = [e.score.score for e in ranking.entries]
    assert scores == sorted(scores, reverse=True)
    assert all(e.score.tier is StrictTier.NONE for e in ranking.entries)


# ------------------------------------------------- 5. invariancia al orden de entrada


@PROFILE
@given(items=lists_st(min_size=2), data=st.data(), rules=DEFAULT_LIKE)
def test_rank_invariant_to_input_permutation(
    items: list[PriorityInput], data: st.DataObject, rules: RuleSet
) -> None:
    shuffled = data.draw(st.permutations(items))
    assert rank(shuffled, rules, as_of=AS_OF).entries == rank(items, rules, as_of=AS_OF).entries


# ------------------------------------- 6. independencia de alternativas irrelevantes


@PROFILE
@given(items=lists_st(min_size=2), data=st.data(), rules=DEFAULT_LIKE)
def test_independence_of_irrelevant_alternatives(
    items: list[PriorityInput], data: st.DataObject, rules: RuleSet
) -> None:
    keep = data.draw(st.lists(st.booleans(), min_size=len(items), max_size=len(items)))
    subset = [i for i, k in zip(items, keep, strict=True) if k]
    assume(subset)
    full = rank(items, rules, as_of=AS_OF)
    part = rank(subset, rules, as_of=AS_OF)
    full_scores = {e.score.entry_id: e.score for e in full.entries}
    for e in part.entries:
        assert e.score == full_scores[e.score.entry_id]
    kept = {i.entry_id for i in subset}
    relative = [e.score.entry_id for e in full.entries if e.score.entry_id in kept]
    assert relative == [e.score.entry_id for e in part.entries]


# --------------------------------------- 7-8. rango del puntaje y suma de contribuciones


@st.composite
def rules_st(draw: st.DrawFn) -> dict[str, Any]:
    """RuleSet válido generado (valores en múltiplos de 1/20 para YAML exacto)."""
    due_soon = draw(st.integers(0, 60))
    enabled = draw(st.booleans())
    vals = sorted((draw(st.integers(0, 20)) / 20 for _ in range(4)), reverse=True)
    assume(vals[0] > vals[3])
    kind = draw(st.sampled_from(["linear_saturated", "log_saturated", "steps"]))
    if kind == "steps":
        cuts = sorted(set(draw(st.lists(st.integers(1, 2000), max_size=3))))
        levels = sorted(draw(st.integers(0, 20)) / 20 for _ in range(len(cuts) + 1))
        wait_tr: dict[str, Any] = {
            "type": "steps",
            "steps": [{"at_days": a, "value": v} for a, v in zip([0, *cuts], levels, strict=True)],
        }
    else:
        wait_tr = {"type": kind, "saturation_days": draw(st.integers(1, 3650))}
    start = due_soon + draw(st.integers(0, 120))
    end = start - draw(st.integers(1, 200))
    components: list[dict[str, Any]] = [
        {
            "field": "clinical_priority",
            "label": "Prioridad",
            "weight": draw(st.integers(1, 400)) / 2,
            "mapping": dict(zip(["p1", "p2", "p3", "p4"], vals, strict=True)),
        }
    ]
    if draw(st.booleans()):
        components.append(
            {
                "field": "wait_days",
                "label": "Espera",
                "weight": draw(st.integers(0, 200)),
                "transform": wait_tr,
            }
        )
    if draw(st.booleans()):
        components.append(
            {
                "field": "days_to_ges_deadline",
                "label": "GES",
                "weight": draw(st.integers(0, 200)),
                "transform": {"type": "ramp_down", "start_days": start, "end_days": end},
            }
        )
    components = draw(st.permutations(components))
    return {
        "schema_version": 1,
        "rules_id": "gen",
        "rules_version": "1",
        "description": "generado",
        "components": components,
        "ges_strict": {
            "enabled": enabled,
            "due_soon_days": due_soon,
            "order_within": draw(st.sampled_from(["deadline", "score"])),
            # Solo prefijos contiguos de p1..p4 y vacío si la regla está desactivada.
            "yield_to_priorities": ["p1", "p2", "p3", "p4"][: draw(st.integers(0, 4))]
            if enabled
            else [],
        },
    }


@PROFILE
@given(rd=rules_st(), items=lists_st(max_size=6))
def test_score_between_0_and_100_for_any_valid_ruleset(
    rd: dict[str, Any], items: list[PriorityInput]
) -> None:
    rules = parse_rules(dump(rd))
    for inp in items:
        s = score_entry(inp, rules, as_of=AS_OF)
        assert 0.0 <= s.score <= 100.0
        assert math.isfinite(s.score)
        assert sum(c.effective_weight for c in s.components) == pytest.approx(100.0)
        for c in s.components:
            assert 0.0 <= c.normalized <= 1.0


@PROFILE
@given(rd=rules_st(), items=lists_st(max_size=6))
def test_sum_of_contributions_equals_score(rd: dict[str, Any], items: list[PriorityInput]) -> None:
    rules = parse_rules(dump(rd))
    for inp in items:
        s = score_entry(inp, rules, as_of=AS_OF)
        assert abs(math.fsum(c.contribution for c in s.components) - s.score) <= 1e-9


@PROFILE
@given(items=lists_st(max_size=10), rules=DEFAULT_LIKE)
def test_sum_of_contributions_equals_score_default_weights(
    items: list[PriorityInput], rules: RuleSet
) -> None:
    for inp in items:
        s = score_entry(inp, rules, as_of=AS_OF)
        assert abs(math.fsum(c.contribution for c in s.components) - s.score) <= 1e-9


@PROFILE
@given(rd=rules_st(), items=lists_st(min_size=2, max_size=8))
def test_better_declared_priority_never_ranked_behind_worse_with_equal_group(
    rd: dict[str, Any], items: list[PriorityInput]
) -> None:
    """Con cualquier regla válida, una p1 nunca queda detrás de otra prioridad si ambas
    tienen el mismo nivel estricto y la misma fecha/plazo (la prioridad declarada no se invierte).
    """
    rules = parse_rules(dump(rd))
    twins = []
    for n, p in enumerate(PRIOS):
        base = items[0]
        twins.append(PriorityInput(f"t{n}", p, base.entry_date, base.ges_deadline))
    order = [e.score.entry_id for e in rank(twins, rules, as_of=AS_OF).entries]
    assert order == sorted(order)  # t0 (p1) < t1 (p2) < t2 (p3) < t3 (p4)


@PROFILE
@given(rd=rules_st(), items=lists_st(), data=st.data())
def test_better_clinical_priority_never_worsens_rank_any_valid_ruleset(
    rd: dict[str, Any], items: list[PriorityInput], data: st.DataObject
) -> None:
    """Regresión A1: la propiedad vale para cualquier RuleSet válido, no solo los por defecto."""
    rules = parse_rules(dump(rd))
    idx = data.draw(st.integers(0, len(items) - 1))
    target = items[idx]
    better = data.draw(
        st.sampled_from([p for p in PRIOS if _RANK_OF[p] <= _RANK_OF[target.clinical_priority]])
    )
    improved = PriorityInput(target.entry_id, better, target.entry_date, target.ges_deadline)
    changed = [*items[:idx], improved, *items[idx + 1 :]]
    assert _pos(rules, changed)[target.entry_id] <= _pos(rules, items)[target.entry_id]
