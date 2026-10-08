"""Población sintética: pacientes y entradas en lista de espera calibrados contra la Glosa 06.

Asignación determinista con márgenes exactos (Hamilton) más permutaciones con semilla;
ver ``docs/design/synthetic-plan.md``, sección 1. No se generan nombres, RUT, sexo, etnia
ni nacionalidad.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from uuid import UUID

import numpy as np
import polars as pl
from shared.schemas import CareType

from synthetic.allocation import hamilton, labels
from synthetic.catalog import (
    IqProcedure,
    consultation_procedure_code,
    iq_procedures,
    specialty_index,
)
from synthetic.config import RunConfig
from synthetic.distributions import fit_lognormal, match_mean_median, stratified_lognormal
from synthetic.rng import Stream, rng_for
from synthetic.targets import CNE, IQ, Assumptions, CalibrationTargets
from synthetic.taxonomy import GROUP_CNE_DENTAL, GROUP_CNE_MEDICAL, GROUP_IQ, specialty_code
from synthetic.universe import Universe, build_universe

AGE_ORDER = ("0_14", "15_19", "20_44", "45_64", "65_plus")
INSURANCE_ORDER = ("fonasa_a", "fonasa_b", "fonasa_c", "fonasa_d", "other")
PRIORITY_ORDER = ("p1", "p2", "p3", "p4")

ENTRY_COLUMNS = [
    "id",
    "run_id",
    "patient_id",
    "health_service_code",
    "establishment_code",
    "specialty_code",
    "procedure_code",
    "care_type",
    "care_subtype",
    "clinical_priority",
    "is_ges",
    "ges_problem_code",
    "ges_deadline",
    "entry_date",
    "status",
    "resolved_on",
]
PATIENT_COLUMNS = [
    "id",
    "run_id",
    "health_service_code",
    "commune_code",
    "age_group",
    "insurance",
]


def resolve_as_of(cfg: RunConfig, a: Assumptions) -> date:
    """Fecha de referencia: ``--as-of`` si se entregó; si no, la del supuesto ``as_of``."""
    return cfg.as_of if cfg.as_of is not None else date.fromisoformat(a.value("as_of"))


def _permute(arr: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return arr[rng.permutation(len(arr))]


def _service_rows(
    t: CalibrationTargets, care_type: str
) -> dict[int, tuple[int, int, float, float]]:
    """Servicio -> (registros, personas, media, mediana) de la lista no GES."""
    return {
        r.health_service_code: (
            r.waiting_count,
            r.persons_count,
            r.mean_wait_days,
            r.median_wait_days,
        )
        for r in sorted(t.service_rows, key=lambda x: x.health_service_code)
        if r.care_type == care_type
    }


def _choose_procedures(
    spec_codes: np.ndarray,
    subtypes: np.ndarray,
    procs: list[IqProcedure],
    rng: np.random.Generator,
) -> np.ndarray:
    """Elige, por entrada IQ, un procedimiento de su especialidad y subtipo (ponderado)."""
    out = np.empty(len(spec_codes), dtype=object)
    by_key: dict[tuple[str, str], list[IqProcedure]] = {}
    by_spec: dict[str, list[IqProcedure]] = {}
    for p in procs:
        by_key.setdefault((p.specialty_code, p.care_subtype.value), []).append(p)
        by_spec.setdefault(p.specialty_code, []).append(p)
    pairs = sorted({(str(s), str(b)) for s, b in zip(spec_codes, subtypes, strict=True)})
    for spec, sub in pairs:
        idx = np.flatnonzero((spec_codes == spec) & (subtypes == sub))
        cands = by_key.get((spec, sub)) or by_spec[spec]
        w = np.array([c.weight for c in cands], dtype=float)
        pick = rng.choice(len(cands), size=len(idx), p=w / w.sum())
        out[idx] = [cands[i].code for i in pick]
    return out


def _wait_days(
    n: int,
    mean: float,
    median: float,
    floor: float,
    clip: tuple[int, int],
    rng: np.random.Generator,
) -> np.ndarray:
    """Espera en días de un grupo: lognormal estratificada con mediana y media ajustadas."""
    d = fit_lognormal(mean, median, floor)
    x = stratified_lognormal(d, n, rng, float(clip[1]))
    x = match_mean_median(x, mean, median, float(clip[0]), float(clip[1]))
    return np.clip(np.rint(x), clip[0], clip[1]).astype(np.int64)


def commune_weights(t: CalibrationTargets, a: Assumptions) -> dict[int, dict[str, float]]:
    """Peso por comuna dentro de cada servicio (proxy de población inscrita en APS).

    CESFAM/CGU/CGR por 1, CECOSF por 0,5, PSR por 0,1 (supuesto ``commune_facility_weights``). Si un
    servicio no tiene establecimientos de APS, se usan las comunas de sus hospitales.
    """
    cw = a.value("commune_facility_weights")
    out: dict[int, dict[str, float]] = {}
    for cs in t.commune_service:
        w = cs.cesfam_like * cw["cesfam_like"] + cs.cecosf * cw["cecosf"] + cs.psr * cw["psr"]
        if w > 0:
            out.setdefault(cs.health_service_code, {})[cs.commune_code] = w
    for h in t.establishments:
        if not out.get(h.health_service_code):
            fallback = {
                h2.commune_code: 1.0
                for h2 in t.establishments
                if h2.health_service_code == h.health_service_code
            }
            out[h.health_service_code] = fallback
    return {s: dict(sorted(w.items())) for s, w in sorted(out.items())}


def generate_population(
    t: CalibrationTargets, a: Assumptions, cfg: RunConfig, run_id: UUID
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Genera ``patient`` y ``waitlist_entry`` (columnas idénticas a las tablas de la BD)."""
    as_of = resolve_as_of(cfg, a)
    uni = build_universe(t, a)
    specs = specialty_index(t)
    procs = iq_procedures(t, a)
    n = cfg.size
    r_alloc = rng_for(cfg.seed, Stream.ALLOCATION)
    r_attr = rng_for(cfg.seed, Stream.ATTRS)
    r_wait = rng_for(cfg.seed, Stream.WAIT)
    r_prio = rng_for(cfg.seed, Stream.PRIORITY)
    r_ges = rng_for(cfg.seed, Stream.GES)
    r_link = rng_for(cfg.seed, Stream.PATIENT_LINK)

    # ---- 1. Márgenes exactos por bloque ------------------------------------------------
    kind_counts = hamilton({"cne": uni.l_cne, "iq": uni.l_iq, "ges": uni.l_ges}, n)
    n_cne, n_iq, n_ges = kind_counts["cne"], kind_counts["iq"], kind_counts["ges"]

    cne_rows = _service_rows(t, CNE)
    iq_rows = _service_rows(t, IQ)

    def service_labels(rows: dict[int, tuple[int, int, float, float]], total: int) -> np.ndarray:
        codes = list(rows)
        counts = hamilton({c: float(rows[c][0]) for c in codes}, total)
        return labels(counts, codes)

    def specialty_labels(groups: tuple[str, ...], total: int) -> np.ndarray:
        weights = {
            specialty_code(r.group, r.name): float(r.waiting_count)
            for r in sorted(t.specialties, key=lambda x: (x.group, x.name))
            if r.group in groups
        }
        counts = hamilton(weights, total)
        return _permute(labels(counts, list(weights)), r_alloc)

    # CNE
    cne_svc = service_labels(cne_rows, n_cne)
    cne_spec = specialty_labels((GROUP_CNE_MEDICAL, GROUP_CNE_DENTAL), n_cne)
    # IQ
    iq_svc = service_labels(iq_rows, n_iq)
    iq_spec = specialty_labels((GROUP_IQ,), n_iq)
    sub_w = {r.care_subtype: float(r.waiting_count) for r in t.subtypes if r.care_type == IQ}
    iq_sub = _permute(labels(hamilton(sub_w, n_iq), list(sub_w)), r_alloc)
    iq_proc = _choose_procedures(iq_spec, iq_sub, procs, r_attr)
    # GES: celdas (problema, retrasada/en plazo)
    cells = [(g, True) for g in uni.ges] + [(g, False) for g in uni.ges]
    cell_w = {
        i: (c[0].delayed_count if c[1] else c[0].in_deadline_weight) for i, c in enumerate(cells)
    }
    cell_counts = hamilton(cell_w, n_ges)
    cell_lab = labels(cell_counts, list(cell_w)).astype(np.int64)
    ges_w = {
        r.health_service_code: float(r.waiting_count)
        for r in sorted(t.ges_services, key=lambda x: x.health_service_code)
    }
    ges_svc = _permute(labels(hamilton(ges_w, n_ges), list(ges_w)), r_alloc)
    ges_info = [cells[i][0] for i in cell_lab]
    ges_delayed = np.array([cells[i][1] for i in cell_lab], dtype=bool)
    ges_spec = np.array([g.specialty_code for g in ges_info], dtype=object)
    ges_problem = np.array([g.code for g in ges_info], dtype=np.int64)
    ges_deadline_days = np.array([g.deadline_days for g in ges_info], dtype=np.int64)
    ges_onc = np.array([g.oncologic for g in ges_info], dtype=bool)

    # ---- 2. Vectores por entrada (CNE, IQ, GES en ese orden) ----------------------------
    kind = np.array(["cne"] * n_cne + ["iq"] * n_iq + ["ges"] * n_ges, dtype=object)
    service = np.concatenate([cne_svc, iq_svc, ges_svc]).astype(np.int64)
    spec = np.concatenate([cne_spec, iq_spec, ges_spec]).astype(object)
    problem = np.concatenate([np.zeros(n_cne + n_iq, dtype=np.int64), ges_problem])
    is_ges = kind == "ges"
    onc = np.concatenate([np.zeros(n_cne + n_iq, dtype=bool), ges_onc])

    # procedimiento y subtipo
    ges_proc = np.empty(n_ges, dtype=object)
    iq_like = np.flatnonzero([specs[s].group == GROUP_IQ for s in ges_spec])
    if len(iq_like):
        # entradas GES quirúrgicas: procedimiento ponderado entre todos los de la especialidad
        by_spec: dict[str, list[IqProcedure]] = {}
        for p in procs:
            by_spec.setdefault(p.specialty_code, []).append(p)
        for sc in sorted({str(ges_spec[i]) for i in iq_like}):
            idx = np.array([i for i in iq_like if ges_spec[i] == sc])
            cands = by_spec[sc]
            w = np.array([c.weight for c in cands], dtype=float)
            ges_proc[idx] = [
                cands[j].code for j in r_ges.choice(len(cands), len(idx), p=w / w.sum())
            ]
    for i in range(n_ges):
        if specs[str(ges_spec[i])].group != GROUP_IQ:
            ges_proc[i] = consultation_procedure_code(str(ges_spec[i]))
    proc_sub = {p.code: p.care_subtype.value for p in procs}
    cne_proc = np.array([consultation_procedure_code(str(s)) for s in cne_spec], dtype=object)
    procedure = np.concatenate([cne_proc, iq_proc, ges_proc]).astype(object)
    care_type = np.array([specs[str(s)].care_type.value for s in spec], dtype=object)
    care_subtype = np.empty(n, dtype=object)
    for i in range(n):
        s = specs[str(spec[i])]
        if s.care_type == CareType.CONSULTATION:
            care_subtype[i] = s.care_subtype.value if s.care_subtype else None
        else:
            care_subtype[i] = proc_sub[str(procedure[i])]

    # ---- 3. Espera -------------------------------------------------------------------
    clip = (int(a.value("wait_clip_days")[0]), int(a.value("wait_clip_days")[1]))
    floor = float(a.value("lognormal_sigma_floor"))
    wait = np.zeros(n, dtype=np.int64)
    for kd, rows in (("cne", cne_rows), ("iq", iq_rows)):
        for svc, (_, _, mean, median) in rows.items():
            idx = np.flatnonzero((kind == kd) & (service == svc))
            if len(idx):
                wait[idx] = _wait_days(len(idx), mean, median, floor, clip, r_wait)
    ges_base = n_cne + n_iq
    for g in uni.ges:
        gi = np.flatnonzero(ges_problem == g.code)
        d_idx = gi[ges_delayed[gi]]
        p_idx = gi[~ges_delayed[gi]]
        if len(d_idx):
            d = _wait_days(
                len(d_idx),
                g.mean_delay_days,
                g.median_delay_days,
                floor,
                (1, max(2, clip[1] - g.deadline_days)),
                r_wait,
            )
            wait[ges_base + d_idx] = g.deadline_days + d
        if len(p_idx):
            wait[ges_base + p_idx] = 1 + np.floor(
                r_wait.random(len(p_idx)) * g.deadline_days
            ).astype(np.int64)
    # ---- 4. Prioridad clínica (dato de entrada sintético) -----------------------------
    priority = np.empty(n, dtype=object)
    mixes = {
        "cne": a.value("priority_mix_cne"),
        "iq": a.value("priority_mix_iq"),
        "ges_onc": a.value("priority_mix_ges_oncologic"),
        "ges_other": a.value("priority_mix_iq"),
    }
    prio_key = np.where(is_ges, np.where(onc, "ges_onc", "ges_other"), kind)
    for key in ("cne", "iq", "ges_onc", "ges_other"):
        idx = np.flatnonzero(prio_key == key)
        if len(idx):
            counts = hamilton({p: mixes[key][p] for p in PRIORITY_ORDER}, len(idx))
            priority[idx] = _permute(labels(counts, list(PRIORITY_ORDER)), r_prio)

    # ---- 5. Edad por clase de especialidad ----------------------------------------------
    ped = np.array([specs[str(s)].pediatric for s in spec], dtype=bool)
    age = np.empty(n, dtype=object)
    for is_ped, key in ((True, "pediatric_age_mix"), (False, "general_age_mix")):
        idx = np.flatnonzero(ped == is_ped)
        if len(idx):
            mix = a.value(key)
            counts = hamilton({g: mix[g] for g in AGE_ORDER}, len(idx))
            age[idx] = _permute(labels(counts, list(AGE_ORDER)), r_attr)

    # ---- 6. Pacientes por entrada -------------------------------------------------------
    retries = int(a.value("patient_link_retries"))
    entry_patient = np.full(n, -1, dtype=np.int64)
    p_service: list[int] = []
    p_age: list[str] = []
    p_specs: list[set[str]] = []
    for kd, rows in (("cne", cne_rows), ("iq", iq_rows)):
        for svc, (count, persons, _, _) in rows.items():
            idx = np.flatnonzero((kind == kd) & (service == svc))
            if not len(idx):
                continue
            idx = _permute(idx, r_link)
            e = len(idx)
            target = min(e, max(1, round(e / (count / persons))))
            seen: dict[str, int] = {}
            for pos, ei in enumerate(idx):
                seen.setdefault(str(age[ei]), pos)
            chosen = sorted(seen.values())
            if len(chosen) < target:
                chosen_set = set(chosen)
                for pos in range(e):
                    if len(chosen) >= target:
                        break
                    if pos not in chosen_set:
                        chosen.append(pos)
                        chosen_set.add(pos)
            chosen_set = set(chosen)
            by_age: dict[str, list[int]] = {}
            for pos in sorted(chosen_set):
                pid = len(p_service)
                ei = int(idx[pos])
                entry_patient[ei] = pid
                p_service.append(svc)
                p_age.append(str(age[ei]))
                p_specs.append({str(spec[ei])})
                by_age.setdefault(str(age[ei]), []).append(pid)
            extras = [pos for pos in range(e) if pos not in chosen_set]
            u = r_link.random((len(extras), retries))
            for j, pos in enumerate(extras):
                ei = int(idx[pos])
                cand = by_age[str(age[ei])]
                s = str(spec[ei])
                pid = cand[int(u[j, 0] * len(cand))]
                for tr in range(1, retries):
                    if s not in p_specs[pid]:
                        break
                    pid = cand[int(u[j, tr] * len(cand))]
                entry_patient[ei] = pid
                p_specs[pid].add(s)
    for ei in np.flatnonzero(is_ges):
        entry_patient[ei] = len(p_service)
        p_service.append(int(service[ei]))
        p_age.append(str(age[ei]))
        p_specs.append({str(spec[ei])})
    n_pat = len(p_service)
    pat_service = np.array(p_service, dtype=np.int64)
    pat_age = np.array(p_age, dtype=object)

    ins_mix = a.insurance_mix()
    ins_counts = hamilton({k: ins_mix[k] for k in INSURANCE_ORDER}, n_pat)
    pat_ins = _permute(labels(ins_counts, list(INSURANCE_ORDER)), r_attr)

    pat_commune = np.empty(n_pat, dtype=object)
    hosp_by_service: dict[int, list[tuple[str, str, str | None]]] = {}
    for h in t.establishments:
        hosp_by_service.setdefault(h.health_service_code, []).append(
            (h.code, h.commune_code, h.complexity)
        )
    comm_w = commune_weights(t, a)
    for svc in sorted(set(p_service)):
        idx = np.flatnonzero(pat_service == svc)
        weights = comm_w[svc]
        counts = hamilton(dict(sorted(weights.items())), len(idx))
        pat_commune[idx] = _permute(labels(counts, sorted(weights)), r_attr)

    # ---- 7. Establecimiento (hospital del servicio) -------------------------------------
    hw = a.value("hospital_complexity_weights")
    estab = np.empty(n, dtype=object)
    for svc in sorted(set(service.tolist())):
        idx = np.flatnonzero(service == svc)
        hospitals = sorted(hosp_by_service[svc])
        weights = {h[0]: float(hw.get(h[2] or "", 1.0)) for h in hospitals}
        counts = hamilton(weights, len(idx))
        estab[idx] = _permute(labels(counts, list(weights)), r_attr)

    # ---- 8. Marcos de datos -----------------------------------------------------------
    run_s = str(run_id)
    pat_ids = [str(uuid.uuid5(run_id, f"patient:{i}")) for i in range(n_pat)]
    ent_ids = [str(uuid.uuid5(run_id, f"entry:{i}")) for i in range(n)]
    entry_dates = [as_of - timedelta(days=int(w)) for w in wait]
    deadlines: list[date | None] = [None] * n
    for k in range(n_ges):
        i = ges_base + k
        deadlines[i] = entry_dates[i] + timedelta(days=int(ges_deadline_days[k]))

    patient = pl.DataFrame(
        {
            "id": pat_ids,
            "run_id": [run_s] * n_pat,
            "health_service_code": pat_service,
            "commune_code": pat_commune.tolist(),
            "age_group": pat_age.tolist(),
            "insurance": pat_ins.tolist(),
        },
        schema={
            "id": pl.String,
            "run_id": pl.String,
            "health_service_code": pl.Int64,
            "commune_code": pl.String,
            "age_group": pl.String,
            "insurance": pl.String,
        },
    ).select(PATIENT_COLUMNS)
    entry = pl.DataFrame(
        {
            "id": ent_ids,
            "run_id": [run_s] * n,
            "patient_id": [pat_ids[p] for p in entry_patient],
            "health_service_code": service,
            "establishment_code": estab.tolist(),
            "specialty_code": spec.tolist(),
            "procedure_code": procedure.tolist(),
            "care_type": care_type.tolist(),
            "care_subtype": care_subtype.tolist(),
            "clinical_priority": priority.tolist(),
            "is_ges": is_ges,
            "ges_problem_code": [
                int(p) if g else None for p, g in zip(problem, is_ges, strict=True)
            ],
            "ges_deadline": deadlines,
            "entry_date": entry_dates,
            "status": ["waiting"] * n,
            "resolved_on": [None] * n,
        },
        schema={
            "id": pl.String,
            "run_id": pl.String,
            "patient_id": pl.String,
            "health_service_code": pl.Int64,
            "establishment_code": pl.String,
            "specialty_code": pl.String,
            "procedure_code": pl.String,
            "care_type": pl.String,
            "care_subtype": pl.String,
            "clinical_priority": pl.String,
            "is_ges": pl.Boolean,
            "ges_problem_code": pl.Int64,
            "ges_deadline": pl.Date,
            "entry_date": pl.Date,
            "status": pl.String,
            "resolved_on": pl.Date,
        },
    ).select(ENTRY_COLUMNS)
    return patient, entry


def universe_for(t: CalibrationTargets, a: Assumptions) -> Universe:
    """Atajo para reutilizar el universo desde validación y oferta."""
    return build_universe(t, a)
