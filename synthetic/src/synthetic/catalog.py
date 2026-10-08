"""Catálogos globales: servicios, comunas, establecimientos, especialidades, GES, procedimientos."""

from dataclasses import dataclass

import polars as pl
from shared.schemas import CareSubtype, CareType

from synthetic.targets import Assumptions, CalibrationTargets
from synthetic.taxonomy import (
    GROUP_CNE_DENTAL,
    GROUP_CNE_MEDICAL,
    GROUP_IQ,
    GROUP_TO_CARE,
    is_pediatric,
    specialty_code,
)


@dataclass(frozen=True)
class SpecialtyInfo:
    """Metadatos de una especialidad del catálogo."""

    code: str
    group: str
    name: str
    care_type: CareType
    care_subtype: CareSubtype | None
    pediatric: bool


def specialty_index(t: CalibrationTargets) -> dict[str, SpecialtyInfo]:
    """Índice código -> metadatos de especialidad, en orden determinista."""
    out: dict[str, SpecialtyInfo] = {}
    for row in sorted(t.specialties, key=lambda r: (r.group, r.name)):
        code = specialty_code(row.group, row.name)
        care_type, subtype = GROUP_TO_CARE[row.group]
        out[code] = SpecialtyInfo(
            code, row.group, row.name, care_type, subtype, is_pediatric(row.name)
        )
    return out


def consultation_procedure_code(spec_code: str) -> str:
    """Código del procedimiento 'consulta nueva' de una especialidad CNE."""
    code = f"{spec_code}:cn"
    if len(code) > 80:
        raise ValueError(f"código de procedimiento demasiado largo: {code}")
    return code


@dataclass(frozen=True)
class IqProcedure:
    """Procedimiento quirúrgico genérico de una especialidad IQ."""

    code: str
    specialty_code: str
    name: str
    care_subtype: CareSubtype
    duration_min: int
    weight: float


def iq_procedures(t: CalibrationTargets, a: Assumptions) -> list[IqProcedure]:
    """Procedimientos IQ con código determinista ``<especialidad>:<subtipo>_<n>``."""
    names = {r.name for r in t.specialties if r.group == GROUP_IQ}
    counters: dict[tuple[str, str], int] = {}
    out: list[IqProcedure] = []
    for spec in a.iq_procedures:
        if spec.specialty not in names:
            raise ValueError(f"especialidad IQ desconocida en supuestos: {spec.specialty}")
        sc = specialty_code(GROUP_IQ, spec.specialty)
        key = (sc, spec.care_subtype)
        counters[key] = counters.get(key, 0) + 1
        out.append(
            IqProcedure(
                code=f"{sc}:{spec.care_subtype}_{counters[key]}",
                specialty_code=sc,
                name=spec.name,
                care_subtype=CareSubtype(spec.care_subtype),
                duration_min=spec.duration_min,
                weight=spec.weight,
            )
        )
    missing = names - {s.specialty for s in a.iq_procedures}
    if missing:
        raise ValueError(f"especialidades IQ sin procedimientos: {sorted(missing)}")
    return out


def ges_specialty_code(group: str, name: str, t: CalibrationTargets) -> str:
    """Código de la especialidad en que se resuelve un problema GES (valida que exista)."""
    code = specialty_code(group, name)
    if code not in specialty_index(t):
        raise ValueError(f"especialidad de mapeo GES inexistente: {group}/{name}")
    return code


