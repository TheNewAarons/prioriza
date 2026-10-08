"""Lectura de una corrida sintética desde parquet con una lista explícita de tablas permitidas.

Las features se construyen solo con ``FEATURE_TABLES``. Los atributos de equidad y la verdad
sintética se leen aparte, con funciones de nombre explícito, y solo para evaluar: nunca se pasan
a ``features.build_features``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

FEATURE_TABLES: Final[frozenset[str]] = frozenset(
    {"appointment", "waitlist_entry", "catalog_specialty"}
)
FAIRNESS_TABLES: Final[frozenset[str]] = frozenset({"patient"})
TRUTH_TABLES: Final[frozenset[str]] = frozenset({"appointment_truth", "patient_latent"})
FAIRNESS_COLUMNS: Final[tuple[str, ...]] = (
    "age_group",
    "insurance",
    "health_service_code",
    "commune_code",
)


@dataclass(frozen=True)
class RunData:
    """Tablas observables de una corrida y su versión de datos (desde ``manifest.json``)."""

    run_dir: Path
    data_version: dict[str, Any]
    appointment: pl.DataFrame
    waitlist_entry: pl.DataFrame
    catalog_specialty: pl.DataFrame


def _read_table(run_dir: Path, name: str, allowed: frozenset[str]) -> pl.DataFrame:
    if name not in allowed:
        raise PermissionError(f"tabla {name!r} fuera de la lista permitida {sorted(allowed)}")
    return pl.read_parquet(run_dir / f"{name}.parquet")


def read_manifest(run_dir: Path) -> dict[str, Any]:
    """Contenido de ``manifest.json`` de la corrida."""
    data: dict[str, Any] = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return data


def data_version(manifest: dict[str, Any]) -> dict[str, Any]:
    """Identificadores que fijan la versión de los datos de entrenamiento."""
    run = manifest["run"]
    keys = (
        "id",
        "seed",
        "size",
        "scenario",
        "as_of",
        "generator_version",
        "targets_sha256",
        "params_sha256",
        "dataset_sha256",
    )
    return {("run_id" if k == "id" else k): run[k] for k in keys}


def load_run(run_dir: Path) -> RunData:
    """Carga las tablas permitidas para construir features."""
    manifest = read_manifest(run_dir)
    return RunData(
        run_dir=run_dir,
        data_version=data_version(manifest),
        appointment=_read_table(run_dir, "appointment", FEATURE_TABLES),
        waitlist_entry=_read_table(run_dir, "waitlist_entry", FEATURE_TABLES),
        catalog_specialty=_read_table(run_dir, "catalog_specialty", FEATURE_TABLES),
    )


def load_fairness_attributes(run_dir: Path) -> pl.DataFrame:
    """Atributos del paciente para medir equidad (``patient_id`` + ``FAIRNESS_COLUMNS``)."""
    patient = _read_table(run_dir, "patient", FAIRNESS_TABLES)
    return patient.select(pl.col("id").alias("patient_id"), *FAIRNESS_COLUMNS)


def load_truth_for_evaluation(run_dir: Path) -> pl.DataFrame:
    """Probabilidad verdadera por cita: solo para la referencia del oráculo en la evaluación."""
    truth = _read_table(run_dir, "appointment_truth", TRUTH_TABLES)
    return truth.select(pl.col("appointment_id").alias("id"), "true_noshow_prob")


def find_run_dir(
    data_dir: Path,
    seed: int,
    size: int,
    scenario: str,
    expected: dict[str, str] | None = None,
) -> Path:
    """Única corrida en ``data_dir`` con esa semilla, tamaño y escenario.

    ``expected`` (por ejemplo, ``targets_sha256`` y ``params_sha256`` vigentes del generador)
    descarta corridas generadas con supuestos anteriores. Si no queda exactamente una, falla:
    nunca se elige por fecha de archivo.
    """
    matches: list[tuple[Path, dict[str, Any]]] = []
    for manifest_path in sorted(data_dir.glob("*/manifest.json")):
        run = json.loads(manifest_path.read_text(encoding="utf-8"))["run"]
        if (run["seed"], run["size"], run["scenario"]) == (seed, size, scenario):
            matches.append((manifest_path.parent, run))
    hint = "genérala con `make synth` o `prioriza-synth generate --no-load`"
    if not matches:
        raise FileNotFoundError(
            f"no hay corrida sintética con seed={seed}, size={size}, scenario={scenario} en "
            f"{data_dir}; {hint}"
        )
    current = [
        (path, run)
        for path, run in matches
        if all(run.get(k) == v for k, v in (expected or {}).items())
    ]
    if not current:
        stale = ", ".join(p.name for p, _ in matches)
        raise FileNotFoundError(
            f"las corridas con seed={seed}, size={size}, scenario={scenario} ({stale}) se "
            f"generaron con otros supuestos del generador; {hint}"
        )
    if len(current) > 1:
        names = ", ".join(p.name for p, _ in current)
        raise FileExistsError(f"varias corridas coinciden ({names}); fija una con --run-dir")
    return current[0][0]
