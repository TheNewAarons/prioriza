"""Escritura a parquet y manifest (sin red ni base de datos)."""

from __future__ import annotations

import json

import polars as pl
from synthetic.io import DISCLAIMER, write_parquet


def test_parquet_ida_y_vuelta_y_manifest(ds1k, tmp_path):
    """write_parquet escribe todas las tablas y catálogos sin pérdida, más manifest.json."""
    run_dir = write_parquet(ds1k, tmp_path)
    assert run_dir.name == ds1k.run["id"]
    for name, df in ds1k.tables.items():
        back = pl.read_parquet(run_dir / f"{name}.parquet")
        assert back.equals(df), name
    for name, df in ds1k.catalogs.items():
        assert pl.read_parquet(run_dir / f"catalog_{name}.parquet").equals(df), name
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["digest"] == ds1k.digest
    assert manifest["disclaimer"] == DISCLAIMER
    assert "validación institucional" in DISCLAIMER
