"""Orquestación pura (sin E/S) de la generación: población, inasistencias y oferta."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

import polars as pl

from synthetic import GENERATOR_VERSION
from synthetic.capacity import generate_capacity, horizon_start
from synthetic.catalog import build_catalogs
from synthetic.config import RunConfig
from synthetic.digest import dataset_digest
from synthetic.noshow_truth import (
    build_params,
    calibrate_intercepts,
    draw_frailty,
    generate_history,
    noshow_rates,
    with_wait,
)
from synthetic.population import generate_population, resolve_as_of
from synthetic.targets import (
    Assumptions,
    CalibrationTargets,
    load_assumptions,
    load_targets,
    sha256_text,
)
from synthetic.universe import build_universe

RUN_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://prioriza.invalid/synthetic-run")


@dataclass(frozen=True)
class SyntheticDataset:
    """Resultado de una corrida: metadatos de la corrida, catálogos, tablas y digest."""

    run: dict[str, object]
    catalogs: dict[str, pl.DataFrame]
    tables: dict[str, pl.DataFrame]
    digest: str


def run_id_for(cfg: RunConfig, as_of: str, targets_sha: str, params_sha: str) -> uuid.UUID:
    """Id determinista: uuid5 de ``seed:size:scenario:horizon:as_of:targets_sha:params_sha``."""
    name = (
        f"{cfg.seed}:{cfg.size}:{cfg.scenario.value}:{cfg.horizon_weeks}:"
        f"{as_of}:{targets_sha}:{params_sha}"
    )
    return uuid.uuid5(RUN_NAMESPACE, name)


def generate(
    cfg: RunConfig,
    targets: CalibrationTargets | None = None,
    assumptions: Assumptions | None = None,
) -> SyntheticDataset:
    """Genera el conjunto de datos completo. Es puro: no lee ni escribe archivos ni la BD."""
    t = targets or load_targets()
    a = assumptions or load_assumptions()
    as_of = resolve_as_of(cfg, a)
    targets_sha = sha256_text(t)
    params_sha = sha256_text(a)
    run_id = run_id_for(cfg, as_of.isoformat(), targets_sha, params_sha)

    patient, entry = generate_population(t, a, cfg, run_id)

    params = build_params(t, a, cfg)
    frailty = draw_frailty(cfg, params.sigma_u, patient.height)
    patient_f = patient.with_columns(pl.Series("noshow_frailty", frailty))
    entry_w = with_wait(entry, t, as_of)
    intercepts = calibrate_intercepts(entry_w, patient_f, params, noshow_rates(t, a))
    params = replace(params, intercepts=intercepts)
    appointment, truth, latent = generate_history(patient_f, entry_w, params, cfg, run_id, t, a)

    resource, slot = generate_capacity(t, a, cfg, entry, run_id)

    tables = {
        "patient": patient,
        "patient_latent": latent,
        "waitlist_entry": entry,
        "resource": resource,
        "slot": slot,
        "appointment": appointment,
        "appointment_truth": truth,
    }
    catalogs = build_catalogs(t, a)
    digest = dataset_digest({**tables, **{f"catalog_{k}": v for k, v in catalogs.items()}})
    uni = build_universe(t, a)
    run_params: dict[str, Any] = {
        "noshow": params.to_json(),
        "horizon_start": horizon_start(as_of).isoformat(),
        "ges_coverage_of_delayed": uni.ges_coverage,
        "unverified_assumptions": a.unverified(),
    }
    run: dict[str, object] = {
        "id": str(run_id),
        "seed": cfg.seed,
        "size": cfg.size,
        "scenario": cfg.scenario.value,
        "as_of": as_of.isoformat(),
        "horizon_weeks": cfg.horizon_weeks,
        "reference_source_id": t.reference_source_id,
        "targets_sha256": targets_sha,
        "params_sha256": params_sha,
        "dataset_sha256": digest,
        "generator_version": GENERATOR_VERSION,
        "params": run_params,
        "status": "ready",
    }
    return SyntheticDataset(run=run, catalogs=catalogs, tables=tables, digest=digest)
