"""Mundo de la simulación: datos inmutables armados una vez desde una corrida sintética.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from noshow.train import load_verified_bundle  # type: ignore[import-untyped]
from priority.rules import RuleSet, load_default_rules
from shared.db.enums import NoShowScenario
from shared.schemas import CareType
from synthetic.capacity import Cell, capacity_cells, horizon_start, session_minutes
from synthetic.config import RunConfig
from synthetic.targets import load_assumptions, load_targets


def _read(run_dir: Path, name: str) -> pl.DataFrame:
    return pl.read_parquet(run_dir / f"{name}.parquet")


@dataclass(frozen=True)
class World:
    """Estado inicial y catálogos compartidos por todas las políticas y réplicas."""

    run_id: str
    as_of: date
    horizon_start: date
    size: int
    seed: int
    scenario: str
    truth_params: dict[str, Any]
    sigma_u: float
    median_wait: dict[tuple[int, str], float]
    stock: pl.DataFrame
    patient_frame: pl.DataFrame
    history: pl.DataFrame
    specialties: pl.DataFrame
    procedures: pl.DataFrame
    hospitals_by_service: dict[int, list[tuple[str, float]]]
    cells: list[Cell]
    rules: RuleSet
    bundle: dict[str, Any]
    model_version: str
    session_min: dict[str, int]
    timezone: ZoneInfo
    cne_starts: list[time]
    iq_start: time


def world_from_run(run_dir: Path, model_path: Path) -> World:
    """Arma el mundo desde ``data/.../<run_id>/`` y el modelo de inasistencias de esa corrida."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    run = manifest["run"]
    as_of = date.fromisoformat(run["as_of"])
    size = int(run["size"])
    seed = int(run["seed"])
    scenario = str(run["scenario"])
    truth_params = dict(run["params"]["noshow"])
    sigma_u = float(truth_params["sigma_u"])

    targets = load_targets()
    assumptions = load_assumptions()
    cfg = RunConfig(
        size=size,
        seed=seed,
        scenario=NoShowScenario(scenario),
        horizon_weeks=int(run["horizon_weeks"]),
        as_of=as_of,
    )
    stock = (
        _read(run_dir, "waitlist_entry")
        .filter(pl.col("status") == "waiting")
        .with_columns(pl.col("id").cast(pl.String), pl.col("patient_id").cast(pl.String))
    )
    cells = capacity_cells(targets, assumptions, cfg, stock)

    median_wait = {
        (r.health_service_code, r.care_type): float(r.median_wait_days)
        for r in targets.service_rows
    }

    patient = _read(run_dir, "patient").select(
        pl.col("id").cast(pl.String).alias("patient_id"),
        "age_group",
        "insurance",
        "commune_code",
    )
    latent = _read(run_dir, "patient_latent").select(
        pl.col("patient_id").cast(pl.String), "noshow_frailty"
    )
    patient_frame = patient.join(latent, on="patient_id", how="left")

    history = _read(run_dir, "appointment").select(
        pl.col("patient_id").cast(pl.String), "scheduled_start", pl.col("status").cast(pl.String)
    )
    specialties = _read(run_dir, "catalog_specialty")
    procedures = _read(run_dir, "catalog_procedure").select(
        pl.col("code").alias("procedure_code"), "duration_min"
    )

    hw = assumptions.value("hospital_complexity_weights")
    hospitals_by_service: dict[int, list[tuple[str, float]]] = {}
    for r in _read(run_dir, "catalog_establishment").sort("code").iter_rows(named=True):
        hospitals_by_service.setdefault(int(r["health_service_code"]), []).append(
            (str(r["code"]), float(hw.get(r["complexity"] or "", 1.0)))
        )

    rules = load_default_rules()
    bundle = load_verified_bundle(model_path)
    timezone = ZoneInfo(str(assumptions.value("timezone")))

    return World(
        run_id=str(run["id"]),
        as_of=as_of,
        horizon_start=horizon_start(as_of),
        size=size,
        seed=seed,
        scenario=scenario,
        truth_params=truth_params,
        sigma_u=sigma_u,
        median_wait=median_wait,
        stock=stock,
        patient_frame=patient_frame,
        history=history,
        specialties=specialties,
        procedures=procedures,
        hospitals_by_service=hospitals_by_service,
        cells=cells,
        rules=rules,
        bundle=bundle,
        model_version=str(bundle["model_version"]),
        session_min={
            CareType.CONSULTATION.value: session_minutes(assumptions, CareType.CONSULTATION.value),
            CareType.SURGERY.value: session_minutes(assumptions, CareType.SURGERY.value),
        },
        timezone=timezone,
        cne_starts=[time.fromisoformat(x) for x in assumptions.value("cne_session_starts")],
        iq_start=time.fromisoformat(assumptions.value("iq_block_start")),
    )
