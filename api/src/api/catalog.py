"""Corrida sintética en memoria: lista de espera con puntaje, puesto y explicación.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Solo lee las tablas `patient` y `waitlist_entry` de la corrida (nunca las tablas de verdad
sintética). El puntaje y la explicación salen de `priority`; la prioridad clínica es un dato
de entrada y no se modifica. El puesto (`rank`) es dentro de la cola de la entrada (servicio de
salud, especialidad y tipo de atención).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from noshow.cli import current_generator_shas  # type: ignore[import-untyped]
from noshow.data import find_run_dir  # type: ignore[import-untyped]
from priority.adapters import rank_frame
from priority.explain import explain_ranked, explanation_to_dict
from priority.score import Ranking
from scheduler.adapters import RunInfo, read_run_info
from scheduler.instance import LOCAL_TZ

from api.settings import ApiSettings
from priority import RuleSet, load_default_rules

SORT_COLUMNS: dict[str, tuple[str, bool]] = {
    "rank": ("rank", False),
    "score": ("score", True),
    "entry_date": ("entry_date", False),
}

WAITLIST_COLUMNS = (
    "entry_id",
    "patient_id",
    "health_service_code",
    "specialty_code",
    "care_type",
    "clinical_priority",
    "is_ges",
    "ges_deadline",
    "entry_date",
    "wait_days",
    "score",
    "rank",
    "tier",
)


log = logging.getLogger("api.catalog")


class CatalogUnavailable(RuntimeError):
    """La corrida sintética no se pudo ubicar o leer."""


def resolve_run_dir(settings: ApiSettings) -> Path:
    """Directorio de la corrida: `run_dir` explícito o la única que coincide con la semilla."""
    if settings.run_dir is not None:
        if not (settings.run_dir / "manifest.json").exists():
            raise CatalogUnavailable(
                f"no hay corrida sintética en el directorio configurado ({settings.run_dir.name})"
            )
        return settings.run_dir
    try:
        path: Path = find_run_dir(
            settings.data_dir,
            settings.seed,
            settings.size,
            settings.scenario,
            current_generator_shas(),
        )
    except FileNotFoundError as exc:
        raise CatalogUnavailable(
            f"no hay corrida sintética con semilla {settings.seed}, tamaño {settings.size} y "
            f"escenario {settings.scenario}; ejecuta `make synth`"
        ) from exc
    except FileExistsError as exc:
        raise CatalogUnavailable(
            "hay más de una corrida que coincide; fija PRIORIZA_API_RUN_DIR"
        ) from exc
    return path


HISTOGRAM_STEP = 30
HISTOGRAM_MAX = 720
GES_RISK_DAYS = 30


@dataclass
class RunCatalog:
    """Lista de espera de la corrida con puntajes; solo lectura."""

    info: RunInfo
    rules: RuleSet
    entries: pl.DataFrame  # todas las entradas; rank/score/tier nulos si no están en espera
    patients: pl.DataFrame
    rankings: dict[str, Ranking]  # entry_id -> ranking de su cola
    slots: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    resources: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    _summary_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, run_dir: Path, rules: RuleSet | None = None) -> RunCatalog:
        info = read_run_info(run_dir)
        rules = rules or load_default_rules()
        entries = pl.read_parquet(
            run_dir / "waitlist_entry.parquet",
            columns=[
                "id",
                "patient_id",
                "health_service_code",
                "specialty_code",
                "care_type",
                "clinical_priority",
                "is_ges",
                "ges_deadline",
                "entry_date",
                "status",
            ],
        ).with_columns(pl.col("id").cast(pl.String), pl.col("patient_id").cast(pl.String))
        waiting = entries.filter(pl.col("status") == "waiting")
        rankings = rank_frame(waiting, rules, as_of=info.as_of)
        by_entry: dict[str, Ranking] = {}
        rows: list[tuple[str, float, int, str, int]] = []
        for ranking in rankings.values():
            for r in ranking.entries:
                s = r.score
                by_entry[s.entry_id] = ranking
                rows.append((s.entry_id, s.score, r.rank, s.tier.name, s.wait_days))
        scored = pl.DataFrame(
            rows,
            schema={
                "id": pl.String,
                "score": pl.Float64,
                "rank": pl.Int64,
                "tier": pl.String,
                "wait_days": pl.Int64,
            },
            orient="row",
        )
        joined = entries.join(scored, on="id", how="left").rename({"id": "entry_id"})
        patients = pl.read_parquet(
            run_dir / "patient.parquet",
            columns=["id", "health_service_code", "commune_code", "age_group", "insurance"],
        ).with_columns(pl.col("id").cast(pl.String))
        # Slots y recursos para el calendario del plan; no bloquean si faltan.
        slots_path = run_dir / "slot.parquet"
        resources_path = run_dir / "resource.parquet"
        slots = pl.DataFrame()
        resources = pl.DataFrame()
        if slots_path.exists() and resources_path.exists():
            try:
                slots = pl.read_parquet(
                    slots_path,
                    columns=[
                        "id",
                        "resource_id",
                        "specialty_code",
                        "start_at",
                        "duration_min",
                        "unit_min",
                    ],
                ).with_columns(pl.col("id").cast(pl.String), pl.col("resource_id").cast(pl.String))
                resources = pl.read_parquet(
                    resources_path,
                    columns=[
                        "id",
                        "kind",
                        "establishment_code",
                        "health_service_code",
                        "specialty_code",
                        "label",
                    ],
                ).with_columns(pl.col("id").cast(pl.String))
            except (OSError, pl.exceptions.PolarsError):
                log.warning("no se pudieron leer slots/recursos de %s", run_dir.name)
                slots = pl.DataFrame()
                resources = pl.DataFrame()
        return cls(
            info=info,
            rules=rules,
            entries=joined,
            patients=patients,
            rankings=by_entry,
            slots=slots,
            resources=resources,
        )

    def waitlist_page(
        self,
        *,
        filters: dict[str, Any],
        order_by: str,
        limit: int,
        offset: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Entradas en espera filtradas y ordenadas; devuelve (total, página)."""
        df = self.entries.filter(pl.col("rank").is_not_null())
        for column, value in filters.items():
            if value is not None:
                df = df.filter(pl.col(column) == value)
        column, descending = SORT_COLUMNS[order_by]
        df = df.sort([column, "entry_id"], descending=[descending, False])
        page = df.slice(offset, limit).select(WAITLIST_COLUMNS)
        return df.height, page.to_dicts()

    def patient(self, patient_id: str) -> dict[str, Any] | None:
        """Atributos del paciente sintético y sus entradas con la explicación del puntaje."""
        found = self.patients.filter(pl.col("id") == patient_id)
        if found.is_empty():
            return None
        entries = self.entries.filter(pl.col("patient_id") == patient_id).sort(
            "entry_date", "entry_id"
        )
        out: list[dict[str, Any]] = []
        for row in entries.iter_rows(named=True):
            explanation = None
            components = None
            ranking = self.rankings.get(row["entry_id"])
            if ranking is not None:
                explanation = explanation_to_dict(
                    explain_ranked(ranking, row["entry_id"], self.rules)
                )
                # Desglose numérico del puntaje.
                ranked = ranking.get(row["entry_id"])
                components = [
                    {
                        "field": c.field,
                        "label": c.label,
                        "raw_value": c.raw_value,
                        "normalized": c.normalized,
                        "weight": c.weight,
                        "contribution": c.contribution,
                    }
                    for c in ranked.score.components
                ]
            out.append(
                {
                    **{c: row[c] for c in WAITLIST_COLUMNS},
                    "status": row["status"],
                    "explanation": explanation,
                    "components": components,
                }
            )
        patient = found.row(0, named=True)
        return {
            "patient_id": patient_id,
            "health_service_code": patient["health_service_code"],
            "commune_code": patient["commune_code"],
            "age_group": patient["age_group"],
            "insurance": patient["insurance"],
            "entries": out,
        }

    def calendar(
        self,
        counts: pl.DataFrame,
        *,
        horizon_start: date,
        horizon_end: date,
        resource_kind: str | None = None,
        health_service_code: int | None = None,
    ) -> pl.DataFrame:
        """Calendario del plan por recurso y día local (todas las filas, ordenadas)."""
        return _calendar_frame(
            self.slots,
            self.resources,
            counts,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            resource_kind=resource_kind,
            health_service_code=health_service_code,
        )

    def waitlist_summary(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resumen de las entradas en espera, calculado una vez por combinación de filtros."""
        active = {k: v for k, v in (filters or {}).items() if v is not None}
        cache_key = repr(sorted(active.items()))
        cached = self._summary_cache.get(cache_key)
        if cached is not None:
            return cached
        df = self.entries.filter(pl.col("rank").is_not_null())
        for column, value in active.items():
            df = df.filter(pl.col(column) == value)
        result = {
            "as_of": self.info.as_of,
            "run_id": self.info.run_id,
            "run_entries": self.entries.height,
            **_summarize(df, self.info.as_of),
        }
        result["by_care_type"] = [
            {"care_type": ct, **_summarize(df.filter(pl.col("care_type") == ct), self.info.as_of)}
            for ct in ("consultation", "surgery")
        ]
        result["wait_histogram"] = _histogram(df)
        self._summary_cache[cache_key] = result
        return result


def _calendar_frame(
    slots: pl.DataFrame,
    resources: pl.DataFrame,
    counts: pl.DataFrame,
    *,
    horizon_start: date,
    horizon_end: date,
    resource_kind: str | None,
    health_service_code: int | None,
) -> pl.DataFrame:
    """Carga por recurso y día local dentro del horizonte (cupos CNE o minutos de pabellón)."""
    df = (
        slots.rename({"id": "slot_id"})
        .drop("specialty_code")
        .join(
            resources.rename(
                {"id": "resource_id", "kind": "resource_kind", "label": "resource_label"}
            ),
            on="resource_id",
            how="inner",
        )
        .with_columns(pl.col("start_at").dt.convert_time_zone(LOCAL_TZ.key).dt.date().alias("date"))
        .filter((pl.col("date") >= horizon_start) & (pl.col("date") <= horizon_end))
    )
    if resource_kind is not None:
        df = df.filter(pl.col("resource_kind") == resource_kind)
    if health_service_code is not None:
        df = df.filter(pl.col("health_service_code") == health_service_code)
    df = df.join(counts, on="slot_id", how="left").with_columns(
        pl.col("scheduled", "overbooked").fill_null(0),
        pl.when(pl.col("resource_kind") == "specialist_agenda")
        .then(pl.col("duration_min") // pl.col("unit_min"))
        .otherwise(pl.col("duration_min"))
        .alias("capacity"),
    )
    return (
        df.group_by(
            "resource_id",
            "resource_label",
            "resource_kind",
            "health_service_code",
            "specialty_code",
            "date",
        )
        .agg(
            pl.len().cast(pl.Int64).alias("blocks"),
            pl.col("capacity").sum().cast(pl.Int64),
            pl.col("scheduled").sum().cast(pl.Int64),
            pl.col("overbooked").sum().cast(pl.Int64),
        )
        .sort("resource_label", "resource_id", "date")
    )


def _summarize(df: pl.DataFrame, as_of: date) -> dict[str, Any]:
    """Total, mediana y p90 de espera, y conteos GES (en riesgo: plazo en 30 días o menos)."""
    waits = df["wait_days"]
    left = (pl.col("ges_deadline") - pl.lit(as_of)).dt.total_days()
    ges = df.filter(pl.col("is_ges") & pl.col("ges_deadline").is_not_null())
    return {
        "total": df.height,
        "wait_median": None if df.is_empty() else float(waits.median() or 0.0),  # type: ignore[arg-type]
        "wait_p90": None if df.is_empty() else float(waits.quantile(0.9, "linear") or 0.0),
        "ges_total": int(df.filter(pl.col("is_ges")).height),
        "ges_at_risk": ges.filter((left >= 0) & (left <= GES_RISK_DAYS)).height,
        "ges_overdue": ges.filter(left < 0).height,
    }


def _histogram(df: pl.DataFrame) -> list[dict[str, Any]]:
    """Tramos de 30 días de 0 a 720 y uno final de 720 o más."""
    waits = df["wait_days"].clip(lower_bound=0)
    counts = (
        pl.DataFrame(
            {"bin": (waits // HISTOGRAM_STEP).clip(upper_bound=HISTOGRAM_MAX // HISTOGRAM_STEP)}
        )
        .group_by("bin")
        .len()
    )
    by_bin = dict(zip(counts["bin"].to_list(), counts["len"].to_list(), strict=True))
    last = HISTOGRAM_MAX // HISTOGRAM_STEP
    out: list[dict[str, Any]] = []
    for i in range(last + 1):
        start = i * HISTOGRAM_STEP
        end = None if i == last else start + HISTOGRAM_STEP
        out.append({"from_day": start, "to_day": end, "count": int(by_bin.get(i, 0))})
    return out


class CatalogProvider:
    """Carga perezosa (una vez) de la corrida; la app arranca aunque no haya datos."""

    def __init__(self, settings: ApiSettings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._catalog: RunCatalog | None = None

    def run_dir(self) -> Path:
        return resolve_run_dir(self._settings)

    def run_id(self) -> str | None:
        """Id de la corrida (lee solo `manifest.json`); `None` si no está disponible."""
        try:
            return read_run_info(self.run_dir()).run_id
        except (CatalogUnavailable, OSError, KeyError, ValueError):
            return None

    def get(self) -> RunCatalog:
        with self._lock:
            if self._catalog is None:
                try:
                    self._catalog = RunCatalog.load(self.run_dir())
                except CatalogUnavailable:
                    raise
                except (OSError, KeyError, ValueError, pl.exceptions.PolarsError) as exc:
                    log.exception("no se pudo leer la corrida sintética")
                    raise CatalogUnavailable(
                        "no se pudo leer la corrida sintética (ver el log del servidor)"
                    ) from exc
            return self._catalog
