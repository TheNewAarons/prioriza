"""Métricas de calibración C1-C8 calculadas de forma independiente en los tests.

No importa nada de ``synthetic.validate``, ``synthetic.universe`` ni
``synthetic.noshow_truth``: recalcula las métricas desde los DataFrames y los
JSON de objetivos/supuestos, para que los tests no sean tautológicos.
Todo es sintético.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import date

import numpy as np
import polars as pl

CNE, IQ = "consultation", "surgery"
AS_OF = date(2025, 9, 30)
PEDIATRIC = re.compile(r"pediatr|infantil|del_nino|adolescente")


def tvd(observed: dict, expected: dict) -> float:
    """Distancia de variación total, 1/2 * suma |p_obs - p_esp|."""
    keys = set(observed) | set(expected)
    return 0.5 * sum(abs(observed.get(k, 0.0) - expected.get(k, 0.0)) for k in keys)


def shares(values) -> dict:
    """Proporciones empíricas de una lista de valores."""
    c = Counter(values)
    n = sum(c.values())
    return {k: v / n for k, v in c.items()}


def normalize(w: dict) -> dict:
    """Normaliza pesos a proporciones."""
    s = float(sum(w.values()))
    return {k: v / s for k, v in w.items()}


def slug(text: str) -> str:
    """Slug ASCII igual al de los códigos de especialidad (group:slug)."""
    import unicodedata

    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


def ges_info(t, a):
    """Lista de dicts por problema GES mapeado: demanda retrasada y en plazo (Little, 0,5)."""
    factor = float(a.value("ges_in_plazo_factor"))
    by_code = {p.code: p for p in t.ges_problems}
    out = []
    for m in sorted(a.ges_problem_map, key=lambda x: x.code):
        p = by_code[m.code]
        ytd = p.ytd_new_cases_fonasa_2025 or 0
        out.append(
            {
                "code": m.code,
                "group": m.group,
                "deadline": m.deadline_days,
                "delayed": p.delayed_count,
                "in_deadline": ytd * m.deadline_days / 365.0 * factor,
                "ytd": ytd,
                "mean": p.mean_delay_days if p.mean_delay_days is not None else 136.0,
                "median": p.median_delay_days if p.median_delay_days is not None else 71.0,
            }
        )
    return out


def with_wait(entry: pl.DataFrame) -> pl.DataFrame:
    """Agrega wait_days = as_of - entry_date."""
    return entry.with_columns(
        (pl.lit(AS_OF) - pl.col("entry_date")).dt.total_days().alias("wait_days")
    )


# ------------------------------------------------------------------ C1


def c1_checks(ds, t, a) -> dict[str, tuple[float, float]]:
    """Devuelve {nombre: (tvd observado, cota K/(2n)+1e-9)} para cada margen de C1."""
    entry, patient = ds.tables["waitlist_entry"], ds.tables["patient"]
    out: dict[str, tuple[float, float]] = {}

    def add(name, obs_values, exp, k=None):
        n = len(obs_values)
        k = len(exp) if k is None else k
        out[name] = (tvd(shares(obs_values), exp), k / (2 * n) + 1e-9)

    ges = ges_info(t, a)
    l_ges = sum(g["delayed"] + g["in_deadline"] for g in ges)
    kinds = [
        "ges" if g else ("cne" if c == CNE else "iq")
        for g, c in zip(entry["is_ges"], entry["care_type"], strict=True)
    ]
    add(
        "tipo",
        kinds,
        normalize(
            {
                "cne": t.national_row(CNE).waiting_count,
                "iq": t.national_row(IQ).waiting_count,
                "ges": l_ges,
            }
        ),
    )
    ordinary = entry.filter(~pl.col("is_ges"))
    for ct, label in ((CNE, "cne"), (IQ, "iq")):
        sub = ordinary.filter(pl.col("care_type") == ct)
        exp = normalize(
            {r.health_service_code: r.waiting_count for r in t.service_rows if r.care_type == ct}
        )
        add(f"servicio|{label}", sub["health_service_code"].to_list(), exp)
    for group, ct, subtype in (
        ("cne_medical", CNE, "medical"),
        ("cne_dental", CNE, "dental"),
        ("iq", IQ, None),
    ):
        sub = ordinary.filter(pl.col("care_type") == ct)
        if subtype:
            sub = sub.filter(pl.col("care_subtype") == subtype)
        exp = normalize(
            {f"{group}:{slug(r.name)}": r.waiting_count for r in t.specialties if r.group == group}
        )
        add(f"especialidad|{group}", sub["specialty_code"].to_list(), exp)
    gent = entry.filter(pl.col("is_ges"))
    add(
        "problema|ges",
        gent["ges_problem_code"].to_list(),
        normalize({g["code"]: g["delayed"] + g["in_deadline"] for g in ges}),
    )
    add(
        "servicio|ges",
        gent["health_service_code"].to_list(),
        normalize({s.health_service_code: s.waiting_count for s in t.ges_services}),
    )
    cw = a.value("commune_facility_weights")
    weights: dict[int, dict[str, float]] = defaultdict(dict)
    for cs in t.commune_service:
        w = cs.cesfam_like * cw["cesfam_like"] + cs.cecosf * cw["cecosf"] + cs.psr * cw["psr"]
        if w > 0:
            weights[cs.health_service_code][cs.commune_code] = w
    for svc in sorted(set(patient["health_service_code"].to_list())):
        sub = patient.filter(pl.col("health_service_code") == svc)
        if svc not in weights:
            continue  # sin APS: el generador usa comunas de hospitales (no es margen público)
        add(f"comuna|servicio {svc}", sub["commune_code"].to_list(), normalize(weights[svc]))
    ped = {
        code
        for code in set(entry["specialty_code"].to_list())
        if PEDIATRIC.search(code.split(":", 1)[1])
    }
    ep = entry.select("patient_id", "specialty_code").join(
        patient.select(pl.col("id").alias("patient_id"), "age_group"), on="patient_id"
    )
    for label, is_ped, key in (
        ("pediatrica", True, "pediatric_age_mix"),
        ("general", False, "general_age_mix"),
    ):
        sub = ep.filter(pl.col("specialty_code").is_in(sorted(ped)) == is_ped)
        add(f"edad|{label}", sub["age_group"].to_list(), normalize(dict(a.value(key))), k=5)
    ins = a.value("insurance_aps_counts")["counts"]
    add("previsión", patient["insurance"].to_list(), normalize(dict(ins)))
    return out


# ------------------------------------------------------------------ C2-C5, C7


def within(obs: float, target: float, rel: float, abs_tol: float = 0.0) -> bool:
    """|obs - target| <= max(rel*|target|, abs_tol)."""
    return abs(obs - target) <= max(rel * abs(target), abs_tol) + 1e-9


def wait_group_errors(ds, t) -> tuple[list[str], int]:
    """C2: errores por (servicio, tipo) con n>=30 (listas no GES). Devuelve (fallos, grupos)."""
    ordinary = with_wait(ds.tables["waitlist_entry"]).filter(~pl.col("is_ges"))
    fails, groups = [], 0
    for r in t.service_rows:
        sub = ordinary.filter(
            (pl.col("health_service_code") == r.health_service_code)
            & (pl.col("care_type") == r.care_type)
        )
        if sub.height < 30:
            continue
        groups += 1
        w = sub["wait_days"].to_numpy().astype(float)
        if not within(float(np.median(w)), r.median_wait_days, 0.02, 1.0):
            fails.append(
                f"{r.health_service_code}/{r.care_type} mediana {np.median(w)} "
                f"vs {r.median_wait_days}"
            )
        if not within(float(w.mean()), r.mean_wait_days, 0.03):
            fails.append(
                f"{r.health_service_code}/{r.care_type} media {w.mean():.1f} vs {r.mean_wait_days}"
            )
    return fails, groups


def national_wait(ds, care_type: str) -> tuple[float, float]:
    """C3: (media, mediana) de espera de la mezcla nacional no GES de un tipo."""
    e = with_wait(ds.tables["waitlist_entry"]).filter(
        ~pl.col("is_ges") & (pl.col("care_type") == care_type)
    )
    w = e["wait_days"].to_numpy().astype(float)
    return float(w.mean()), float(np.median(w))


def ratio_errors(ds, t) -> tuple[list[str], int]:
    """C4: razón registros/personas por (servicio, tipo) vs persons_count, ±(0,01 + 1/P)."""
    ordinary = ds.tables["waitlist_entry"].filter(~pl.col("is_ges"))
    fails, groups = [], 0
    for r in t.service_rows:
        sub = ordinary.filter(
            (pl.col("health_service_code") == r.health_service_code)
            & (pl.col("care_type") == r.care_type)
        )
        if sub.height == 0:
            continue
        groups += 1
        p = sub["patient_id"].n_unique()
        ratio = sub.height / p
        target = r.waiting_count / r.persons_count
        if abs(ratio - target) > 0.01 + 1.0 / p:
            fails.append(f"{r.health_service_code}/{r.care_type}: {ratio:.3f} vs {target:.3f}")
    return fails, groups


def ges_delay_errors(ds, t, a) -> tuple[list[str], int, np.ndarray, float]:
    """C5: retraso GES (as_of - plazo) por problema con n>=30. Devuelve también el
    vector de retrasos y el objetivo de media de la mezcla de problemas mapeados."""
    entry = ds.tables["waitlist_entry"].filter(pl.col("is_ges"))
    delayed = entry.filter(pl.col("ges_deadline") < pl.lit(AS_OF)).with_columns(
        (pl.lit(AS_OF) - pl.col("ges_deadline")).dt.total_days().alias("delay")
    )
    fails, groups = [], 0
    info = {g["code"]: g for g in ges_info(t, a)}
    mix = 0.0
    for code, g in info.items():
        sub = delayed.filter(pl.col("ges_problem_code") == code)
        mix += sub.height * g["mean"]
        if sub.height < 30:
            continue
        groups += 1
        d = sub["delay"].to_numpy().astype(float)
        if not within(float(np.median(d)), g["median"], 0.02, 1.0):
            fails.append(f"{code} mediana {np.median(d)} vs {g['median']}")
        if not within(float(d.mean()), g["mean"], 0.03):
            fails.append(f"{code} media {d.mean():.1f} vs {g['mean']}")
    return fails, groups, delayed["delay"].to_numpy().astype(float), mix / max(delayed.height, 1)


# ------------------------------------------------------------------ C6


def noshow_rates(t, a) -> dict[tuple[int, str], float]:
    """Tasas objetivo t_{s,c}: CNE con Arica/Iquique fijos y tasa común k; IQ constante."""
    national = float(a.value("noshow_rate_cne_national"))
    over = {int(k): float(v) for k, v in a.value("noshow_rate_overrides").items()}
    cne = {r.health_service_code: r.waiting_count for r in t.service_rows if r.care_type == CNE}
    fixed = sum(cne[s] * v for s, v in over.items())
    others = sum(v for s, v in cne.items() if s not in over)
    k = (national * sum(cne.values()) - fixed) / others
    rates = {(s, CNE): over.get(s, k) for s in cne}
    for r in t.service_rows:
        if r.care_type == IQ:
            rates[(r.health_service_code, IQ)] = float(a.value("noshow_rate_iq"))
    return rates


def entry_p_ref(ds, t, frailty=None) -> pl.DataFrame:
    """p verdadera de cada entrada con anticipación de referencia, recalculada con la
    fórmula logit del plan (sección 2) y los parámetros guardados en ``ds.run``.

    Si se entrega ``frailty`` (un valor por entrada, en el orden de la tabla), reemplaza al u
    guardado: sirve para verificar la calibración con un sorteo independiente."""
    prm = ds.run["params"]["noshow"]
    entry = with_wait(ds.tables["waitlist_entry"])
    med = {(r.health_service_code, r.care_type): r.median_wait_days for r in t.service_rows}
    pat = ds.tables["patient"].join(
        ds.tables["patient_latent"].select(pl.col("patient_id").alias("id"), "noshow_frailty"),
        on="id",
    )
    df = entry.join(
        pat.select(pl.col("id").alias("patient_id"), "age_group", "insurance", "noshow_frailty"),
        on="patient_id",
    )
    rows = df.select(
        "health_service_code",
        "care_type",
        "specialty_code",
        "age_group",
        "insurance",
        "wait_days",
        "noshow_frailty",
    ).to_dicts()
    ref_lead = float(prm["ref_lead_days"])
    if frailty is not None:
        for r, u in zip(rows, frailty, strict=True):
            r["noshow_frailty"] = float(u)
    p = np.empty(len(rows))
    for i, r in enumerate(rows):
        m = med.get((r["health_service_code"], r["care_type"]), float(r["wait_days"]))
        z = (
            prm["intercepts"][f"{r['health_service_code']}:{r['care_type']}"]
            + prm["gamma"][r["specialty_code"]]
            + prm["beta_age"][r["age_group"]]
            + prm["beta_ins"][r["insurance"]]
            + prm["beta_wait"] * math.log2(max(r["wait_days"], 1.0) / max(m, 1.0))
            + prm["beta_lead"] * math.log2(1.0 + ref_lead / 7.0)
            + r["noshow_frailty"]
        )
        p[i] = 1.0 / (1.0 + math.exp(-z))
    return df.select("health_service_code", "care_type", "is_ges").with_columns(
        pl.Series("p_ref", p)
    )


def history_frame(ds) -> pl.DataFrame:
    """Historial con p verdadera, resultado y atributos del paciente."""
    ap = ds.tables["appointment"].select("id", "patient_id", "status", "lead_days")
    tr = ds.tables["appointment_truth"].select(
        pl.col("appointment_id").alias("id"), "true_noshow_prob"
    )
    pat = ds.tables["patient"].select(
        pl.col("id").alias("patient_id"), "health_service_code", "age_group", "insurance"
    )
    return ap.join(tr, on="id").join(pat, on="patient_id")


# ------------------------------------------------------------------ C8


def capacity_errors(ds, t, a, size: int, horizon: int) -> tuple[list[str], int]:
    """C8: minutos programados por semana vs objetivo por (servicio, tipo), recalculado con
    ley de Little (plan sección 3): CNE = theta/(1-t)*consult_min; IQ = theta/(1-t)*(dur+30)/0.85.
    """
    entry = ds.tables["waitlist_entry"]
    rates = noshow_rates(t, a)
    ges = ges_info(t, a)
    l_u = (
        t.national_row(CNE).waiting_count
        + t.national_row(IQ).waiting_count
        + sum(g["delayed"] + g["in_deadline"] for g in ges)
    )
    scale = size / l_u * float(a.value("capacity_multiplier"))
    theta: dict[tuple[int, str], float] = {}
    for r in t.service_rows:
        theta[(r.health_service_code, r.care_type)] = 7.0 * r.waiting_count / r.mean_wait_days
    ges_total = sum(s.waiting_count for s in t.ges_services)
    for g in ges:
        ct = IQ if g["group"] == "iq" else CNE
        for s in t.ges_services:
            key = (s.health_service_code, ct)
            theta[key] = theta.get(key, 0.0) + g["ytd"] / 52.0 * s.waiting_count / ges_total
    dur = dict(
        zip(
            ds.catalogs["procedure"]["code"].to_list(),
            ds.catalogs["procedure"]["duration_min"].to_list(),
            strict=True,
        )
    )
    e = entry.with_columns(
        pl.col("procedure_code").replace_strict(dur, return_dtype=pl.Int64).alias("dur")
    )
    sessions = {CNE: int(a.value("cne_session_min")), IQ: int(a.value("iq_block_min"))}
    slot = ds.tables["slot"].join(
        ds.tables["resource"].select(
            pl.col("id").alias("resource_id"), "health_service_code", "kind"
        ),
        on="resource_id",
    )
    fails, groups = [], 0
    for (s, c), th in sorted(theta.items()):
        sub = e.filter((pl.col("health_service_code") == s) & (pl.col("care_type") == c))
        if sub.height == 0 or (s, c) not in rates:
            continue
        no_show = rates[(s, c)]
        if c == CNE:
            # un solo procedimiento "consulta nueva" por especialidad
            target = th * scale / (1 - no_show) * float(sub["dur"].mean())
        else:
            target = (
                th
                * scale
                / (1 - no_show)
                * (float(sub["dur"].mean()) + float(a.value("iq_turnover_min")))
                / float(a.value("iq_utilization"))
            )
        kind = "operating_room" if c == IQ else "specialist_agenda"
        got = (
            slot.filter((pl.col("health_service_code") == s) & (pl.col("kind") == kind))[
                "duration_min"
            ].sum()
            / horizon
        )
        groups += 1
        if abs(got - target) > max(0.05 * target, sessions[c] / horizon) + 1e-9:
            fails.append(f"{s}/{c}: {got:.1f} vs {target:.1f} min/sem")
    return fails, groups