def build_catalogs(t: CalibrationTargets, a: Assumptions) -> dict[str, pl.DataFrame]:
    """Construye los catálogos (``health_service``, ``commune``, ``establishment``, ...)."""
    services = {r.health_service_code: r.health_service for r in t.service_rows}
    health_service = pl.DataFrame(
        {"code": sorted(services), "name": [services[c] for c in sorted(services)]},
        schema={"code": pl.Int64, "name": pl.String},
    )
    commune = pl.DataFrame(
        {
            "code": [c.code for c in t.communes],
            "name": [c.name for c in t.communes],
            "region_code": [c.region_code for c in t.communes],
        },
        schema={"code": pl.String, "name": pl.String, "region_code": pl.Int64},
    )
    establishment = pl.DataFrame(
        {
            "code": [e.code for e in t.establishments],
            "name": [e.name for e in t.establishments],
            "health_service_code": [e.health_service_code for e in t.establishments],
            "commune_code": [e.commune_code for e in t.establishments],
            "complexity": [e.complexity for e in t.establishments],
        },
        schema={
            "code": pl.String,
            "name": pl.String,
            "health_service_code": pl.Int64,
            "commune_code": pl.String,
            "complexity": pl.String,
        },
    )
    specs = specialty_index(t)
    specialty = pl.DataFrame(
        {
            "code": list(specs),
            "name": [s.name for s in specs.values()],
            "care_type": [s.care_type.value for s in specs.values()],
            "care_subtype": [
                s.care_subtype.value if s.care_subtype else None for s in specs.values()
            ],
        },
        schema={
            "code": pl.String,
            "name": pl.String,
            "care_type": pl.String,
            "care_subtype": pl.String,
        },
    )
    mapping = {m.code: m for m in a.ges_problem_map}
    g_code: list[int] = []
    g_name: list[str] = []
    g_deadline: list[int | None] = []
    g_spec: list[str | None] = []
    g_care: list[str | None] = []
    for p in t.ges_problems:
        g_code.append(p.code)
        g_name.append(p.name)
        m = mapping.get(p.code)
        if m is None:
            g_deadline.append(None)
            g_spec.append(None)
            g_care.append(None)
        else:
            sc = ges_specialty_code(m.group, m.specialty, t)
            g_deadline.append(m.deadline_days)
            g_spec.append(sc)
            g_care.append(specs[sc].care_type.value)
    ges_problem = pl.DataFrame(
        {
            "code": g_code,
            "name": g_name,
            "deadline_days": g_deadline,
            "specialty_code": g_spec,
            "care_type": g_care,
        },
        schema={
            "code": pl.Int64,
            "name": pl.String,
            "deadline_days": pl.Int64,
            "specialty_code": pl.String,
            "care_type": pl.String,
        },
    )
    default_min = int(a.value("consult_min")["default"])
    overrides: dict[str, int] = a.value("consult_min")["overrides"]
    rows: list[dict[str, object]] = []
    for code, info in specs.items():
        if info.group in (GROUP_CNE_MEDICAL, GROUP_CNE_DENTAL):
            rows.append(
                {
                    "code": consultation_procedure_code(code),
                    "specialty_code": code,
                    "name": "Consulta nueva de especialidad",
                    "care_subtype": info.care_subtype.value if info.care_subtype else None,
                    "duration_min": int(overrides.get(info.name, default_min)),
                    "ges_problem_code": None,
                }
            )
    rows += [
        {
            "code": p.code,
            "specialty_code": p.specialty_code,
            "name": p.name,
            "care_subtype": p.care_subtype.value,
            "duration_min": p.duration_min,
            "ges_problem_code": None,
        }
        for p in iq_procedures(t, a)
    ]
    procedure = pl.DataFrame(
        rows,
        schema={
            "code": pl.String,
            "specialty_code": pl.String,
            "name": pl.String,
            "care_subtype": pl.String,
            "duration_min": pl.Int64,
            "ges_problem_code": pl.Int64,
        },
    )
    return {
        "health_service": health_service,
        "commune": commune,
        "establishment": establishment,
        "specialty": specialty,
        "ges_problem": ges_problem,
        "procedure": procedure,
    }


def procedure_durations(t: CalibrationTargets, a: Assumptions) -> dict[str, int]:
    """Duración en minutos de cada procedimiento (consulta nueva e IQ genéricos)."""
    default_min = int(a.value("consult_min")["default"])
    overrides: dict[str, int] = a.value("consult_min")["overrides"]
    out: dict[str, int] = {}
    for code, info in specialty_index(t).items():
        if info.group in (GROUP_CNE_MEDICAL, GROUP_CNE_DENTAL):
            out[consultation_procedure_code(code)] = int(overrides.get(info.name, default_min))
    for p in iq_procedures(t, a):
        out[p.code] = p.duration_min
    return out
