"""Adaptadores sobre DataFrames en memoria (usados por la simulación, P10).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import polars as pl
import pytest
from scheduler.config import SchedulerConfig

from scheduler import adapters

AS_OF = date(2025, 9, 30)


def _frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    entries = pl.DataFrame(
        {
            "entry_id": ["e1"],
            "patient_id": ["p1"],
            "health_service_code": [1],
            "establishment_code": ["H1"],
            "specialty_code": ["cne_medical:x"],
            "care_type": ["consultation"],
            "entry_date": [date(2025, 1, 1)],
        }
    )
    blocks = pl.DataFrame(
        {
            "slot_id": ["s1"],
            "health_service_code": [1],
            "establishment_code": ["H1"],
            "specialty_code": ["cne_medical:x"],
            "resource_kind": ["specialist_agenda"],
            # 15:00 en Santiago: un bloque de la tarde, como en el hallazgo de la revisión.
            "start_at": [datetime(2025, 10, 7, 18, 0, tzinfo=UTC)],
        }
    )
    return entries, blocks


def test_noshow_history_is_cut_at_local_midnight_of_as_of(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una cita del propio ``as_of`` no entra al historial; la del día anterior sí."""
    seen: dict[str, Any] = {}

    def fake_features(candidates: pl.DataFrame, history: pl.DataFrame, *_: Any) -> pl.DataFrame:
        seen["history"] = history
        return candidates

    monkeypatch.setattr(adapters, "build_candidate_features", fake_features)
    monkeypatch.setattr(adapters, "predict_noshow", lambda _b, f: np.full(f.height, 0.2))
    history = pl.DataFrame(
        {
            "patient_id": ["p1", "p1"],
            # 2025-09-29 20:00 local (día anterior) y 2025-09-30 11:00 local (mismo as_of).
            "scheduled_start": [
                datetime(2025, 9, 29, 23, 0, tzinfo=UTC),
                datetime(2025, 9, 30, 14, 0, tzinfo=UTC),
            ],
            "status": ["attended", "no_show"],
        }
    )
    entries, blocks = _frames()
    out, version = adapters.noshow_from_frames(
        entries,
        blocks,
        history,
        pl.DataFrame({"code": ["cne_medical:x"], "care_type": ["consultation"]}),
        {"model_version": "test"},
        SchedulerConfig(),
        AS_OF,
    )
    assert version == "test"
    assert out["p"].to_list() == [0.2]
    assert seen["history"]["status"].to_list() == ["attended"]
