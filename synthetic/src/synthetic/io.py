"""Escritura de la corrida a parquet y ``manifest.json``."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl
from shared.disclaimer import DISCLAIMER

if TYPE_CHECKING:
    from synthetic.pipeline import SyntheticDataset
    from synthetic.validate import CalibrationReport

__all__ = ["DISCLAIMER", "write_parquet"]


def write_parquet(
    ds: SyntheticDataset, out_dir: Path, report: CalibrationReport | None = None
) -> Path:
    """Escribe ``<out_dir>/<run_id>/*.parquet`` (tablas y catálogos) y ``manifest.json``."""
    run_dir = out_dir / str(ds.run["id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    for name, frame in sorted(ds.tables.items()):
        path = run_dir / f"{name}.parquet"
        frame.write_parquet(path)
        files[name] = {"rows": frame.height, "columns": frame.columns}
    for name, frame in sorted(ds.catalogs.items()):
        path = run_dir / f"catalog_{name}.parquet"
        frame.write_parquet(path)
        files[f"catalog_{name}"] = {"rows": frame.height, "columns": frame.columns}
    manifest: dict[str, Any] = {
        "disclaimer": DISCLAIMER,
        "run": ds.run,
        "digest": ds.digest,
        "files": files,
        "versions": {
            "python": platform.python_version(),
            "polars": pl.__version__,
            "numpy": np.__version__,
        },
        "calibration": report.model_dump(mode="json") if report is not None else None,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return run_dir
