"""Escritura de resultados procesados: parquet más sidecar de procedencia."""

import json
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import polars as pl


def _version() -> str:
    try:
        return version("ingestion")
    except PackageNotFoundError:  # pragma: no cover - paquete sin instalar
        return "desconocida"


def write_processed(
    df: pl.DataFrame,
    *,
    processed_dir: Path,
    source_id: str,
    provenance: Mapping[str, object],
) -> Path:
    """Escribe ``<source_id>.parquet`` y ``<source_id>.metadata.json`` en ``processed_dir``.

    El sidecar incluye la procedencia recibida (sha256 del original, URL, tablas, páginas,
    advertencias), las filas y columnas escritas y la versión de ``ingestion``. Devuelve la
    ruta del parquet.
    """
    processed_dir.mkdir(parents=True, exist_ok=True)
    parquet = processed_dir / f"{source_id}.parquet"
    sidecar = processed_dir / f"{source_id}.metadata.json"
    tmp = parquet.with_name(parquet.name + ".part")
    df.write_parquet(tmp, compression="zstd")
    tmp.replace(parquet)
    metadata = {
        "source_id": source_id,
        **provenance,
        "rows": df.height,
        "columns": df.columns,
        "ingestion_version": _version(),
    }
    sidecar.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return parquet
