"""Orquestación: descarga, parseo, validación y escritura de cada fuente."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl
from pydantic import ValidationError
from shared.schemas import (
    FACILITY_POLARS_SCHEMA,
    GES_CASES_POLARS_SCHEMA,
    WAITLIST_POLARS_SCHEMA,
)

from ingestion.download import fetch, sha256_file
from ingestion.errors import DataValidationError, IngestionError
from ingestion.normalize import to_frame
from ingestion.output import write_processed
from ingestion.parsers.establishments import parse_establishments_csv
from ingestion.parsers.glosa06 import parse_glosa06_pdf
from ingestion.parsers.sis_ges import parse_sis_ges_xlsx
from ingestion.sources import SOURCES, SourceKind, SourceSpec, get_source
from ingestion.validate import validate_facilities, validate_ges_cases, validate_waitlist

WAITLIST_SORT = (
    "source_table",
    "grain",
    "health_service_code",
    "health_service",
    "specialty",
    "ges_problem_code",
    "care_type",
    "care_subtype",
)


@dataclass
class RunResult:
    """Resultado de procesar una fuente."""

    source_id: str
    ok: bool
    rows: int = 0
    output: Path | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _process(
    spec: SourceSpec, path: Path, provenance: dict[str, object]
) -> tuple[pl.DataFrame, list[str]]:
    """Parsea y valida; devuelve el DataFrame y las advertencias."""
    if spec.kind is SourceKind.GLOSA06_PDF:
        results = parse_glosa06_pdf(path, spec)
        warnings = validate_waitlist(results, spec)
        records = [rec for result in results for rec in result.records]
        provenance["tables"] = {
            r.key: {
                "label": r.label,
                "pages": list(r.pages),
                "rows": len(r.records),
                "cutoff": r.cutoff.isoformat(),
                "extracted_at": r.extracted_at.isoformat() if r.extracted_at else None,
                "published_totals": r.totals,
            }
            for r in results
        }
        frame = to_frame(records, WAITLIST_POLARS_SCHEMA, WAITLIST_SORT)
    elif spec.kind is SourceKind.SIS_GES_XLSX:
        ges_records, totals = parse_sis_ges_xlsx(path, spec)
        warnings = validate_ges_cases(ges_records, totals, spec)
        provenance["tables"] = {
            "ges_cases": {
                "rows": len(ges_records),
                "periods": sorted({r.period.isoformat() for r in ges_records}),
                "rows_per_sheet": dict(Counter(r.source_sheet for r in ges_records)),
            }
        }
        frame = to_frame(
            ges_records, GES_CASES_POLARS_SCHEMA, ("period", "ges_problem_code", "insurer")
        )
    else:
        facilities = parse_establishments_csv(path, spec)
        warnings = validate_facilities(facilities, spec)
        provenance["tables"] = {"facilities": {"rows": len(facilities)}}
        frame = to_frame(facilities, FACILITY_POLARS_SCHEMA, ("establishment_code",))
    return frame, warnings


def run_source(
    source_id: str,
    *,
    data_dir: Path,
    today: date,
    refresh: bool = False,
    offline: bool = False,
    input_path: Path | None = None,
) -> RunResult:
    """Procesa una fuente de punta a punta. Los errores de ingesta quedan en el resultado."""
    spec = get_source(source_id)
    try:
        if input_path is not None:
            path = input_path
            provenance: dict[str, object] = {
                "url": None,
                "local_input": str(input_path),
                "raw_sha256": sha256_file(input_path),
            }
        else:
            download = fetch(
                spec,
                raw_dir=data_dir / "raw",
                today=today,
                refresh=refresh,
                offline=offline,
            )
            path = download.path
            meta = download.metadata
            provenance = {
                "url": meta.url,
                "resolved_url": meta.resolved_url,
                "downloaded_at": meta.downloaded_at.isoformat(),
                "raw_sha256": meta.sha256,
                "from_cache": download.from_cache,
            }
        frame, warnings = _process(spec, path, provenance)
        provenance["warnings"] = warnings
        output = write_processed(
            frame,
            processed_dir=data_dir / "processed",
            source_id=spec.source_id,
            provenance=provenance,
        )
    except IngestionError as exc:
        return RunResult(source_id, ok=False, error=str(exc))
    except ValidationError as exc:
        error = DataValidationError(source_id, "-", f"registro inválido: {exc}")
        return RunResult(source_id, ok=False, error=str(error))
    return RunResult(source_id, ok=True, rows=frame.height, output=output, warnings=warnings)


def run_all(
    *,
    data_dir: Path,
    today: date,
    refresh: bool = False,
    offline: bool = False,
    fail_fast: bool = False,
) -> list[RunResult]:
    """Procesa todas las fuentes registradas, en orden; ``fail_fast`` corta en el primer error."""
    results: list[RunResult] = []
    for source_id in SOURCES:
        result = run_source(
            source_id, data_dir=data_dir, today=today, refresh=refresh, offline=offline
        )
        results.append(result)
        if fail_fast and not result.ok:
            break
    return results
