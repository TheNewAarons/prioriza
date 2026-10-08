"""Regresiones de la revisión de priority (A1-A2, M1-M4, B1-B4).

Cada test falla con el código anterior a las correcciones. Todo sintético, sin red.
"""

from __future__ import annotations

import random
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import polars as pl
import pytest
from priority.adapters import inputs_from_frame, rank_frame
from priority.explain import explain, explain_ranked
from priority.inputs import PriorityInput
from priority.rules import RulesError, RuleSet, parse_rules
from priority.score import rank, score_entry
from priority_test_support import AS_OF, DEFAULT_RULES_DICT, dump, make_input, rules_dict
from shared.db.enums import ClinicalPriority


def _err(d: dict[str, Any] | str) -> str:
    text = d if isinstance(d, str) else dump(d)
    with pytest.raises(RulesError) as exc:
        parse_rules(text)
    return str(exc.value)


def _plain(s: str) -> str:
    """Minúsculas y sin tildes."""
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ------------------------------------------------------------------------- A1


@pytest.mark.parametrize("bad", [["p4"], ["p2"], ["p3"], ["p2", "p3"], ["p1", "p3"], ["p2", "p1"]])
def test_a1_yield_must_be_contiguous_prefix(bad: list[str]) -> None:
    assert "yield_to_priorities" in _err(rules_dict(yield_to_priorities=bad))


@pytest.mark.parametrize(
    "ok", [[], ["p1"], ["p1", "p2"], ["p1", "p2", "p3"], ["p1", "p2", "p3", "p4"]]
)
def test_a1_yield_prefixes_accepted(ok: list[str]) -> None:
    parse_rules(dump(rules_dict(yield_to_priorities=ok)))


# ------------------------------------------------------------------------- A2


def test_a2_explanation_of_overdue_p2_with_default_yield_is_truthful(
    default_rules: RuleSet,
) -> None:
    s = score_entry(make_input("x", "p2", 400, deadline_in=-10), default_rules, as_of=AS_OF)
    text = explain(s, default_rules).text
    assert "salvo las de prioridad" in text
    assert "p1" in text.split("salvo las de prioridad", 1)[1]


def test_a2_explanation_of_yielding_group(default_rules: RuleSet) -> None:
    s = score_entry(make_input("x", "p1", 5), default_rules, as_of=AS_OF)
    text = explain(s, default_rules).text
    assert "fuera de" in text
    assert "p1" in text.split("fuera de", 1)[1]
    assert "otra prioridad" not in text


def test_a2_two_level_yield_lists_both(build_rules: Any) -> None:
    rules = build_rules(yield_to_priorities=["p1", "p2"])
    s = score_entry(make_input("x", "p3", 5, deadline_in=-3), rules, as_of=AS_OF)
    after = explain(s, rules).text.split("salvo las de prioridad", 1)[1]
    assert "p1" in after
    assert "p2" in after


# ------------------------------------------------------------------------- M1


def test_m1_disabled_with_nonempty_yield_rejected() -> None:
    d = rules_dict(enabled=False)
    d["ges_strict"]["yield_to_priorities"] = ["p1"]
    assert "yield_to_priorities" in _err(d)


def test_m1_disabled_with_empty_yield_accepted() -> None:
    parse_rules(dump(rules_dict(enabled=False, yield_to_priorities=[])))


# ------------------------------------------------------------------------- M2


def test_m2_null_status_rejected() -> None:
    df = pl.DataFrame(
        {
            "id": ["a", "b"],
            "clinical_priority": ["p1", "p2"],
            "entry_date": [date(2025, 1, 1), date(2025, 1, 2)],
            "ges_deadline": [None, None],
            "status": ["waiting", None],
        },
        schema_overrides={"ges_deadline": pl.Date},
    )
    with pytest.raises(ValueError, match="waiting"):
        inputs_from_frame(df)


# ------------------------------------------------------------------------- M3


