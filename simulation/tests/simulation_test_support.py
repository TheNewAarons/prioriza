"""Mundos chicos armados a mano para los tests de la simulación (sin generador ni archivos).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

import uuid
from datetime import date, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest
from priority.rules import load_default_rules
from simulation.world import World
from synthetic.capacity import Cell, horizon_start

AS_OF = date(2026, 1, 4)  # domingo: el reloj parte el lunes 2026-01-05
SPEC = "cne_medical:x"
IQ_SPEC = "iq:y"
STOCK_SCHEMA = {
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
}


def make_world(
    *,
    n_stock: int = 5,
    sessions_per_week: float = 1.0,
    arrivals_per_week: float = 0.0,
    intercept: float = -40.0,
    surgery: bool = False,
    ges_every: int = 0,
    groups: tuple[str, ...] = ("a1",),
) -> World:
    """Un servicio y una especialidad CNE (o de pabellón con ``surgery``).

    ``intercept`` fija la probabilidad verdadera de inasistencia (-40: nadie falta; +40: todos
    faltan; 0: la mitad), sin fragilidad ni otros efectos. La entrada ``k`` del stock ingresó
    ``200 + k`` días antes de ``AS_OF`` (la ``e000`` es la más nueva); con ``ges_every`` > 0 una
    de cada ``ges_every`` es GES con plazo a 60 días de ``AS_OF``. Los pacientes se reparten
    entre los valores de ``groups`` (edad, previsión y comuna iguales al valor).
    """
    care = "surgery" if surgery else "consultation"
    spec = IQ_SPEC if surgery else SPEC
    session = 360 if surgery else 240
    rows: list[dict[str, Any]] = []
    for k in range(n_stock):
        ges = ges_every > 0 and k % ges_every == 0
        rows.append(
            {
                "id": f"e{k:03d}",
                "patient_id": f"p{k:03d}",
                "health_service_code": 1,
                "establishment_code": "h1",
                "specialty_code": spec,
                "procedure_code": "proc1",
                "care_type": care,
                "clinical_priority": "p3",
                "is_ges": ges,
                "ges_deadline": AS_OF + timedelta(days=60) if ges else None,
                "entry_date": AS_OF - timedelta(days=200 + k),
            }
        )
    stock = pl.DataFrame(rows, schema=STOCK_SCHEMA)
    patient_frame = pl.DataFrame(
        {
            "patient_id": [f"p{k:03d}" for k in range(n_stock)],
            "age_group": [groups[k % len(groups)] for k in range(n_stock)],
            "insurance": [groups[k % len(groups)] for k in range(n_stock)],
            "commune_code": [groups[k % len(groups)] for k in range(n_stock)],
            "noshow_frailty": [0.0] * n_stock,
        },
        schema={
            "patient_id": pl.String,
            "age_group": pl.String,
            "insurance": pl.String,
            "commune_code": pl.String,
            "noshow_frailty": pl.Float64,
        },
    )
    zeros = dict.fromkeys(groups, 0.0)
    truth_params = {
        "scenario": "baseline",
        "beta_age": zeros,
        "beta_ins": zeros,
        "gamma": {spec: 0.0},
        "beta_wait": 0.0,
        "beta_lead": 0.0,
        "sigma_u": 0.0,
        "ref_lead_days": 28,
        "intercepts": {f"1:{care}": intercept},
    }
    ges_rate = arrivals_per_week / ges_every if ges_every else 0.0
    cell = Cell(
        1,
        care,
        spec,
        n_stock,
        sessions_per_week * session,
        0 if surgery else 20,
        arrivals_per_week,
        ges_rate,
    )
    return World(
        run_id=str(uuid.UUID(int=7)),
        as_of=AS_OF,
        horizon_start=horizon_start(AS_OF),
        size=n_stock,
        seed=42,
        scenario="baseline",
        truth_params=truth_params,
        sigma_u=0.0,
        median_wait={(1, care): 200.0},
        stock=stock,
        patient_frame=patient_frame,
        history=pl.DataFrame(
            {
                "patient_id": pl.Series([], dtype=pl.String),
                "scheduled_start": pl.Series([], dtype=pl.Datetime("us", "UTC")),
                "status": pl.Series([], dtype=pl.String),
            }
        ),
        specialties=pl.DataFrame({"code": [spec], "care_type": [care]}),
        procedures=pl.DataFrame(
            {"procedure_code": ["proc1"], "duration_min": [60 if surgery else 20]},
            schema={"procedure_code": pl.String, "duration_min": pl.Int64},
        ),
        hospitals_by_service={1: [("h1", 1.0)]},
        cells=[cell],
        rules=load_default_rules(),
        bundle={"model_version": "test"},
        model_version="test",
        session_min={"consultation": 240, "surgery": 360},
        timezone=ZoneInfo("America/Santiago"),
        cne_starts=[time(8, 30), time(14, 0)],
        iq_start=time(8, 0),
    )


def fake_prediction(monkeypatch: pytest.MonkeyPatch, p: float) -> None:
    """Reemplaza el modelo de inasistencias por una p predicha constante (sin artefacto)."""
    from scheduler import adapters

    monkeypatch.setattr(adapters, "build_candidate_features", lambda c, *_: c)
    monkeypatch.setattr(adapters, "predict_noshow", lambda _b, f: np.full(f.height, p))
