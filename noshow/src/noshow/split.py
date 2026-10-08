"""Split temporal: entrenar con citas pasadas, calibrar con las siguientes y evaluar las últimas.

No hay mezcla aleatoria: cada conjunto ocupa un intervalo de fechas disjunto y posterior al
anterior. Los límites se calculan desde la última cita observada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

from noshow.features import TIMESTAMP


@dataclass(frozen=True)
class TemporalSplit:
    """Conjuntos de entrenamiento, calibración y prueba, con sus límites (UTC)."""

    train: pl.DataFrame
    calibration: pl.DataFrame
    test: pl.DataFrame
    calibration_start: datetime
    test_start: datetime

    def summary(self) -> dict[str, object]:
        """Tamaños, tasas y rangos de fechas de cada conjunto."""
        out: dict[str, object] = {
            "calibration_start": self.calibration_start.isoformat(),
            "test_start": self.test_start.isoformat(),
        }
        for name, frame in (
            ("train", self.train),
            ("calibration", self.calibration),
            ("test", self.test),
        ):
            out[name] = {
                "n": frame.height,
                "no_show_rate": round(float(frame["no_show"].mean() or 0.0), 6),
                "first": _iso(frame[TIMESTAMP].min()),
                "last": _iso(frame[TIMESTAMP].max()),
            }
        return out


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def temporal_split(frame: pl.DataFrame, test_days: int, calibration_days: int) -> TemporalSplit:
    """Divide por ``scheduled_start``: [.., cal) entrena, [cal, test) calibra, [test, ..] evalúa."""
    if test_days < 1 or calibration_days < 1:
        raise ValueError("test_days y calibration_days deben ser >= 1")
    last = frame[TIMESTAMP].max()
    if not isinstance(last, datetime):
        raise ValueError("no hay citas para dividir")
    test_start = last - timedelta(days=test_days)
    calibration_start = test_start - timedelta(days=calibration_days)
    ts = pl.col(TIMESTAMP)
    ordered = frame.sort(TIMESTAMP, "id")
    split = TemporalSplit(
        train=ordered.filter(ts < calibration_start),
        calibration=ordered.filter((ts >= calibration_start) & (ts < test_start)),
        test=ordered.filter(ts >= test_start),
        calibration_start=calibration_start,
        test_start=test_start,
    )
    for name, part in (("train", split.train), ("calibration", split.calibration)):
        if part.height == 0:
            raise ValueError(f"el conjunto {name} quedó vacío; reduce test_days o calibration_days")
    return split
