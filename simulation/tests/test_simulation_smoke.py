"""Humo de la simulación: mundo chico a mano, 4 políticas x réplicas y aviso (diseño §9)."""

from __future__ import annotations

import uuid
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl
from priority.rules import load_default_rules
from simulation.config import DEFAULT_REPLICA_SEEDS, POLICIES, SimulationConfig
from simulation.report import run_experiment
from simulation.world import World
from synthetic.capacity import Cell, horizon_start


def _world() -> World:
    as_of = date(2026, 1, 4)  # domingo; el horizonte parte el lunes siguiente
    truth_params = {
        "scenario": "baseline",
        "beta_age": {"a1": 0.0},
        "beta_ins": {"f1": 0.0},
        "gamma": {"s1": 0.0},
        "beta_wait": 0.0,
        "beta_lead": 0.0,
        "sigma_u": 0.0,
        "ref_lead_days": 28,
        "intercepts": {"1:surgery": 0.0},
    }
    stock = pl.DataFrame(
        {
            "id": ["e1"],
            "patient_id": ["p1"],
            "health_service_code": [1],
            "establishment_code": ["h1"],
            "specialty_code": ["s1"],
            "procedure_code": ["proc1"],
            "care_type": ["surgery"],
            "clinical_priority": ["p1"],
            "is_ges": [False],
            "ges_deadline": [None],
            "entry_date": [as_of - timedelta(days=100)],
        },
        schema={
            "id": pl.String,
            "patient_id": pl.String,
            "health_service_code": pl.Int64,
            "establishment_code": pl.String,
            "specialty_code": pl.String,
            "procedure_code": pl.String,
            "care_type": pl.String,
            "clinical_priority": pl.String,
            "is_ges": pl.Boolean,
            "ges_deadline": pl.Date,
            "entry_date": pl.Date,
        },
    )
    patient_frame = pl.DataFrame(
        {
            "patient_id": ["p1"],
            "age_group": ["a1"],
            "insurance": ["f1"],
            "commune_code": ["c1"],
            "noshow_frailty": [0.0],
        },
        schema={
            "patient_id": pl.String,
            "age_group": pl.String,
            "insurance": pl.String,
            "commune_code": pl.String,
            "noshow_frailty": pl.Float64,
        },
    )
    empty_appt = pl.DataFrame(
        {
            "patient_id": pl.Series([], dtype=pl.String),
            "scheduled_start": pl.Series([], dtype=pl.Datetime("us", "UTC")),
            "status": pl.Series([], dtype=pl.String),
        }
    )
    return World(
        run_id=str(uuid.uuid4()),
        as_of=as_of,
        horizon_start=horizon_start(as_of),
        size=1,
        seed=42,
        scenario="baseline",
        truth_params=truth_params,
        sigma_u=0.0,
        median_wait={(1, "surgery"): 200.0},
        stock=stock,
        patient_frame=patient_frame,
        history=empty_appt,
        specialties=pl.DataFrame(
            {"code": pl.Series([], dtype=pl.String), "care_type": pl.Series([], dtype=pl.String)}
        ),
        procedures=pl.DataFrame(
            {"procedure_code": ["proc1"], "duration_min": [60]},
            schema={"procedure_code": pl.String, "duration_min": pl.Int64},
        ),
        hospitals_by_service={1: [("h1", 1.0)]},
        cells=[Cell(1, "surgery", "s1", 1, 360.0, 0, 1.0, 0.0)],
        rules=load_default_rules(),
        bundle={"model_version": "test"},
        model_version="test",
        session_min={"consultation": 240, "surgery": 360},
        timezone=ZoneInfo("America/Santiago"),
        cne_starts=[time(8, 30), time(14, 0)],
        iq_start=time(8, 0),
    )


def test_run_experiment_smoke() -> None:
    """``run_experiment`` devuelve las 4 políticas con réplicas y el aviso en el payload."""
    config = SimulationConfig(weeks=2, replica_seeds=DEFAULT_REPLICA_SEEDS[:2])
    payload = run_experiment(_world(), config)

    assert "sintéticos" in payload["disclaimer"]
    assert payload["run"]["id"]
    assert payload["replica_seeds"] == [101, 102]
    assert len(payload["replicas"]) == 2
    for replica in payload["replicas"]:
        assert set(replica["policies"]) == set(POLICIES)
    assert set(payload["aggregate"]) == set(POLICIES)
    assert "optimized_vs_fifo" in payload["comparisons"]
