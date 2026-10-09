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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
from noshow.cli import current_generator_shas  # type: ignore[import-untyped]
from noshow.data import find_run_dir  # type: ignore[import-untyped]
from priority.adapters import rank_frame
from priority.explain import explain_ranked, explanation_to_dict
from priority.score import Ranking
from scheduler.adapters import RunInfo, read_run_info

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


@dataclass
class RunCatalog:
    """Lista de espera de la corrida con puntajes; solo lectura."""

    info: RunInfo
    rules: RuleSet
    entries: pl.DataFrame  # todas las entradas; rank/score/tier nulos si no están en espera
    patients: pl.DataFrame
    rankings: dict[str, Ranking]  # entry_id -> ranking de su cola

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
        return cls(info=info, rules=rules, entries=joined, patients=patients, rankings=by_entry)

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
            ranking = self.rankings.get(row["entry_id"])
            if ranking is not None:
                explanation = explanation_to_dict(
                    explain_ranked(ranking, row["entry_id"], self.rules)
                )
            out.append(
                {
                    **{c: row[c] for c in WAITLIST_COLUMNS},
                    "status": row["status"],
                    "explanation": explanation,
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
