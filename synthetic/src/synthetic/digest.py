"""Huella (digest) determinista de un conjunto de tablas."""

import hashlib
from collections.abc import Mapping

import polars as pl


def dataset_digest(tables: Mapping[str, pl.DataFrame]) -> str:
    """sha256 de (nombre de tabla + CSV ordenado por la primera columna) por tabla.

    El pipeline incluye también los catálogos (con prefijo ``catalog_``).

    Los flotantes se serializan con 6 decimales y no se incluyen marcas de creación.
    """
    h = hashlib.sha256()
    for name in sorted(tables):
        frame = tables[name]
        key = frame.columns[0]
        csv = frame.sort(key).write_csv(float_precision=6)
        h.update(name.encode("utf-8"))
        h.update(b"\n")
        h.update(csv.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()
