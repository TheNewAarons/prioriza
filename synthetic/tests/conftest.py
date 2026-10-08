"""Fixtures de sesión para los tests de synthetic.

Se genera cada población una sola vez por sesión (semillas fijas, sin red).
Todo es 100% sintético.
"""

from __future__ import annotations

import pytest

SEED = 42
N_CALIBRATION = 20_000
N_SMALL = 1_000


@pytest.fixture(scope="session")
def targets():
    """Objetivos de calibración versionados (JSON empaquetado)."""
    from synthetic.targets import load_targets

    return load_targets()


@pytest.fixture(scope="session")
def assumptions():
    """Supuestos versionados (JSON empaquetado)."""
    from synthetic.targets import load_assumptions

    return load_assumptions()


def _generate(size: int, seed: int, scenario: str = "baseline"):
    from shared.db.enums import NoShowScenario
    from synthetic.config import RunConfig
    from synthetic.pipeline import generate

    cfg = RunConfig(size=size, seed=seed, scenario=NoShowScenario(scenario))
    return cfg, generate(cfg)


@pytest.fixture(scope="session")
def ds20k():
    """Población baseline N=20.000, semilla 42."""
    return _generate(N_CALIBRATION, SEED)[1]


@pytest.fixture(scope="session")
def ds20k_neutral():
    """Población neutral N=20.000, semilla 42."""
    return _generate(N_CALIBRATION, SEED, "neutral")[1]


@pytest.fixture(scope="session")
def ds20k_ses():
    """Población ses_gradient N=20.000, semilla 42."""
    return _generate(N_CALIBRATION, SEED, "ses_gradient")[1]


@pytest.fixture(scope="session")
def ds1k():
    """Población baseline N=1.000, semilla 42."""
    return _generate(N_SMALL, SEED)[1]


@pytest.fixture(scope="session")
def make_dataset():
    """Fábrica (size, seed, scenario) -> SyntheticDataset."""

    def factory(size: int, seed: int, scenario: str = "baseline"):
        return _generate(size, seed, scenario)[1]

    return factory


@pytest.fixture(scope="session")
def m():
    """Módulo de métricas independientes (synthetic_metrics.py, en este directorio)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).with_name("synthetic_metrics.py")
    spec = importlib.util.spec_from_file_location("synthetic_metrics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
