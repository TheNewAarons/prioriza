"""Verdad sintética de inasistencias: probabilidad por cita y historial de asistencia.

logit p_ij = alpha_{s,c} + gamma_spec(j) + beta_age[a_i] + beta_ins[ins_i]
             + beta_wait·log2(W_ij / M_{s,c}) + beta_lead·log2(1 + lead/7) + u_i

El generador usa edad (y previsión solo en el escenario ``ses_gradient``); sexo, etnia,
nacionalidad y comuna no entran. ``u_i`` y ``p`` son verdad sintética: prohibidos como
feature del modelo de inasistencias.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import numpy as np
import polars as pl
from shared.db.enums import NoShowScenario
from shared.schemas import CareType

from synthetic.catalog import procedure_durations, specialty_index
from synthetic.config import RunConfig
from synthetic.rng import Stream, rng_for
from synthetic.targets import (
    CNE,
    IQ,
    Assumptions,
    CalibrationTargets,
)

APPOINTMENT_COLUMNS = [
    "id",
    "run_id",
    "patient_id",
    "entry_id",
    "slot_id",
    "schedule_run_id",
    "origin",
    "status",
    "scheduled_start",
    "duration_min",
    "lead_days",
    "is_overbooked",
    "predicted_noshow_prob",
    "specialty_code",
]
TRUTH_COLUMNS = ["appointment_id", "run_id", "true_noshow_prob"]
LATENT_COLUMNS = ["patient_id", "run_id", "noshow_frailty"]

GroupKey = tuple[int, CareType]


@dataclass(frozen=True)
class NoShowParams:
    """Parámetros del generador de inasistencias (escenario, coeficientes e interceptos)."""

    scenario: NoShowScenario
    beta_age: dict[str, float]
    beta_ins: dict[str, float]
    gamma: dict[str, float]
    beta_wait: float
    beta_lead: float
    sigma_u: float
    ref_lead_days: int
    intercepts: dict[GroupKey, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Representación JSON-compatible (para ``synthetic_run.params``)."""
        return {
            "scenario": self.scenario.value,
            "beta_age": dict(self.beta_age),
            "beta_ins": dict(self.beta_ins),
            "gamma": dict(sorted(self.gamma.items())),
            "beta_wait": self.beta_wait,
            "beta_lead": self.beta_lead,
            "sigma_u": self.sigma_u,
            "ref_lead_days": self.ref_lead_days,
            "intercepts": {f"{s}:{c.value}": v for (s, c), v in sorted(self.intercepts.items())},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> NoShowParams:
        """Reconstruye los parámetros desde ``to_json`` (la simulación recalcula p futura)."""
        intercepts: dict[GroupKey, float] = {}
        for key, v in data["intercepts"].items():
            s, c = key.split(":")
            intercepts[(int(s), CareType(c))] = float(v)
        return cls(
            scenario=NoShowScenario(data["scenario"]),
            beta_age=dict(data["beta_age"]),
            beta_ins=dict(data["beta_ins"]),
            gamma=dict(data["gamma"]),
            beta_wait=float(data["beta_wait"]),
            beta_lead=float(data["beta_lead"]),
            sigma_u=float(data["sigma_u"]),
            ref_lead_days=int(data["ref_lead_days"]),
            intercepts=intercepts,
        )


def build_params(t: CalibrationTargets, a: Assumptions, cfg: RunConfig) -> NoShowParams:
    """Parámetros del escenario; los efectos por especialidad usan el stream SPEC_EFFECTS."""
    sc = a.value("noshow_scenarios")[cfg.scenario.value]
    rng = rng_for(cfg.seed, Stream.SPEC_EFFECTS)
    codes = sorted(specialty_index(t))
    draws = rng.normal(0.0, 1.0, size=len(codes))  # se consumen siempre, también en neutral
    gamma = {c: float(d) * float(sc["gamma_sd"]) for c, d in zip(codes, draws, strict=True)}
    return NoShowParams(
        scenario=cfg.scenario,
        beta_age={k: float(v) for k, v in sc["beta_age"].items()},
        beta_ins={k: float(v) for k, v in sc["beta_ins"].items()},
        gamma=gamma,
        beta_wait=float(sc["beta_wait"]),
        beta_lead=float(sc["beta_lead"]),
        sigma_u=float(a.value("noshow_sigma_u")),
        ref_lead_days=int(a.value("noshow_ref_lead_days")),
    )


def noshow_rates(t: CalibrationTargets, a: Assumptions) -> dict[GroupKey, float]:
    """Tasas objetivo t_{s,c}: CNE con Arica/Iquique fijos y resto con tasa común; IQ constante."""
    national = float(a.value("noshow_rate_cne_national"))
    overrides = {int(k): float(v) for k, v in a.value("noshow_rate_overrides").items()}
    cne = {r.health_service_code: r.waiting_count for r in t.service_rows if r.care_type == CNE}
    total = sum(cne.values())
    fixed = sum(cne[s] * overrides[s] for s in overrides if s in cne)
    others = sum(v for s, v in cne.items() if s not in overrides)
    common = (national * total - fixed) / others
    out: dict[GroupKey, float] = {}
    for s in sorted(cne):
        out[(s, CareType.CONSULTATION)] = overrides.get(s, common)
    iq_rate = float(a.value("noshow_rate_iq"))
    for r in sorted(t.service_rows, key=lambda x: x.health_service_code):
        if r.care_type == IQ:
            out[(r.health_service_code, CareType.SURGERY)] = iq_rate
    return out


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def true_noshow_prob(
    features: pl.DataFrame, frailty: np.ndarray, params: NoShowParams
) -> np.ndarray:
    """Probabilidad verdadera de inasistencia por fila.

    Columnas de ``features``: ``intercept``, ``specialty_code``, ``age_group``, ``insurance``,
    ``wait_days``, ``median_wait_days`` y ``lead_days``.
    """
    return _sigmoid(_linear_predictor(features, frailty, params))


def _linear_predictor(
    features: pl.DataFrame, frailty: np.ndarray, params: NoShowParams
) -> np.ndarray:
    """Logit de la probabilidad de inasistencia."""
    spec = features["specialty_code"].replace_strict(params.gamma, return_dtype=pl.Float64)
    age = features["age_group"].replace_strict(params.beta_age, return_dtype=pl.Float64)
    ins = features["insurance"].replace_strict(params.beta_ins, return_dtype=pl.Float64)
    wait = features["wait_days"].to_numpy().astype(np.float64)
    med = features["median_wait_days"].to_numpy().astype(np.float64)
    lead = features["lead_days"].to_numpy().astype(np.float64)
    z = (
        features["intercept"].to_numpy().astype(np.float64)
        + spec.to_numpy()
        + age.to_numpy()
        + ins.to_numpy()
        + params.beta_wait * np.log2(np.maximum(wait, 1.0) / np.maximum(med, 1.0))
        + params.beta_lead * np.log2(1.0 + lead / 7.0)
        + frailty
    )
    return z


def draw_frailty(cfg: RunConfig, sigma_u: float, n_patients: int) -> np.ndarray:
    """Fragilidad individual u_i ~ N(0, sigma_u²) con el stream LATENT."""
    return rng_for(cfg.seed, Stream.LATENT).normal(0.0, sigma_u, size=n_patients)


def _as_of(cfg: RunConfig, a: Assumptions) -> date:
    return cfg.as_of if cfg.as_of is not None else date.fromisoformat(a.value("as_of"))


def with_wait(entries: pl.DataFrame, t: CalibrationTargets, as_of: date) -> pl.DataFrame:
    """Agrega ``wait_days`` (espera a ``as_of``) y ``median_wait_days`` del grupo."""
    median = pl.DataFrame(
        {
            "health_service_code": [r.health_service_code for r in t.service_rows],
            "care_type": [r.care_type for r in t.service_rows],
            "median_wait_days": [r.median_wait_days for r in t.service_rows],
        },
        schema={
            "health_service_code": pl.Int64,
            "care_type": pl.String,
            "median_wait_days": pl.Float64,
        },
    )
    out = entries.join(
        median, on=["health_service_code", "care_type"], how="left", maintain_order="left"
    ).with_columns((pl.lit(as_of) - pl.col("entry_date")).dt.total_days().alias("wait_days"))
    return out.with_columns(
        pl.col("median_wait_days").fill_null(pl.col("wait_days").cast(pl.Float64))
    )


def entry_features(
    entries: pl.DataFrame,
    patients: pl.DataFrame,
    t: CalibrationTargets,
    as_of: date,
) -> pl.DataFrame:
    """Une entradas (con espera) y pacientes: base de las features de la verdad sintética."""
    cols = ["id", "age_group", "insurance"]
    if "noshow_frailty" in patients.columns:
        cols.append("noshow_frailty")
    pat = patients.select(cols).rename({"id": "patient_id"})
    base = entries if "wait_days" in entries.columns else with_wait(entries, t, as_of)
    return base.join(pat, on="patient_id", how="left", maintain_order="left")


def calibrate_intercepts(
    entries: pl.DataFrame,
    patients: pl.DataFrame,
    params: NoShowParams,
    rates: dict[GroupKey, float],
) -> dict[GroupKey, float]:
    """Intercepto alpha_{s,c} por bisección para que la media de p dé la tasa objetivo.

    ``entries`` puede traer ``wait_days`` y ``median_wait_days`` (si no, el término de
    espera vale 0); ``patients`` puede traer ``noshow_frailty`` (si no, se usa 0). La media
    se evalúa con la anticipación de referencia ``params.ref_lead_days``.
    """
    pat_cols = ["id", "age_group", "insurance"]
    if "noshow_frailty" in patients.columns:
        pat_cols.append("noshow_frailty")
    df = entries.join(
        patients.select(pat_cols).rename({"id": "patient_id"}),
        on="patient_id",
        how="left",
        maintain_order="left",
    )
    n = df.height
    frailty = (
        df["noshow_frailty"].to_numpy().astype(np.float64)
        if "noshow_frailty" in df.columns
        else np.zeros(n)
    )
    if "wait_days" in df.columns and "median_wait_days" in df.columns:
        wait = df["wait_days"].to_numpy().astype(np.float64)
        med = df["median_wait_days"].to_numpy().astype(np.float64)
    else:
        wait = med = np.ones(n)
    feats = pl.DataFrame(
        {
            "intercept": np.zeros(n),
            "specialty_code": df["specialty_code"],
            "age_group": df["age_group"],
            "insurance": df["insurance"],
            "wait_days": wait,
            "median_wait_days": med,
            "lead_days": np.full(n, float(params.ref_lead_days)),
        }
    )
    base = _linear_predictor(feats, frailty, params)
    svc = df["health_service_code"].to_numpy()
    care = df["care_type"].to_numpy()
    out: dict[GroupKey, float] = {}
    for (s, c), rate in sorted(rates.items()):
        mask = (svc == s) & (care == c.value)
        if not mask.any():
            continue
        b = base[mask]
        lo, hi = -40.0, 40.0
        for _ in range(100):
            mid = 0.5 * (lo + hi)
            if _sigmoid(b + mid).mean() < rate:
                lo = mid
            else:
                hi = mid
        out[(s, c)] = 0.5 * (lo + hi)
    return out


def generate_history(
    patients: pl.DataFrame,
    entries: pl.DataFrame,
    params: NoShowParams,
    cfg: RunConfig,
    run_id: UUID,
    targets: CalibrationTargets,
    assumptions: Assumptions,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Historial de asistencia: ``appointment``, ``appointment_truth`` y ``patient_latent``.

    Si ``patients`` no trae ``noshow_frailty`` se sortea con el stream LATENT; si
    ``params.intercepts`` está vacío se calibran contra los objetivos versionados.
    """
    t, a = targets, assumptions
    as_of = _as_of(cfg, a)
    n_pat = patients.height
    if "noshow_frailty" in patients.columns:
        frailty = patients["noshow_frailty"].to_numpy().astype(np.float64)
    else:
        frailty = draw_frailty(cfg, params.sigma_u, n_pat)
        patients = patients.with_columns(pl.Series("noshow_frailty", frailty))
    entries_w = entries if "wait_days" in entries.columns else with_wait(entries, t, as_of)
    feats = entry_features(entries_w, patients, t, as_of)
    if not params.intercepts:
        params = replace(
            params, intercepts=calibrate_intercepts(entries_w, patients, params, noshow_rates(t, a))
        )
    rng = rng_for(cfg.seed, Stream.HISTORY)
    lam = float(a.value("history_poisson_lambda"))
    kmax = int(a.value("history_max_appointments"))
    window = int(a.value("history_window_days"))
    lead_lo, lead_hi = (int(x) for x in a.value("history_lead_range_days"))

    k = np.minimum(rng.poisson(lam, size=n_pat), kmax)
    pat_idx = np.repeat(np.arange(n_pat), k)
    total = len(pat_idx)
    days_before = rng.integers(1, window + 1, size=total)
    lead = rng.integers(lead_lo, lead_hi + 1, size=total)
    pick = rng.random(total)
    outcome = rng.random(total)

    # entradas de cada paciente (ordenadas por paciente) para elegir la especialidad
    pid_index = {pid: i for i, pid in enumerate(patients["id"].to_list())}
    entry_pat = np.array([pid_index[p] for p in entries["patient_id"].to_list()], dtype=np.int64)
    order = np.argsort(entry_pat, kind="stable")
    counts = np.bincount(entry_pat, minlength=n_pat)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    chosen = order[starts[pat_idx] + np.floor(pick * counts[pat_idx]).astype(np.int64)]

    sel = feats[chosen.tolist()]
    group_alpha = {(s, c.value): v for (s, c), v in params.intercepts.items()}
    alpha = np.array(
        [
            group_alpha[(s, c)]
            for s, c in zip(sel["health_service_code"], sel["care_type"], strict=True)
        ]
    )
    hist_feats = pl.DataFrame(
        {
            "intercept": alpha,
            "specialty_code": sel["specialty_code"],
            "age_group": sel["age_group"],
            "insurance": sel["insurance"],
            "wait_days": np.ones(total),  # término de espera 0 en el historial
            "median_wait_days": np.ones(total),
            "lead_days": lead.astype(np.float64),
        }
    )
    p = true_noshow_prob(hist_feats, frailty[pat_idx], params)
    no_show = outcome < p

    durations = procedure_durations(t, a)
    duration = np.array([durations[c] for c in sel["procedure_code"]], dtype=np.int64)
    # citas a las 12:00 UTC del día correspondiente (la hora local exacta no es relevante)
    base = datetime(as_of.year, as_of.month, as_of.day, 12, tzinfo=UTC)
    starts_at = [base - timedelta(days=int(d)) for d in days_before]
    run_s = str(run_id)
    appt_ids = [str(uuid.uuid5(run_id, f"appointment:{i}")) for i in range(total)]
    pat_ids = patients["id"].to_numpy()
    appointment = pl.DataFrame(
        {
            "id": appt_ids,
            "run_id": [run_s] * total,
            "patient_id": pat_ids[pat_idx].tolist(),
            "entry_id": [None] * total,
            "slot_id": [None] * total,
            "schedule_run_id": [None] * total,
            "origin": ["history"] * total,
            "status": np.where(no_show, "no_show", "attended").tolist(),
            "scheduled_start": starts_at,
            "duration_min": duration,
            "lead_days": lead,
            "is_overbooked": np.zeros(total, dtype=bool),
            "predicted_noshow_prob": [None] * total,
            "specialty_code": sel["specialty_code"].to_list(),
        },
        schema={
            "id": pl.String,
            "run_id": pl.String,
            "patient_id": pl.String,
            "entry_id": pl.String,
            "slot_id": pl.String,
            "schedule_run_id": pl.String,
            "origin": pl.String,
            "status": pl.String,
            "scheduled_start": pl.Datetime("us", "UTC"),
            "duration_min": pl.Int64,
            "lead_days": pl.Int64,
            "is_overbooked": pl.Boolean,
            "predicted_noshow_prob": pl.Float64,
            "specialty_code": pl.String,
        },
    ).select(APPOINTMENT_COLUMNS)
    truth = pl.DataFrame(
        {"appointment_id": appt_ids, "run_id": [run_s] * total, "true_noshow_prob": p},
        schema={"appointment_id": pl.String, "run_id": pl.String, "true_noshow_prob": pl.Float64},
    ).select(TRUTH_COLUMNS)
    latent = pl.DataFrame(
        {"patient_id": pat_ids.tolist(), "run_id": [run_s] * n_pat, "noshow_frailty": frailty},
        schema={"patient_id": pl.String, "run_id": pl.String, "noshow_frailty": pl.Float64},
    ).select(LATENT_COLUMNS)
    return appointment, truth, latent