def test_m3_explain_ranked_rejects_different_rules(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    d = rules_dict()
    d["components"][0]["weight"] = 60
    d["components"][1]["weight"] = 30
    d["components"][2]["weight"] = 10
    other = parse_rules(dump(d))
    assert other.digest() != default_rules.digest()
    with pytest.raises(ValueError, match=r"(?i)digest|reglas"):
        explain_ranked(r, "A", other)


def test_m3_explain_ranked_same_rules_ok(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    assert explain_ranked(r, "A", default_rules).entry_id == "A"


# ------------------------------------------------------------------------- M4


def _big_frame(n: int) -> pl.DataFrame:
    rng = random.Random(20251008)
    prios = ["p1", "p2", "p3", "p4"]
    waits = [rng.randint(0, 3650) for _ in range(n)]
    ges = [rng.random() < 0.07 for _ in range(n)]
    return pl.DataFrame(
        {
            "id": [str(uuid.UUID(int=rng.getrandbits(128))) for _ in range(n)],
            "clinical_priority": [rng.choice(prios) for _ in range(n)],
            "entry_date": [AS_OF - timedelta(days=w) for w in waits],
            "ges_deadline": [
                AS_OF + timedelta(days=rng.randint(-max(w, 1), 120)) if g else None
                for w, g in zip(waits, ges, strict=True)
            ],
            "status": ["waiting"] * n,
            "health_service_code": [rng.randint(1, 29) for _ in range(n)],
            "specialty_code": [rng.randint(1, 20) for _ in range(n)],
            "care_type": [rng.choice(["consult", "surgery"]) for _ in range(n)],
        },
        schema_overrides={"ges_deadline": pl.Date},
    )


def test_m4_rank_frame_100k_partitioned_under_3_seconds(default_rules: RuleSet) -> None:
    df = _big_frame(100_000)
    t0 = time.perf_counter()
    out = rank_frame(df, default_rules, as_of=AS_OF)
    elapsed = time.perf_counter() - t0
    assert sum(len(r.entries) for r in out.values()) == 100_000
    assert len(out) > 1000
    assert elapsed < 3.0, f"rank_frame tardó {elapsed:.2f} s"


# ------------------------------------------------------------------------- B1


@pytest.mark.parametrize("bad", [True, "35", 1001, 1e308])
def test_b1_wait_weight_strict_and_bounded(bad: Any) -> None:
    d = rules_dict()
    d["components"][1]["weight"] = bad
    assert "weight" in _err(d)


def test_b1_clinical_weight_bool_and_overflow_rejected() -> None:
    d = rules_dict()
    d["components"][0]["weight"] = True
    assert "weight" in _err(d)
    d = rules_dict()
    d["components"][0]["weight"] = 1e308
    d["components"][1]["weight"] = 1e308
    assert "weight" in _err(d)


def test_b1_weight_1000_accepted() -> None:
    d = rules_dict()
    d["components"][1]["weight"] = 1000
    parse_rules(dump(d))


# ------------------------------------------------------------------------- B2


def test_b2_merge_key_rejected() -> None:
    text = dump(DEFAULT_RULES_DICT).replace(
        "ges_strict:\n  enabled: true\n",
        "ges_strict:\n  <<: {enabled: false}\n  enabled: true\n",
    )
    assert "<<" in text
    _err(text)


def test_b2_merge_key_list_rejected() -> None:
    text = "base: &b {enabled: false}\n" + dump(DEFAULT_RULES_DICT).replace(
        "ges_strict:\n  enabled: true\n",
        "ges_strict:\n  <<: [*b]\n  enabled: true\n",
    )
    _err(text)


def test_b2_anchor_and_alias_rejected() -> None:
    text = dump(DEFAULT_RULES_DICT).replace(
        "rules_id: test-default", "rules_id: &x test-default\nrules_version_alias: *x"
    )
    _err(text)


# ------------------------------------------------------------------------- B3


@pytest.mark.parametrize(
    "term",
    [
        "Comuna de residencia",
        "PREVISIÓN",
        "Fonasa",
        "isapre",
        "Edad del paciente",
        "Sexo",
        "Género",
        "Etnia",
        "Nacionalidad",
        "migrante",
        "commune",
        "insurance plan",
        "Age",
        "sex",
        "gender",
        "ethnicity",
        "nationality",
        "migrant",
        "PREVISION",
        "genero",
    ],
)
@pytest.mark.parametrize("idx", [0, 1, 2])
def test_b3_prohibited_label_rejected(term: str, idx: int) -> None:
    d = rules_dict()
    d["components"][idx]["label"] = term
    assert "label" in _err(d)


def test_b3_clean_labels_accepted() -> None:
    parse_rules(dump(rules_dict()))


def test_b3_explanation_text_has_no_prohibited_terms(
    default_rules: RuleSet, golden_inputs: list[PriorityInput]
) -> None:
    banned = (
        "comuna",
        "prevision",
        "fonasa",
        "isapre",
        "edad",
        "sexo",
        "genero",
        "etnia",
        "nacionalidad",
        "migrante",
    )
    r = rank(golden_inputs, default_rules, as_of=AS_OF)
    for e in r.entries:
        text = _plain(explain_ranked(r, e.score.entry_id, default_rules).text)
        for term in banned:
            assert term not in text, term


# ------------------------------------------------------------------------- B4


def test_b4_none_entry_date_rejected() -> None:
    with pytest.raises(ValueError, match="entry_date"):
        PriorityInput("x", ClinicalPriority.P1, None, None)  # type: ignore[arg-type]


def test_b4_datetime_entry_date_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="entry_date"):
        PriorityInput("x", ClinicalPriority.P1, datetime(2025, 1, 1), None)  # type: ignore[arg-type]


def test_b4_adapter_collects_all_invalid_rows_in_one_error() -> None:
    df = pl.DataFrame(
        {
            "id": ["ok", "bad1", "bad2"],
            "clinical_priority": ["p1", "p2", "p3"],
            "entry_date": [date(2025, 5, 1), date(2025, 5, 1), date(2025, 6, 1)],
            "ges_deadline": [None, date(2025, 4, 1), date(2025, 5, 1)],
        },
        schema_overrides={"ges_deadline": pl.Date},
    )
    with pytest.raises(ValueError) as exc:
        inputs_from_frame(df)
    msg = str(exc.value)
    assert "bad1" in msg
    assert "bad2" in msg
