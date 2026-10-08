"""Tests de adaptadores (ORM en memoria, sin DB; DataFrames de polars)."""

from __future__ import annotations

import inspect
import uuid
from datetime import date

import polars as pl
import pytest
from priority.adapters import from_waitlist_entry, inputs_from_frame, rank_frame
from priority.rules import RuleSet
from priority.score import StrictTier, rank
from priority_test_support import AS_OF
from shared.db.enums import ClinicalPriority, EntryStatus
from shared.db.models import WaitlistEntry

# Ids UUID fijos (sintéticos).
IDS = [str(uuid.UUID(int=i)) for i in range(1, 9)]


def _orm(**kw: object) -> WaitlistEntry:
    base: dict[str, object] = {
        "id": uuid.UUID(int=77),
        "clinical_priority": ClinicalPriority.P2,
        "entry_date": date(2025, 6, 1),
        "ges_deadline": None,
        "status": EntryStatus.WAITING,
    }
    base.update(kw)
    return WaitlistEntry(**base)


def _frame(**extra: list[object]) -> pl.DataFrame:
    data: dict[str, list[object]] = {
        "id": IDS[:4],
        "clinical_priority": ["p1", "p2", "p3", "p4"],
        "entry_date": [date(2025, 9, 1), date(2025, 1, 1), date(2025, 3, 1), date(2024, 1, 1)],
        "ges_deadline": [None, date(2025, 9, 20), None, date(2025, 10, 5)],
    }
    data.update(extra)
    return pl.DataFrame(data, schema_overrides={"ges_deadline": pl.Date})


# ------------------------------------------------------------------------ ORM


def test_from_waitlist_entry_in_memory() -> None:
    e = _orm(ges_deadline=date(2025, 12, 1))
    inp = from_waitlist_entry(e)
    assert inp.entry_id == str(uuid.UUID(int=77))
    assert inp.clinical_priority is ClinicalPriority.P2
    assert inp.entry_date == date(2025, 6, 1)
    assert inp.ges_deadline == date(2025, 12, 1)
    assert inp.is_ges


def test_from_waitlist_entry_non_ges() -> None:
    inp = from_waitlist_entry(_orm())
    assert inp.ges_deadline is None
    assert not inp.is_ges


@pytest.mark.parametrize(
    "status", [EntryStatus.SCHEDULED, EntryStatus.RESOLVED, EntryStatus.REMOVED]
)
def test_from_waitlist_entry_rejects_non_waiting(status: EntryStatus) -> None:
    with pytest.raises(ValueError, match=r".+"):
        from_waitlist_entry(_orm(status=status))


# --------------------------------------------------------------------- polars


def test_inputs_from_frame_basic() -> None:
    out = inputs_from_frame(_frame())
    assert [i.entry_id for i in out] == IDS[:4]
    assert [i.clinical_priority for i in out] == list(ClinicalPriority)
    assert out[1].ges_deadline == date(2025, 9, 20)
    assert out[0].ges_deadline is None


def test_inputs_from_frame_ignores_extra_columns() -> None:
    extra = _frame(
        insurance=["fonasa_a", "other", "fonasa_d", "fonasa_b"],
        commune_code=[1, 2, 3, 4],
        age_group=["0_14", "65_plus", "20_44", "15_19"],
    )
    assert inputs_from_frame(extra) == inputs_from_frame(_frame())


@pytest.mark.parametrize("col", ["id", "clinical_priority", "entry_date", "ges_deadline"])
def test_inputs_from_frame_missing_column_fails(col: str) -> None:
    with pytest.raises((ValueError, KeyError, pl.exceptions.ColumnNotFoundError)):
        inputs_from_frame(_frame().drop(col))


def test_inputs_from_frame_status_must_be_waiting() -> None:
    ok = _frame(status=["waiting"] * 4)
    assert len(inputs_from_frame(ok)) == 4
    bad = _frame(status=["waiting", "resolved", "waiting", "waiting"])
    with pytest.raises(ValueError, match=r".+"):
        inputs_from_frame(bad)


def test_inputs_from_frame_invalid_priority_fails() -> None:
    bad = _frame().with_columns(pl.Series("clinical_priority", ["p1", "p9", "p3", "p4"]))
    with pytest.raises(ValueError, match=r".+"):
        inputs_from_frame(bad)


def test_rank_frame_partitions_and_scores_unchanged(default_rules: RuleSet) -> None:
    df = pl.DataFrame(
        {
            "id": IDS[:6],
            "clinical_priority": ["p1", "p3", "p2", "p4", "p2", "p1"],
            "entry_date": [
                date(2025, 9, 1),
                date(2025, 2, 1),
                date(2025, 4, 1),
                date(2024, 4, 1),
                date(2025, 8, 1),
                date(2025, 5, 1),
            ],
            "ges_deadline": [None] * 6,
            "health_service_code": [1, 1, 1, 2, 2, 2],
            "specialty_code": ["cardio", "cardio", "trauma", "cardio", "cardio", "cardio"],
            "care_type": ["consult"] * 6,
        },
        schema_overrides={"ges_deadline": pl.Date},
    )
    result = rank_frame(df, default_rules, as_of=AS_OF)
    assert set(result) == {
        (1, "cardio", "consult"),
        (1, "trauma", "consult"),
        (2, "cardio", "consult"),
    }
    sizes = {k: len(v.entries) for k, v in result.items()}
    assert sizes == {
        (1, "cardio", "consult"): 2,
        (1, "trauma", "consult"): 1,
        (2, "cardio", "consult"): 3,
    }
    # Cada partición es el ranking independiente de sus filas, y el puntaje no depende de la cola.
    global_rank = rank(inputs_from_frame(df), default_rules, as_of=AS_OF)
    for ranking in result.values():
        assert [e.rank for e in ranking.entries] == list(range(1, len(ranking.entries) + 1))
        for e in ranking.entries:
            assert e.score.score == global_rank.get(e.score.entry_id).score.score
    ids_cardio_2 = [e.score.entry_id for e in result[(2, "cardio", "consult")].entries]
    assert ids_cardio_2 == [IDS[5], IDS[4], IDS[3]]


def test_rank_frame_tiers_reflect_ges(default_rules: RuleSet) -> None:
    df = _frame(health_service_code=[1] * 4, specialty_code=["x"] * 4, care_type=["consult"] * 4)
    (ranking,) = rank_frame(df, default_rules, as_of=AS_OF).values()
    tiers = {e.score.entry_id: e.score.tier for e in ranking.entries}
    assert tiers[IDS[1]] is StrictTier.GES_OVERDUE  # plazo 2025-09-20 < as_of
    assert tiers[IDS[3]] is StrictTier.GES_DUE_SOON  # vence en 5 días
    assert tiers[IDS[0]] is StrictTier.NONE


def test_rank_frame_as_of_has_no_default() -> None:
    p = inspect.signature(rank_frame).parameters["as_of"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is inspect.Parameter.empty
