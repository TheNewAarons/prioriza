"""Fixtures compartidas de los tests de noshow (100 % sintéticas, sin red ni base de datos)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Con --import-mode=importlib el directorio de tests no está en sys.path.
sys.path.insert(0, str(Path(__file__).parent))

from noshow.train import TrainConfig
from noshow_test_support import make_run

SMALL_CONFIG = TrainConfig(
    seed=7, test_days=120, calibration_days=120, n_boot=50, fairness_min_n=20
)


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Corrida de juguete compartida por la sesión (solo lectura)."""
    return make_run(tmp_path_factory.mktemp("synthetic"))


@pytest.fixture()
def small_config() -> TrainConfig:
    """Configuración rápida para datos chicos."""
    return SMALL_CONFIG
