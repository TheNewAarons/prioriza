"""Fixtures de la API: corrida sintética chica generada en un directorio temporal.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Sin red ni datos reales.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from api.auth import Role, User, UserDirectory
from api.jobs import InlineExecutor
from api.main import create_app
from api.plans import MemoryPlanStore
from api.settings import ApiSettings
from fastapi.testclient import TestClient
from shared.db.enums import NoShowScenario
from synthetic.config import RunConfig
from synthetic.io import write_parquet
from synthetic.pipeline import generate
from synthetic.targets import load_assumptions, load_targets

# Con --import-mode=importlib el directorio de tests no está en sys.path.
sys.path.insert(0, str(Path(__file__).parent))

KEYS = {
    "clave-gestor": User("gestora.test", Role.GESTOR),
    "clave-gestor-2": User("gestor.dos", Role.GESTOR),
    "clave-revisor": User("revisor.test", Role.REVISOR),
    "clave-lectura": User("lectura.test", Role.LECTURA),
}


@pytest.fixture(autouse=True)
def _test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """El `TestClient` usa el host `testserver`, que no está en la lista blanca por defecto."""
    monkeypatch.setenv("PRIORIZA_API_TRUSTED_HOSTS", "testserver,localhost")


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Corrida sintética de 1.000 entradas con oferta para 4 semanas (semilla fija)."""
    cfg = RunConfig(size=1000, seed=7, scenario=NoShowScenario.BASELINE, horizon_weeks=4)
    ds = generate(cfg, load_targets(), load_assumptions())
    return write_parquet(ds, tmp_path_factory.mktemp("synthetic"))


@pytest.fixture
def make_client(run_dir: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Fábrica de clientes con almacén en memoria y ejecutor inmediato."""

    def factory() -> TestClient:
        settings = ApiSettings(
            run_dir=run_dir, results_dir=tmp_path / "results", models_dir=tmp_path / "models"
        )
        app = create_app(
            settings,
            store=MemoryPlanStore(),
            executor=InlineExecutor(),
            users=UserDirectory(dict(KEYS)),
        )
        return TestClient(app)

    return factory
