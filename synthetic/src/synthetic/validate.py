"""Validación de calibración: compara el conjunto generado con los objetivos públicos.

Chequeos estrictos (``strict``, fallan la validación), blandos (``soft``, solo avisan) y
omitidos por tamaño de muestra (``skipped``). Ver tolerancias C1-C9 en el plan de diseño.
Los resultados negativos se reportan tal cual.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel, Field
from shared.schemas import CareType

from synthetic.capacity import capacity_targets
from synthetic.catalog import specialty_index
from synthetic.config import RunConfig
from synthetic.distributions import needs_sigma_floor
from synthetic.io import DISCLAIMER
from synthetic.noshow_truth import (
    NoShowParams,
    entry_features,
    noshow_rates,
    true_noshow_prob,
    with_wait,
)
from synthetic.population import (
    AGE_ORDER,
    INSURANCE_ORDER,
    commune_weights,
    resolve_as_of,
)
from synthetic.rng import Stream, rng_for
from synthetic.targets import CNE, IQ, Assumptions, CalibrationTargets
from synthetic.universe import build_universe

if TYPE_CHECKING:
    from synthetic.pipeline import SyntheticDataset

Severity = Literal["strict", "soft", "skipped"]
MIN_GROUP = 30
MIN_HISTORY = 200


class Check(BaseModel):
    """Resultado de un chequeo de calibración."""

    name: str
    group: str
    metric: str
    observed: float | None
    target: float | None
    tolerance: float | None
    n: int
    passed: bool
    severity: Severity
    detail: list[str] = Field(default_factory=list)


class CalibrationReport(BaseModel):
    """Informe de calibración de una corrida."""

    run_id: str
    digest: str
    checks: list[Check]
    passed: bool
    summary: dict[str, int]
    notes: list[str] = Field(default_factory=list)


def _tvd(observed: dict[Any, float], expected: dict[Any, float]) -> float:
    keys = set(observed) | set(expected)
    return 0.5 * sum(abs(observed.get(k, 0.0) - expected.get(k, 0.0)) for k in keys)


def _normalize(w: dict[Any, float]) -> dict[Any, float]:
    s = sum(w.values())
    return {k: v / s for k, v in w.items()} if s > 0 else dict(w)


def _share(values: list[Any]) -> dict[Any, float]:
    n = len(values)
    out: dict[Any, float] = defaultdict(float)
    for v in values:
        out[v] += 1.0 / n
    return dict(out)


class _Collector:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, **kw: Any) -> None:
        self.checks.append(Check(**kw))

    def tvd_check(
        self,
        name: str,
        group: str,
        pairs: list[tuple[str, dict[Any, float], dict[Any, float], int, int]],
        factor: float = 0.5,
    ) -> None:
        """Una o varias comparaciones TVD; cota: factor·K/n + 1e-9 (factor 0,5 sin condicionar)."""
        worst_label = ""
        worst = (-1.0, 0.0, 0)
        failures: list[str] = []
        for label, obs, exp, n, k in pairs:
            if n == 0:
                continue
            tvd = _tvd(obs, exp)
            bound = factor * k / n + 1e-9
            if tvd > bound:
                failures.append(f"{label}: tvd={tvd:.5f} > {bound:.5f}")
            if tvd - bound > worst[0] or worst[0] < 0:
                worst_label, worst = label, (tvd - bound, tvd, n)
                worst_bound = bound
        if worst[0] < 0 and not pairs:
            return
        self.add(
            name=name,
            group=group,
            metric="tvd",
            observed=worst[1],
            target=0.0,
            tolerance=worst_bound if pairs else None,
            n=sum(p[3] for p in pairs),
            passed=not failures,
            severity="strict",
            detail=failures or [f"peor grupo: {worst_label}"],
        )


def _within(obs: float, target: float, rel: float, abs_tol: float = 0.0) -> bool:
    return abs(obs - target) <= max(rel * abs(target), abs_tol) + 1e-9


def calibration_report(
    ds: SyntheticDataset, targets: CalibrationTargets, assumptions: Assumptions
) -> CalibrationReport:
    """Calcula el informe de calibración C1-C9 de un conjunto de datos generado."""
    t, a = targets, assumptions
    tbl = ds.tables
    run = ds.run
    cfg = RunConfig(
        size=int(str(run["size"])),
        seed=int(str(run["seed"])),
        horizon_weeks=int(str(run["horizon_weeks"])),
        as_of=date.fromisoformat(str(run["as_of"])),
    )
    as_of = resolve_as_of(cfg, a)
    h = cfg.horizon_weeks
    entry = tbl["waitlist_entry"]
    patient = tbl["patient"]
    latent = tbl["patient_latent"]
    specs = specialty_index(t)
    uni = build_universe(t, a)
    col = _Collector()
    notes: list[str] = []

    entry_w = with_wait(entry, t, as_of)
    ordinary = entry_w.filter(~pl.col("is_ges"))
    cne = ordinary.filter(pl.col("care_type") == CNE)
    iq = ordinary.filter(pl.col("care_type") == IQ)
    ges = entry_w.filter(pl.col("is_ges"))
    n_all = entry.height

    # ---------------------------------------------------------------- C1 (TVD)
    kind_obs = _share(
        [
            "ges" if g else ("cne" if c == CNE else "iq")
            for g, c in zip(entry["is_ges"].to_list(), entry["care_type"].to_list(), strict=True)
        ]
    )
    kind_exp = _normalize({"cne": uni.l_cne, "iq": uni.l_iq, "ges": uni.l_ges})
    col.tvd_check("C1.tipo", "C1", [("tipo", kind_obs, kind_exp, n_all, 3)])

    for label, frame, ct in (("cne", cne, CNE), ("iq", iq, IQ)):
        exp = _normalize(
            {
                r.health_service_code: float(r.waiting_count)
                for r in t.service_rows
                if r.care_type == ct
            }
        )
        col.tvd_check(
            f"C1.servicio|{label}",
            "C1",
            [(label, _share(frame["health_service_code"].to_list()), exp, frame.height, len(exp))],
        )

    for gname, frame in (
        ("cne_medical", cne.filter(pl.col("care_subtype") == "medical")),
        ("cne_dental", cne.filter(pl.col("care_subtype") == "dental")),
        ("iq", iq),
    ):
        from synthetic.taxonomy import specialty_code as _sc

        exp = _normalize(
            {
                _sc(r.group, r.name): float(r.waiting_count)
                for r in t.specialties
                if r.group == gname
            }
        )
        # condicionar por subtipo duplica la cota (ver docstring de la sección 5)
        factor = 1.0 if gname.startswith("cne") else 0.5
        col.tvd_check(
            f"C1.especialidad|{gname}",
            "C1",
            [(gname, _share(frame["specialty_code"].to_list()), exp, frame.height, len(exp))],
            factor=factor,
        )

    cells = len(uni.ges) * 2
    ges_exp = _normalize({g.code: g.delayed_count + g.in_deadline_weight for g in uni.ges})
    col.tvd_check(
        "C1.problema|ges",
        "C1",
        [("ges", _share(ges["ges_problem_code"].to_list()), ges_exp, ges.height, cells)],
        factor=0.5,
    )
    ges_svc_exp = _normalize(
        {s.health_service_code: float(s.waiting_count) for s in t.ges_services}
    )
    col.tvd_check(
        "C1.servicio|ges",
        "C1",
        [
            (
                "ges",
                _share(ges["health_service_code"].to_list()),
                ges_svc_exp,
                ges.height,
                len(ges_svc_exp),
            )
        ],
    )

    comm_w = commune_weights(t, a)
    pairs = []
    for svc, frame in patient.group_by("health_service_code", maintain_order=True):
        s = int(svc[0])  # type: ignore[index]
        exp = _normalize(comm_w[s])
        pairs.append(
            (f"servicio {s}", _share(frame["commune_code"].to_list()), exp, frame.height, len(exp))
        )
    col.tvd_check("C1.comuna|servicio", "C1", pairs)

    ent_pat = entry.select("id", "patient_id", "specialty_code").join(
        patient.select(pl.col("id").alias("patient_id"), "age_group"), on="patient_id"
    )
    cls_pairs = []
    for is_ped in (True, False):
        codes = [c for c, i in specs.items() if i.pediatric == is_ped]
        frame = ent_pat.filter(pl.col("specialty_code").is_in(codes))
        mix = _normalize(dict(a.value("pediatric_age_mix" if is_ped else "general_age_mix")))
        mix = {k: v for k, v in mix.items() if k in AGE_ORDER}
        cls_pairs.append(
            (
                "pediátrica" if is_ped else "general",
                _share(frame["age_group"].to_list()),
                mix,
                frame.height,
                len(AGE_ORDER),
            )
        )
    col.tvd_check("C1.edad|clase", "C1", cls_pairs)
    ins_mix = a.insurance_mix()
    col.tvd_check(
        "C1.previsión",
        "C1",
        [
            (
                "pacientes",
                _share(patient["insurance"].to_list()),
                ins_mix,
                patient.height,
                len(INSURANCE_ORDER),
            )
        ],
    )

    # ---------------------------------------------------------------- C2 (espera por servicio/tipo)
    mean_fail: list[str] = []
    med_fail: list[str] = []
    n_groups = 0
    worst_med = (0.0, 0.0, 0.0)
    worst_mean = (0.0, 0.0, 0.0)
    skipped = 0
    for r in t.service_rows:
        frame = ordinary.filter(
            (pl.col("health_service_code") == r.health_service_code)
            & (pl.col("care_type") == r.care_type)
        )
        if frame.height < MIN_GROUP:
            skipped += 1
            continue
        n_groups += 1
        w = frame["wait_days"].to_numpy().astype(float)
        med, mean = float(np.median(w)), float(w.mean())
        dm = abs(med - r.median_wait_days)
        if dm > worst_med[0]:
            worst_med = (dm, med, r.median_wait_days)
        if not _within(med, r.median_wait_days, 0.02, 1.0):
            med_fail.append(
                f"{r.health_service_code}/{r.care_type}: mediana {med:.1f} vs {r.median_wait_days}"
            )
        dn = abs(mean - r.mean_wait_days) / r.mean_wait_days
        if dn > worst_mean[0]:
            worst_mean = (dn, mean, r.mean_wait_days)
        if not _within(mean, r.mean_wait_days, 0.03):
            mean_fail.append(
                f"{r.health_service_code}/{r.care_type}: media {mean:.1f} vs {r.mean_wait_days}"
            )
    sigma_floor = [
        f"{r.health_service_code}/{r.care_type}"
        for r in t.service_rows
        if needs_sigma_floor(r.mean_wait_days, r.median_wait_days)
    ]
    if sigma_floor:
        notes.append(
            f"Piso de sigma (media <= 1,001·mediana) en servicio/tipo: {', '.join(sigma_floor)}"
        )
    if n_groups:
        col.add(
            name="C2.mediana",
            group="C2",
            metric="max|obs-obj| días",
            observed=worst_med[0],
            target=0.0,
            tolerance=None,
            n=n_groups,
            passed=not med_fail,
            severity="strict",
            detail=med_fail or ["todas dentro de ±max(2 %, 1 día)"],
        )
        col.add(
            name="C2.media",
            group="C2",
            metric="max error relativo",
            observed=worst_mean[0],
            target=0.0,
            tolerance=0.03,
            n=n_groups,
            passed=not mean_fail,
            severity="strict",
            detail=mean_fail or ["todas dentro de ±3 %"],
        )
    if skipped:
        col.add(
            name="C2.omitidos",
            group="C2",
            metric="grupos con n < 30",
            observed=float(skipped),
            target=None,
            tolerance=None,
            n=skipped,
            passed=True,
            severity="skipped",
            detail=[],
        )

    # ---------------------------------------------------------------- C3 (mezcla nacional)
    for label, frame, key in (("cne", cne, CNE), ("iq", iq, IQ)):
        nat = t.national_row(key)
        w = frame["wait_days"].to_numpy().astype(float)
        for metric, obs, tgt in (
            ("mediana", float(np.median(w)), nat.median_wait_days),
            ("media", float(w.mean()), nat.mean_wait_days),
        ):
            assert tgt is not None
            col.add(
                name=f"C3.{label}.{metric}",
                group="C3",
                metric=metric,
                observed=obs,
                target=tgt,
                tolerance=0.05 * tgt,
                n=frame.height,
                passed=_within(obs, tgt, 0.05),
                severity="strict",
                detail=[],
            )

    # ---------------------------------------------------------------- C4 (registros/personas)
    ent_p = ordinary.select("patient_id", "health_service_code", "care_type")
    fail4: list[str] = []
    worst4 = (0.0, "")
    for r in t.service_rows:
        frame = ent_p.filter(
            (pl.col("health_service_code") == r.health_service_code)
            & (pl.col("care_type") == r.care_type)
        )
        if frame.height == 0:
            continue
        persons = frame["patient_id"].n_unique()
        ratio = frame.height / persons
        target = r.waiting_count / r.persons_count
        tol = 0.01 + 1.0 / persons
        dev = abs(ratio - target)
        if dev > worst4[0]:
            worst4 = (dev, f"{r.health_service_code}/{r.care_type}")
        if dev > tol:
            fail4.append(
                f"{r.health_service_code}/{r.care_type}: {ratio:.3f} vs {target:.3f} "
                f"(tol {tol:.3f})"
            )
    col.add(
        name="C4.registros/personas",
        group="C4",
        metric="max|razón-obj|",
        observed=worst4[0],
        target=0.0,
        tolerance=None,
        n=len(t.service_rows),
        passed=not fail4,
        severity="strict",
        detail=fail4 or [f"peor grupo: {worst4[1]}"],
    )

    # ---------------------------------------------------------------- C5 (retraso GES)
    delayed = ges.filter(pl.col("ges_deadline") < pl.lit(as_of))
    delay = (pl.lit(as_of) - pl.col("ges_deadline")).dt.total_days().alias("delay")
    delayed = delayed.with_columns(delay)
    fail5: list[str] = []
    n5 = 0
    for g in uni.ges:
        frame = delayed.filter(pl.col("ges_problem_code") == g.code)
        if frame.height < MIN_GROUP:
            continue
        n5 += 1
        d = frame["delay"].to_numpy().astype(float)
        if not _within(float(np.median(d)), g.median_delay_days, 0.02, 1.0):
            fail5.append(f"{g.code}: mediana {np.median(d):.1f} vs {g.median_delay_days}")
        if not _within(float(d.mean()), g.mean_delay_days, 0.03):
            fail5.append(f"{g.code}: media {d.mean():.1f} vs {g.mean_delay_days}")
    col.add(
        name="C5.problemas",
        group="C5",
        metric="grupos con n>=30",
        observed=float(n5),
        target=None,
        tolerance=None,
        n=n5,
        passed=not fail5,
        severity="strict" if n5 else "skipped",
        detail=fail5 or ["dentro de tolerancia"],
    )
    if delayed.height:
        d = delayed["delay"].to_numpy().astype(float)
        # objetivo: mezcla ponderada por n de los problemas mapeados
        # (el nacional incluye problemas no mapeados)
        counts = {g.code: int((delayed["ges_problem_code"] == g.code).sum()) for g in uni.ges}
        tot = sum(counts.values())
        mix_mean = sum(counts[g.code] * g.mean_delay_days for g in uni.ges) / tot
        nat = t.national_row("ges")
        assert nat.mean_wait_days is not None and nat.median_wait_days is not None
        col.add(
            name="C5.nacional.media(mapeados)",
            group="C5",
            metric="media de retraso",
            observed=float(d.mean()),
            target=mix_mean,
            tolerance=0.05 * mix_mean,
            n=int(d.size),
            passed=_within(float(d.mean()), mix_mean, 0.05),
            severity="strict",
            detail=["objetivo = mezcla de los problemas mapeados"],
        )
        col.add(
            name="C5.nacional.media(total)",
            group="C5",
            metric="media de retraso",
            observed=float(d.mean()),
            target=nat.mean_wait_days,
            tolerance=0.05 * nat.mean_wait_days,
            n=int(d.size),
            passed=_within(float(d.mean()), nat.mean_wait_days, 0.05),
            severity="soft",
            detail=["el nacional incluye problemas no mapeados; se informa sin fallar"],
        )
        col.add(
            name="C5.nacional.mediana(total)",
            group="C5",
            metric="mediana de retraso",
            observed=float(np.median(d)),
            target=nat.median_wait_days,
            tolerance=0.05 * nat.median_wait_days,
            n=int(d.size),
            passed=_within(float(np.median(d)), nat.median_wait_days, 0.05),
            severity="soft",
            detail=["el nacional incluye problemas no mapeados; se informa sin fallar"],
        )

    # ---------------------------------------------------------------- C6 (inasistencias)
    params = NoShowParams.from_json(run["params"]["noshow"])  # type: ignore[index]
    rates = noshow_rates(t, a)
    feats = entry_features(
        entry_w,
        patient.join(latent.select(pl.col("patient_id").alias("id"), "noshow_frailty"), on="id"),
        t,
        as_of,
    )
    alpha = {(s, c.value): v for (s, c), v in params.intercepts.items()}
    inter = np.array(
        [
            alpha[(s, c)]
            for s, c in zip(feats["health_service_code"], feats["care_type"], strict=True)
        ]
    )
    ref = feats.with_columns(
        pl.Series("intercept", inter),
        pl.lit(float(params.ref_lead_days)).alias("lead_days"),
    ).select(
        "intercept",
        "specialty_code",
        "age_group",
        "insurance",
        "wait_days",
        "median_wait_days",
        "lead_days",
    )
    p_ref = true_noshow_prob(ref, feats["noshow_frailty"].to_numpy().astype(float), params)
    feats = feats.with_columns(pl.Series("p_ref", p_ref))
    fail6: list[str] = []
    worst6 = 0.0
    for (s, c), rate in sorted(rates.items()):
        sub = feats.filter((pl.col("health_service_code") == s) & (pl.col("care_type") == c.value))
        if sub.height == 0:
            continue
        m = float(sub["p_ref"].mean())  # type: ignore[arg-type]
        worst6 = max(worst6, abs(m - rate))
        if abs(m - rate) > 1e-4:
            fail6.append(f"{s}/{c.value}: {m:.5f} vs {rate:.5f}")
    col.add(
        name="C6.media_p",
        group="C6",
        metric="max|media p - tasa| (verifica la bisección, no la independencia)",
        observed=worst6,
        target=0.0,
        tolerance=1e-4,
        n=len(rates),
        passed=not fail6,
        severity="strict",
        detail=fail6 or ["calibrado"],
    )

    # C6 no tautológico: media de p con un sorteo independiente de u (stream VALIDATION).
    u_new = rng_for(int(str(run["seed"])), Stream.VALIDATION).normal(
        0.0, params.sigma_u, size=patient.height
    )
    pid_pos = {pid: i for i, pid in enumerate(patient["id"].to_list())}
    u_row = u_new[[pid_pos[x] for x in feats["patient_id"].to_list()]]
    p_ind = true_noshow_prob(ref, u_row, params)
    feats = feats.with_columns(pl.Series("p_ind", p_ind))
    fail6b: list[str] = []
    n6b = 0
    skipped6b = 0
    worst6b = 0.0
    for (s, c), rate in sorted(rates.items()):
        sub = feats.filter((pl.col("health_service_code") == s) & (pl.col("care_type") == c.value))
        if sub.height < MIN_HISTORY:
            skipped6b += 1
            continue
        n6b += 1
        vals = sub["p_ind"].to_numpy()
        tol = 3 * float(vals.std()) / math.sqrt(sub.height) + 0.005
        dev = abs(float(vals.mean()) - rate)
        worst6b = max(worst6b, dev)
        if dev > tol:
            fail6b.append(f"{s}/{c.value}: {vals.mean():.4f} vs {rate:.4f} (tol {tol:.4f})")
    col.add(
        name="C6.media_p.independiente",
        group="C6",
        metric="max|media p (u independiente) - tasa|",
        observed=worst6b,
        target=0.0,
        tolerance=None,
        n=n6b,
        passed=not fail6b,
        severity="strict" if n6b else "skipped",
        detail=fail6b or [f"dentro de ±(3·sigma_p/raíz(n) + 0,5 pp); {skipped6b} grupos omitidos"],
    )

    appt = tbl["appointment"].select("id", "patient_id", "status", "specialty_code")
    truth = tbl["appointment_truth"].select(
        pl.col("appointment_id").alias("id"), "true_noshow_prob"
    )
    hist = appt.join(truth, on="id").join(
        patient.select(pl.col("id").alias("patient_id"), "health_service_code"), on="patient_id"
    )
    realized = (hist["status"] == "no_show").cast(pl.Float64)
    exp_p = float(hist["true_noshow_prob"].mean())  # type: ignore[arg-type]
    obs_rate = float(realized.mean())  # type: ignore[arg-type]
    n_h = hist.height
    tol_g = 3 * math.sqrt(exp_p * (1 - exp_p) / n_h) + 0.005
    col.add(
        name="C6.historial.global",
        group="C6",
        metric="tasa realizada vs E[p historial]",
        observed=obs_rate,
        target=exp_p,
        tolerance=tol_g,
        n=n_h,
        passed=abs(obs_rate - exp_p) <= tol_g,
        severity="strict",
        detail=[],
    )
    fail_h: list[str] = []
    n_srv = 0
    for svc, frame in hist.group_by("health_service_code", maintain_order=True):
        if frame.height < MIN_HISTORY:
            continue
        n_srv += 1
        tp = float(frame["true_noshow_prob"].mean())  # type: ignore[arg-type]
        ob = float((frame["status"] == "no_show").cast(pl.Float64).mean())  # type: ignore[arg-type]
        tol = 3 * math.sqrt(tp * (1 - tp) / frame.height) + 0.005
        if abs(ob - tp) > tol:
            fail_h.append(f"servicio {svc[0]}: {ob:.4f} vs {tp:.4f} (tol {tol:.4f})")  # type: ignore[index]
    col.add(
        name="C6.historial.servicios",
        group="C6",
        metric="tasa realizada vs E[p historial]",
        observed=float(n_srv),
        target=None,
        tolerance=None,
        n=n_srv,
        passed=not fail_h,
        severity="strict" if n_srv else "skipped",
        detail=fail_h or ["dentro de ±(3·EE + 0,5 pp)"],
    )
    cne_rows = [r for r in t.service_rows if r.care_type == CNE]
    target_by_type = {
        CNE: sum(
            rates[(r.health_service_code, CareType.CONSULTATION)] * r.waiting_count
            for r in cne_rows
        )
        / sum(r.waiting_count for r in cne_rows),
        IQ: float(a.value("noshow_rate_iq")),
    }
    hist_type = hist.with_columns(
        pl.col("specialty_code")
        .replace_strict({k: v.care_type.value for k, v in specs.items()}, return_dtype=pl.String)
        .alias("care_type")
    )
    for ct, target_rate in target_by_type.items():
        sub_h = hist_type.filter(pl.col("care_type") == ct)
        if sub_h.height == 0:
            continue
        rate_h = float((sub_h["status"] == "no_show").cast(pl.Float64).mean())  # type: ignore[arg-type]
        col.add(
            name=f"C6.historial.vs_tasa_objetivo.{'cne' if ct == CNE else 'iq'}",
            group="C6",
            metric="tasa realizada vs tasa objetivo del tipo",
            observed=rate_h,
            target=target_rate,
            tolerance=0.01,
            n=sub_h.height,
            passed=abs(rate_h - target_rate) <= 0.01,
            severity="soft",
            detail=[
                "el historial usa anticipación U{7..90} y sin término de espera; "
                "difiere de la referencia"
            ],
        )

    # ---------------------------------------------------------------- C7 (IQ mayor)
    sub = {r.care_subtype: r.waiting_count for r in t.subtypes if r.care_type == IQ}
    major_t = sub["major"] / (sub["major"] + sub["minor"])
    major_o = float((iq["care_subtype"] == "major").mean())  # type: ignore[arg-type]
    col.add(
        name="C7.iq_mayor",
        group="C7",
        metric="participación",
        observed=major_o,
        target=major_t,
        tolerance=0.03,
        n=iq.height,
        passed=abs(major_o - major_t) <= 0.03,
        severity="strict",
        detail=[],
    )

    # ---------------------------------------------------------------- C8 (capacidad)
    cap_t = capacity_targets(t, a, cfg, entry)
    slot = (
        tbl["slot"]
        .join(
            tbl["resource"].select(
                pl.col("id").alias("resource_id"), "health_service_code", "kind"
            ),
            on="resource_id",
        )
        .with_columns(
            pl.when(pl.col("kind") == "operating_room")
            .then(pl.lit(IQ))
            .otherwise(pl.lit(CNE))
            .alias("care_type")
        )
    )
    sched: dict[tuple[int, str], float] = {}
    for r in (
        slot.group_by("health_service_code", "care_type")
        .agg(pl.col("duration_min").sum())
        .iter_rows()
    ):
        sched[(int(r[0]), str(r[1]))] = float(r[2]) / h
    fail8: list[str] = []
    worst8 = 0.0
    for r in cap_t.iter_rows(named=True):
        key = (int(r["health_service_code"]), str(r["care_type"]))
        target = float(r["target_min_per_week"])
        obs = sched.get(key, 0.0)
        # Banda de la ventana (con calentamiento): por encima de la meta, a lo más una sesión
        # larga en el horizonte; por debajo, a lo más 5 % o una sesión larga.
        one = r["session_min"] / h
        tol = max(0.05 * target, one)
        worst8 = max(worst8, abs(obs - target))
        if obs - target > one + 1e-9 or target - obs > tol + 1e-9:
            fail8.append(f"{key}: {obs:.1f} vs {target:.1f} min/semana (tol {tol:.1f})")
    col.add(
        name="C8.minutos_programados",
        group="C8",
        metric="max|min/sem - objetivo|",
        observed=worst8,
        target=0.0,
        tolerance=None,
        n=cap_t.height,
        passed=not fail8,
        severity="strict",
        detail=fail8 or ["meta - max(5 %, 1 sesión/H) <= oferta <= meta + 1 sesión/H"],
    )
    have = set(
        zip(slot["health_service_code"].to_list(), slot["specialty_code"].to_list(), strict=True)
    )
    want = set(
        zip(entry["health_service_code"].to_list(), entry["specialty_code"].to_list(), strict=True)
    )
    notes.append(
        "Celdas (servicio, especialidad) con entradas pero sin sesiones: "
        f"{len(want - have)} de {len(want)}"
    )
    served_min = float(cap_t["target_min_per_week"].sum())
    unserved_min = float(cap_t["unserved_min_per_week"].sum())
    all_min = served_min + unserved_min
    notes.append(
        "Minutos por semana de celdas sin oferta posible (menos de media sesión de la menor "
        f"duración en el periodo de referencia): {unserved_min:.0f} de {all_min:.0f} "
        f"({unserved_min / max(all_min, 1e-9):.1%}); no entran en la meta de C8"
    )

    # ---------------------------------------------------------------- C9 (blandos / informe)
    cne_p = feats.filter((pl.col("care_type") == CNE) & ~pl.col("is_ges"))["p_ref"].to_numpy()
    e_p2 = float((cne_p**2).mean())
    tgt = a.value("noshow_e_p2_cne_target")
    col.add(
        name="C9.E[p2]_cne",
        group="C9",
        metric="E[p²] CNE",
        observed=e_p2,
        target=float(tgt["value"]),
        tolerance=float(tgt["tolerance"]),
        n=int(cne_p.size),
        passed=abs(e_p2 - float(tgt["value"])) <= float(tgt["tolerance"]),
        severity="soft",
        detail=[],
    )
    col.add(
        name="C9.cobertura_ges",
        group="C9",
        metric="cobertura sobre retrasadas",
        observed=uni.ges_coverage,
        target=1.0,
        tolerance=None,
        n=uni.l_ges_delayed,
        passed=True,
        severity="soft",
        detail=[
            f"{uni.l_ges_delayed} de {uni.ges_delayed_total} garantías retrasadas; "
            f"{len(uni.ges)} problemas mapeados"
        ],
    )
    tab = cne.group_by("health_service_code", "specialty_code").len()
    svcs = sorted(set(tab["health_service_code"].to_list()))
    sps = sorted(set(tab["specialty_code"].to_list()))
    m = np.zeros((len(svcs), len(sps)))
    si = {v: i for i, v in enumerate(svcs)}
    pi = {v: i for i, v in enumerate(sps)}
    for s, sp, c in tab.iter_rows():
        m[si[s], pi[sp]] = c
    total = m.sum()
    exp_m = np.outer(m.sum(1), m.sum(0)) / total
    chi2 = float(((m - exp_m) ** 2 / np.where(exp_m > 0, exp_m, 1)).sum())
    cramer = math.sqrt(chi2 / (total * (min(m.shape) - 1))) if total and min(m.shape) > 1 else 0.0
    col.add(
        name="C9.cramer_v_servicio_x_especialidad",
        group="C9",
        metric="V de Cramér",
        observed=cramer,
        target=None,
        tolerance=None,
        n=int(total),
        passed=True,
        severity="soft",
        detail=["solo informe; el cruce se asume aproximadamente independiente"],
    )

    strict = [c for c in col.checks if c.severity == "strict"]
    summary = {
        "strict_passed": sum(c.passed for c in strict),
        "strict_failed": sum(not c.passed for c in strict),
        "soft_failed": sum((not c.passed) for c in col.checks if c.severity == "soft"),
        "skipped": sum(c.severity == "skipped" for c in col.checks),
    }
    notes.append(DISCLAIMER)
    return CalibrationReport(
        run_id=str(run["id"]),
        digest=ds.digest,
        checks=col.checks,
        passed=summary["strict_failed"] == 0,
        summary=summary,
        notes=notes,
    )
