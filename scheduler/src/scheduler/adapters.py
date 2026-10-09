"""Adaptador: arma la instancia desde una corrida sintética en parquet (formulación §2).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Es la única parte de ``scheduler`` que usa ``priority.rank_frame`` sobre tablas y el modelo de
inasistencias (``noshow``, sin anotaciones de tipo). Los atributos de equidad se leen con la
función de ``noshow`` que respeta su lista de tablas permitidas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from noshow.data import load_fairness_attributes  # type: ignore[import-untyped]
from noshow.features import build_candidate_features  # type: ignore[import-untyped]
from noshow.train import load_bundle, predict_noshow  # type: ignore[import-untyped]
from priority.adapters import rank_frame

from priority import RuleSet, load_default_rules
from scheduler.config import SchedulerConfig
from scheduler.instance import SchedulingInstance

LOCAL_TZ_NAME = "America/Santiago"


@dataclass(frozen=True)
class RunInfo:
    """Identidad de la corrida sintética usada."""

    run_dir: Path
    run_id: str
    as_of: date
    horizon_start: date
    manifest_run: dict[str, Any]


def read_run_info(run_dir: Path) -> RunInfo:
    """Lee ``manifest.json``: id, ``as_of`` e inicio del horizonte de la corrida."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    run = manifest["run"]
    return RunInfo(
        run_dir=run_dir,
        run_id=str(run["id"]),
        as_of=date.fromisoformat(run["as_of"]),
        horizon_start=date.fromisoformat(run["params"]["horizon_start"]),
        manifest_run=run,
    )


def _read(run_dir: Path, name: str) -> pl.DataFrame:
    return pl.read_parquet(run_dir / f"{name}.parquet")


def _place(config: SchedulerConfig, df: pl.DataFrame) -> pl.Expr:
    if config.match_level == "health_service":
        return pl.lit("s:") + pl.col("health_service_code").cast(pl.String)
    return pl.lit("e:") + pl.col("establishment_code").cast(pl.String)


def entries_frame(run_dir: Path, rules: RuleSet, as_of: date) -> pl.DataFrame:
    """Tabla ``entries`` (§2.2) con el puntaje S y el puesto P4 de cada entrada en espera."""
    we = _read(run_dir, "waitlist_entry").filter(pl.col("status") == "waiting")
    we = we.with_columns(pl.col("id").cast(pl.String), pl.col("patient_id").cast(pl.String))
    proc = _read(run_dir, "catalog_procedure").select(
        pl.col("code").alias("procedure_code"), "duration_min"
    )
    rankings = rank_frame(we, rules, as_of=as_of)
    scores = pl.DataFrame(
        [
            (r.score.entry_id, r.score.score, r.rank)
            for ranking in rankings.values()
            for r in ranking.entries
        ],
        schema={"entry_id": pl.String, "score": pl.Float64, "rank": pl.Int64},
        orient="row",
    )
    return (
        we.join(proc, on="procedure_code", how="left")
        .rename({"id": "entry_id"})
        .join(scores, on="entry_id", how="left")
        .select(
            "entry_id",
            "patient_id",
            "health_service_code",
            "establishment_code",
            "specialty_code",
            pl.col("care_type").cast(pl.String),
            "duration_min",
            pl.col("clinical_priority").cast(pl.String),
            "is_ges",
            "ges_deadline",
            "entry_date",
            "score",
            "rank",
        )
    )


def blocks_frame(run_dir: Path, config: SchedulerConfig, horizon_start: date) -> pl.DataFrame:
    """Tabla ``blocks`` (§2.2) del horizonte, con capacidad ya reservada por citas vigentes."""
    end = horizon_start + timedelta(days=7 * config.horizon_weeks)
    slot = _read(run_dir, "slot").with_columns(
        pl.col("id").cast(pl.String).alias("slot_id"), pl.col("resource_id").cast(pl.String)
    )
    resource = _read(run_dir, "resource").select(
        pl.col("id").cast(pl.String).alias("resource_id"),
        pl.col("kind").cast(pl.String).alias("resource_kind"),
        "establishment_code",
        "health_service_code",
    )
    local = pl.col("start_at").dt.convert_time_zone(LOCAL_TZ_NAME).dt.date()
    blocks = (
        slot.join(resource, on="resource_id", how="left")
        .with_columns(local.alias("local_date"))
        .filter((pl.col("local_date") >= horizon_start) & (pl.col("local_date") < end))
    )
    appt = _read(run_dir, "appointment")
    pre = (
        appt.filter(
            pl.col("slot_id").is_not_null()
            & (pl.col("status") == "scheduled")
            & (pl.col("origin") != "history")
        )
        .with_columns(pl.col("slot_id").cast(pl.String))
        .join(blocks.select("slot_id", "unit_min"), on="slot_id", how="inner")
        .group_by("slot_id")
        .agg(
            (pl.col("duration_min") / pl.col("unit_min"))
            .ceil()
            .sum()
            .cast(pl.Int64)
            .alias("prebooked_units"),
            (pl.col("duration_min") + config.or_turnover_min)
            .sum()
            .cast(pl.Int64)
            .alias("prebooked_min"),
        )
    )
    blocks = blocks.join(pre, on="slot_id", how="left").with_columns(
        pl.when(pl.col("resource_kind") == "specialist_agenda")
        .then(pl.col("prebooked_units").fill_null(0))
        .otherwise(0)
        .alias("prebooked_units"),
        pl.when(pl.col("resource_kind") == "operating_room")
        .then(pl.col("prebooked_min").fill_null(0))
        .otherwise(0)
        .alias("prebooked_min"),
    )
    return blocks.select(
        "slot_id",
        "resource_id",
        "resource_kind",
        "health_service_code",
        "establishment_code",
        "specialty_code",
        "start_at",
        "duration_min",
        "unit_min",
        "prebooked_units",
        "prebooked_min",
    ).sort("slot_id")


