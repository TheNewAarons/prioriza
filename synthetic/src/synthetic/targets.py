"""Objetivos de calibración (datos públicos agregados) y supuestos versionados.

``build_targets`` lee los parquet de ``data/processed`` y produce ``CalibrationTargets``;
``load_targets`` y ``load_assumptions`` leen los JSON versionados (sin red ni parquet).
Los supuestos viven en ``targets/assumptions.json``: cada parámetro lleva ``value``,
``source``, ``justification`` y ``verified``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")

SCHEMA_VERSION = 1
CNE = "consultation"
IQ = "surgery"
QUARTERS = ("glosa06_2025q3", "glosa06_2025q4", "glosa06_2026q1")
SIS_SOURCE = "sis_ges_cases_2026q1"
ESTABLISHMENTS_SOURCE = "minsal_establishments"
# Semanas entre III-2025 (2025-09-30) e I-2026 (2026-03-31), para la tendencia de la lista.
TREND_WEEKS = 26


class SourceInfo(BaseModel):
    """Procedencia de un parquet usado en los objetivos."""

    model_config = _FROZEN

    source_id: str
    period: str | None
    parquet_sha256: str
    raw_sha256: str | None
    tables: list[str]


class ServiceRow(BaseModel):
    """Cifras por (servicio de salud, tipo de prestación) de una lista no GES."""

    model_config = _FROZEN

    health_service_code: int
    health_service: str
    care_type: str
    waiting_count: int
    persons_count: int
    mean_wait_days: float
    median_wait_days: float


class NationalRow(BaseModel):
    """Cifras nacionales de un tipo de lista."""

    model_config = _FROZEN

    key: str
    waiting_count: int
    persons_count: int | None
    mean_wait_days: float | None
    median_wait_days: float | None


class SubtypeRow(BaseModel):
    """Registros nacionales por subtipo (médica, dental, mayor, menor)."""

    model_config = _FROZEN

    care_type: str
    care_subtype: str
    waiting_count: int
    persons_count: int


class SpecialtyRow(BaseModel):
    """Registros por especialidad en la taxonomía de su grupo (cne_medical, cne_dental, iq)."""

    model_config = _FROZEN

    group: str
    name: str
    waiting_count: int


class GesServiceRow(BaseModel):
    """Garantías GES retrasadas por servicio."""

    model_config = _FROZEN

    health_service_code: int
    health_service: str
    waiting_count: int


class GesProblemRow(BaseModel):
    """Garantías GES retrasadas por problema, con retraso sobre el plazo y casos nuevos FONASA."""

    model_config = _FROZEN

    code: int
    name: str
    delayed_count: int
    mean_delay_days: float | None
    median_delay_days: float | None
    ytd_new_cases_fonasa_2025: int | None


class EstablishmentRow(BaseModel):
    """Hospital público operativo del SNSS (nombre público del establecimiento)."""

    model_config = _FROZEN

    code: str
    name: str
    health_service_code: int
    commune_code: str
    complexity: str | None


class CommuneRow(BaseModel):
    """Comuna con su región."""

    model_config = _FROZEN

    code: str
    name: str
    region_code: int


class CommuneServiceRow(BaseModel):
    """Conteo de establecimientos de APS por (comuna, servicio), por clase de establecimiento."""

    model_config = _FROZEN

    commune_code: str
    health_service_code: int
    cesfam_like: int
    cecosf: int
    psr: int


class SeriesRow(BaseModel):
    """Serie nacional trimestral."""

    model_config = _FROZEN

    source_id: str
    period: str
    key: str
    waiting_count: int
    persons_count: int | None
    mean_wait_days: float | None
    median_wait_days: float | None


class ArrivalRow(BaseModel):
    """Tasa de llegada semanal: lambda_in = rendimiento (Little) + cambio neto de la lista."""

    model_config = _FROZEN

    care_type: str
    health_service_code: int | None
    weekly_throughput: float
    weekly_net_change: float
    weekly_lambda_in: float


class CalibrationTargets(BaseModel):
    """Objetivos de calibración derivados de datos públicos agregados."""

    model_config = _FROZEN

    schema_version: int = SCHEMA_VERSION
    reference_source_id: str
    sources: list[SourceInfo]
    service_rows: list[ServiceRow]
    national: list[NationalRow]
    subtypes: list[SubtypeRow]
    specialties: list[SpecialtyRow]
    ges_services: list[GesServiceRow]
    ges_problems: list[GesProblemRow]
    establishments: list[EstablishmentRow]
    communes: list[CommuneRow]
    commune_service: list[CommuneServiceRow]
    series: list[SeriesRow]
    arrivals: list[ArrivalRow]

    def national_row(self, key: str) -> NationalRow:
        """Cifras nacionales por clave (``consultation``, ``surgery``, ``ges``)."""
        for row in self.national:
            if row.key == key:
                return row
        raise KeyError(key)


# ------------------------------------------------------------------ Supuestos


class Param(BaseModel):
    """Un parámetro con su procedencia."""

    model_config = _FROZEN

    value: Any
    source: str
    justification: str
    verified: bool


class GesMapping(BaseModel):
    """Problema GES mapeado a una especialidad en la que se resuelve."""

    model_config = _FROZEN

    code: int
    group: str
    specialty: str
    deadline_days: int
    oncologic: bool = False
    source: str
    justification: str
    verified: bool


class ProcedureSpec(BaseModel):
    """Procedimiento genérico de una especialidad quirúrgica."""

    model_config = _FROZEN

    specialty: str
    name: str
    care_subtype: str
    duration_min: int
    weight: float = 1.0


class Assumptions(BaseModel):
    """Supuestos del generador, cada uno con valor, fuente, justificación y verificación."""

    model_config = _FROZEN

    schema_version: int = SCHEMA_VERSION
    parameters: dict[str, Param]
    ges_problem_map: list[GesMapping]
    iq_procedures: list[ProcedureSpec]
    iq_procedures_source: str = Field(
        description="Procedencia de los procedimientos genéricos (supuesto)."
    )

    def value(self, name: str) -> Any:
        """Valor de un parámetro por nombre."""
        return self.parameters[name].value

    def unverified(self) -> list[str]:
        """Nombres de los parámetros no verificados (para el informe)."""
        names = [k for k, p in sorted(self.parameters.items()) if not p.verified]
        names += [f"ges_problem_map[{m.code}]" for m in self.ges_problem_map if not m.verified]
        return names

    def insurance_mix(self) -> dict[str, float]:
        """Proporciones de previsión, calculadas de los conteos de la población inscrita en APS."""
        counts: dict[str, int] = self.value("insurance_aps_counts")["counts"]
        total = sum(counts.values())
        return {k: v / total for k, v in counts.items()}


# ------------------------------------------------------------------ E/S canónica


def canonical_json(model: BaseModel) -> str:
    """JSON canónico: claves ordenadas, separadores compactos y sin marcas de tiempo."""
    payload = model.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def write_json_canonical(model: BaseModel, path: Path) -> str:
    """Escribe el modelo en JSON canónico y devuelve el sha256 del contenido."""
    text = canonical_json(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_text(model: BaseModel) -> str:
    """sha256 del JSON canónico del modelo (sin escribir a disco)."""
    return hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()


def _default_path(name: str) -> Path:
    return Path(str(resources.files("synthetic") / "targets" / name))


def load_targets(path: Path | None = None) -> CalibrationTargets:
    """Carga ``calibration_targets.json`` (por defecto, el versionado en el paquete)."""
    target = path or _default_path("calibration_targets.json")
    return CalibrationTargets.model_validate_json(target.read_text(encoding="utf-8"))


def load_assumptions(path: Path | None = None) -> Assumptions:
    """Carga ``assumptions.json`` (por defecto, el versionado en el paquete)."""
    target = path or _default_path("assumptions.json")
    return Assumptions.model_validate_json(target.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ Construcción


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _source_info(processed_dir: Path, source_id: str, tables: list[str]) -> SourceInfo:
    parquet = processed_dir / f"{source_id}.parquet"
    meta_path = processed_dir / f"{source_id}.metadata.json"
    raw_sha: str | None = None
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw_sha = meta.get("raw_sha256")
    period: str | None = None
    frame = pl.read_parquet(parquet, columns=["period"]) if "period" in _columns(parquet) else None
    if frame is not None and frame.height:
        period = str(frame["period"].max())
    return SourceInfo(
        source_id=source_id,
        period=period,
        parquet_sha256=_file_sha256(parquet),
        raw_sha256=raw_sha,
        tables=sorted(tables),
    )


def _columns(parquet: Path) -> list[str]:
    return pl.read_parquet_schema(parquet).names()


def _table(frame: pl.DataFrame, name: str) -> pl.DataFrame:
    return frame.filter(pl.col("source_table") == name)


def _service_rows(frame: pl.DataFrame, table: str, care_type: str) -> list[ServiceRow]:
    rows = _table(frame, table).filter(pl.col("health_service_code").is_not_null())
    return [
        ServiceRow(
            health_service_code=int(r["health_service_code"]),
            health_service=str(r["health_service"]),
            care_type=care_type,
            waiting_count=int(r["waiting_count"]),
            persons_count=int(r["persons_count"]),
            mean_wait_days=float(r["mean_wait_days"]),
            median_wait_days=float(r["median_wait_days"]),
        )
        for r in rows.sort("health_service_code").iter_rows(named=True)
    ]


def _national(frame: pl.DataFrame) -> list[NationalRow]:
    out: list[NationalRow] = []
    for key, table in (
        (CNE, "cne_by_service"),
        (IQ, "iq_by_service"),
        ("ges", "ges_delayed_by_problem"),
    ):
        row = _table(frame, table).filter(pl.col("grain") == "national")
        if row.height != 1:
            raise ValueError(f"fila nacional no encontrada en {table}")
        r = row.row(0, named=True)
        persons = r["persons_count"]
        out.append(
            NationalRow(
                key=key,
                waiting_count=int(r["waiting_count"]),
                persons_count=None if persons is None else int(persons),
                mean_wait_days=_opt_float(r["mean_wait_days"]),
                median_wait_days=_opt_float(r["median_wait_days"]),
            )
        )
    return out


def _specialties(frame: pl.DataFrame) -> list[SpecialtyRow]:
    out: list[SpecialtyRow] = []
    for group, table in (
        ("cne_medical", "cne_medical_by_specialty"),
        ("cne_dental", "cne_dental_by_specialty"),
        ("iq", "iq_by_specialty"),
    ):
        sub = _table(frame, table).filter(pl.col("specialty").is_not_null()).sort("specialty")
        out += [
            SpecialtyRow(
                group=group, name=str(r["specialty"]), waiting_count=int(r["waiting_count"])
            )
            for r in sub.iter_rows(named=True)
        ]
    return out


def _ges_problems(frame: pl.DataFrame, sis: pl.DataFrame) -> list[GesProblemRow]:
    ytd = (
        sis.filter((pl.col("insurer") == "fonasa") & (pl.col("period") == date(2025, 12, 31)))
        .select("ges_problem_code", "ytd_new_cases")
        .to_dicts()
    )
    ytd_by_code = {int(r["ges_problem_code"]): r["ytd_new_cases"] for r in ytd}
    rows = _table(frame, "ges_delayed_by_problem").filter(pl.col("ges_problem_code").is_not_null())
    out: list[GesProblemRow] = []
    for r in rows.sort("ges_problem_code").iter_rows(named=True):
        code = int(r["ges_problem_code"])
        value = ytd_by_code.get(code)
        out.append(
            GesProblemRow(
                code=code,
                name=str(r["ges_problem"]),
                delayed_count=int(r["waiting_count"]),
                mean_delay_days=_opt_float(r["mean_wait_days"]),
                median_delay_days=_opt_float(r["median_wait_days"]),
                ytd_new_cases_fonasa_2025=None if value is None else int(value),
            )
        )
    return out


def _establishment_targets(
    est: pl.DataFrame,
) -> tuple[list[EstablishmentRow], list[CommuneRow], list[CommuneServiceRow]]:
    snss = est.filter(
        pl.col("belongs_to_snss")
        & pl.col("is_operating")
        & pl.col("health_service_code").is_not_null()
        & pl.col("commune_code").is_not_null()
    )
    hospitals = snss.filter(pl.col("facility_type") == "Hospital").sort("establishment_code")
    h_rows = [
        EstablishmentRow(
            code=str(r["establishment_code"]),
            name=str(r["name"]),
            health_service_code=int(r["health_service_code"]),
            commune_code=str(r["commune_code"]),
            complexity=r["complexity"],
        )
        for r in hospitals.iter_rows(named=True)
    ]
    ftype = pl.col("facility_type")
    cls = (
        pl.when(ftype.str.contains(r"\((CESFAM|CGU|CGR)\)"))
        .then(pl.lit("cesfam_like"))
        .when(ftype.str.contains(r"\(CECOSF\)"))
        .then(pl.lit("cecosf"))
        .when(ftype.str.contains(r"\(PSR\)"))
        .then(pl.lit("psr"))
        .otherwise(pl.lit("other"))
        .alias("cls")
    )
    pairs = (
        snss.with_columns(cls)
        .filter(pl.col("cls") != "other")
        .group_by("commune_code", "health_service_code", "cls")
        .len()
    )
    wide = pairs.pivot(on="cls", index=["commune_code", "health_service_code"], values="len")
    for col in ("cesfam_like", "cecosf", "psr"):
        if col not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.UInt32).alias(col))
    wide = wide.fill_null(0).sort("commune_code", "health_service_code")
    cs_rows = [
        CommuneServiceRow(
            commune_code=str(r["commune_code"]),
            health_service_code=int(r["health_service_code"]),
            cesfam_like=int(r["cesfam_like"]),
            cecosf=int(r["cecosf"]),
            psr=int(r["psr"]),
        )
        for r in wide.iter_rows(named=True)
    ]
    needed = {r.commune_code for r in cs_rows} | {h.commune_code for h in h_rows}
    communes = (
        snss.filter(pl.col("commune_code").is_in(sorted(needed)))
        .group_by("commune_code", maintain_order=False)
        .agg(pl.col("commune_name").first(), pl.col("region_code").first())
        .sort("commune_code")
    )
    c_rows = [
        CommuneRow(
            code=str(r["commune_code"]),
            name=str(r["commune_name"]),
            region_code=int(r["region_code"]),
        )
        for r in communes.iter_rows(named=True)
    ]
    return h_rows, c_rows, cs_rows


def _series(processed_dir: Path) -> list[SeriesRow]:
    out: list[SeriesRow] = []
    for source_id in QUARTERS:
        frame = pl.read_parquet(processed_dir / f"{source_id}.parquet")
        period = str(frame["period"].max())
        for r in _national(frame):
            out.append(
                SeriesRow(
                    source_id=source_id,
                    period=period,
                    key=r.key,
                    waiting_count=r.waiting_count,
                    persons_count=r.persons_count,
                    mean_wait_days=r.mean_wait_days,
                    median_wait_days=r.median_wait_days,
                )
            )
    return out


def _arrivals(first: pl.DataFrame, last: pl.DataFrame) -> list[ArrivalRow]:
    """lambda_in = 7·L/m (Little, III-2025) + (L_I-2026 - L_III-2025)/26 semanas."""
    out: list[ArrivalRow] = []
    for care_type, table in ((CNE, "cne_by_service"), (IQ, "iq_by_service")):
        a = _table(first, table)
        b = _table(last, table)
        last_by_code = {
            (None if r["health_service_code"] is None else int(r["health_service_code"])): r
            for r in b.iter_rows(named=True)
        }
        for r in a.sort("health_service_code", nulls_last=True).iter_rows(named=True):
            code = None if r["health_service_code"] is None else int(r["health_service_code"])
            later = last_by_code.get(code)
            throughput = 7.0 * float(r["waiting_count"]) / float(r["mean_wait_days"])
            delta = 0.0
            if later is not None:
                delta = (float(later["waiting_count"]) - float(r["waiting_count"])) / TREND_WEEKS
            out.append(
                ArrivalRow(
                    care_type=care_type,
                    health_service_code=code,
                    weekly_throughput=round(throughput, 4),
                    weekly_net_change=round(delta, 4),
                    weekly_lambda_in=round(throughput + delta, 4),
                )
            )
    return out


def build_targets(
    processed_dir: Path, reference_source_id: str = "glosa06_2025q3"
) -> CalibrationTargets:
    """Construye los objetivos desde los parquet procesados (determinista, sin red)."""
    ref = pl.read_parquet(processed_dir / f"{reference_source_id}.parquet")
    last = pl.read_parquet(processed_dir / f"{QUARTERS[-1]}.parquet")
    sis = pl.read_parquet(processed_dir / f"{SIS_SOURCE}.parquet")
    est = pl.read_parquet(processed_dir / f"{ESTABLISHMENTS_SOURCE}.parquet")

    subtypes = [
        SubtypeRow(
            care_type=str(r["care_type"]),
            care_subtype=str(r["care_subtype"]),
            waiting_count=int(r["waiting_count"]),
            persons_count=int(r["persons_count"]),
        )
        for r in _table(ref, "noges_national_by_subtype")
        .sort("care_type", "care_subtype")
        .iter_rows(named=True)
    ]
    ges_services = [
        GesServiceRow(
            health_service_code=int(r["health_service_code"]),
            health_service=str(r["health_service"]),
            waiting_count=int(r["waiting_count"]),
        )
        for r in _table(ref, "ges_delayed_by_service")
        .filter(pl.col("health_service_code").is_not_null())
        .sort("health_service_code")
        .iter_rows(named=True)
    ]
    h_rows, c_rows, cs_rows = _establishment_targets(est)

    sources = [
        _source_info(processed_dir, source_id, sorted(_tables_of(processed_dir, source_id)))
        for source_id in (*QUARTERS, SIS_SOURCE, ESTABLISHMENTS_SOURCE)
    ]
    return CalibrationTargets(
        reference_source_id=reference_source_id,
        sources=sources,
        service_rows=_service_rows(ref, "cne_by_service", CNE)
        + _service_rows(ref, "iq_by_service", IQ),
        national=_national(ref),
        subtypes=subtypes,
        specialties=_specialties(ref),
        ges_services=ges_services,
        ges_problems=_ges_problems(ref, sis),
        establishments=h_rows,
        communes=c_rows,
        commune_service=cs_rows,
        series=_series(processed_dir),
        arrivals=_arrivals(ref, last),
    )


def _tables_of(processed_dir: Path, source_id: str) -> list[str]:
    parquet = processed_dir / f"{source_id}.parquet"
    if "source_table" in _columns(parquet):
        return pl.read_parquet(parquet, columns=["source_table"])["source_table"].unique().to_list()
    return []
