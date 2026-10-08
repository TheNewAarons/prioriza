"""Configuración de una corrida del generador."""

from dataclasses import dataclass
from datetime import date

from shared.db.enums import NoShowScenario

MIN_SIZE = 1_000


@dataclass(frozen=True)
class RunConfig:
    """Parámetros de una corrida: tamaño, semilla, escenario, horizonte y fecha de referencia."""

    size: int
    seed: int
    scenario: NoShowScenario = NoShowScenario.BASELINE
    horizon_weeks: int = 26
    as_of: date | None = None

    def __post_init__(self) -> None:
        if self.size < MIN_SIZE:
            raise ValueError(f"size debe ser >= {MIN_SIZE}")
        if self.horizon_weeks < 1:
            raise ValueError("horizon_weeks debe ser >= 1")