def noshow_frame(
    run_dir: Path,
    entries: pl.DataFrame,
    blocks: pl.DataFrame,
    config: SchedulerConfig,
    as_of: date,
    model_path: Path,
) -> tuple[pl.DataFrame, str]:
    """Tabla ``noshow`` (§2.2) para los pares CNE de misma especialidad y lugar.

    Usa ``noshow.build_candidate_features`` con ``scheduled_start = start_at`` del bloque,
    ``lead_days = (fecha local del bloque - as_of)`` y el historial observado hasta ``as_of``.
    """
    bundle = load_bundle(model_path)
    min_lead = min(config.min_lead_days, config.ges_min_lead_days)
    cne_e = entries.filter(pl.col("care_type") == "consultation").with_columns(
        _place(config, entries).alias("place")
    )
    cne_b = blocks.filter(pl.col("resource_kind") == "specialist_agenda").with_columns(
        _place(config, blocks).alias("place"),
        pl.col("start_at").dt.convert_time_zone(LOCAL_TZ_NAME).dt.date().alias("local_date"),
    )
    pairs = (
        cne_e.select("entry_id", "patient_id", "place", "specialty_code")
        .join(
            cne_b.select("slot_id", "place", "specialty_code", "start_at", "local_date"),
            on=["place", "specialty_code"],
            how="inner",
        )
        .with_columns((pl.col("local_date") - pl.lit(as_of)).dt.total_days().alias("lead_days"))
        .filter(pl.col("lead_days") >= min_lead)
        .with_columns((pl.col("entry_id") + "|" + pl.col("slot_id")).alias("id"))
    )
    if pairs.is_empty():
        return pl.DataFrame(
            schema={"entry_id": pl.String, "slot_id": pl.String, "p": pl.Float64}
        ), str(bundle["model_version"])
    history = _read(run_dir, "appointment").select(
        pl.col("patient_id").cast(pl.String), "scheduled_start", pl.col("status").cast(pl.String)
    )
    specialties = _read(run_dir, "catalog_specialty")
    candidates = pairs.select(
        "id",
        "entry_id",
        "patient_id",
        pl.col("start_at").alias("scheduled_start"),
        "lead_days",
        "specialty_code",
    )
    waitlist = entries.select(pl.col("entry_id").alias("id"), "entry_date")
    features = build_candidate_features(candidates, history, specialties, waitlist)
    probs = predict_noshow(bundle, features)
    out = pairs.select("entry_id", "slot_id").with_columns(pl.Series("p", probs, dtype=pl.Float64))
    return out, str(bundle["model_version"])


def instance_from_run(
    run_dir: Path,
    config: SchedulerConfig,
    *,
    models_dir: Path = Path("models/noshow"),
    rules: RuleSet | None = None,
    seed: int = 42,
) -> tuple[SchedulingInstance, RunInfo]:
    """Instancia completa desde ``data/synthetic/<run_id>/`` y el modelo de esa corrida."""
    info = read_run_info(run_dir)
    rules = rules or load_default_rules()
    entries = entries_frame(run_dir, rules, info.as_of)
    blocks = blocks_frame(run_dir, config, info.horizon_start)
    noshow: pl.DataFrame | None = None
    model_version: str | None = None
    if config.overbooking.enabled:
        model_path = models_dir / info.run_id / "noshow_model.joblib"
        if not model_path.exists():
            raise FileNotFoundError(
                f"no existe el modelo de inasistencias {model_path}; ejecuta `make train-noshow` "
                "o usa --no-overbooking"
            )
        noshow, model_version = noshow_frame(
            run_dir, entries, blocks, config, info.as_of, model_path
        )
    groups = load_fairness_attributes(run_dir).with_columns(pl.col("patient_id").cast(pl.String))
    instance = SchedulingInstance.from_frames(
        as_of=info.as_of,
        horizon_start=info.horizon_start,
        entries=entries,
        blocks=blocks,
        noshow=noshow,
        groups=groups,
        rules_digest=rules.digest(),
        rules_version=rules.rules_version,
        yield_priorities=[str(p) for p in rules.ges_strict.yield_to_priorities],
        noshow_model_version=model_version,
        seed=seed,
    )
    return instance, info
