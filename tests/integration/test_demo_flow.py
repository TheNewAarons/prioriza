"""Integración del flujo de la demo (`scripts/demo.sh`) con una población pequeña.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Corre el script real con 1.000 entradas (sin red, sin `uv sync`, sin servir), luego levanta la
API en proceso con los artefactos generados y el panel Dash apuntando a esa API. Todo es
sintético; las claves de `users.json` se generan al vuelo en cada corrida.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from api.jobs import InlineExecutor
from api.main import create_app as create_api
from api.settings import ApiSettings
from dashboard.api_client import ApiClient
from dashboard.app import create_app as create_panel
from dashboard.config import DashboardSettings
from dashboard.session import Session
from dashboard.views import lista, resumen
from fastapi.testclient import TestClient
from shared.disclaimer import DISCLAIMER

from dashboard import runtime

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "demo.sh"
DEMO_ARGS = [
    "--size", "1000", "--sim-weeks", "2", "--sim-replicas", "1",
    "--no-sync", "--no-serve", "--no-open", "--fresh",
]  # fmt: skip
POLICIES = {"fifo", "priority", "optimized"}
SIM_POLICIES = {"fifo", "priority", "optimized", "optimized_overbooking"}


@dataclass(frozen=True)
class Demo:
    """Resultado de correr el script: carpeta, corrida, claves por rol y salida."""

    root: Path
    run_dir: Path
    keys: dict[str, str]
    stdout: str
    stderr: str
    returncode: int


def run_script(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    """Ejecuta `scripts/demo.sh` como subproceso (sin red; límite de 5 minutos)."""
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "NO_COLOR": "1"},
        check=False,
    )


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Demo:
    """Corre la demo completa una vez por módulo y devuelve sus artefactos."""
    root = tmp_path_factory.mktemp("demo")
    proc = run_script(*DEMO_ARGS, "--dir", str(root))
    runs = [p.parent for p in (root / "synthetic").glob("*/manifest.json")]
    users = json.loads((root / "users.json").read_text()) if (root / "users.json").exists() else {}
    keys = {entry["role"]: key for key, entry in users.items()}
    return Demo(
        root=root,
        run_dir=runs[0] if runs else root / "synthetic",
        keys=keys,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )


@pytest.fixture(scope="module")
def api(demo: Demo) -> Iterator[TestClient]:
    """API en proceso con los artefactos de la demo y ejecutor inmediato."""
    settings = ApiSettings(
        run_dir=demo.run_dir,
        models_dir=demo.root / "models",
        results_dir=demo.root / "results",
        users_file=demo.root / "users.json",
        trusted_hosts=["testserver", "api.test"],  # hosts de los clientes de prueba (P16)
    )
    with TestClient(create_api(settings, executor=InlineExecutor())) as client:
        yield client


def headers(demo: Demo, role: str) -> dict[str, str]:
    """Cabecera de autenticación del rol."""
    return {"X-API-Key": demo.keys[role]}


# ------------------------------------------------------------------ 1. el script


def test_script_exits_zero_with_numbered_steps(demo: Demo) -> None:
    """El script termina bien y muestra sus pasos numerados con tiempos."""
    assert demo.returncode == 0, demo.stdout + demo.stderr
    steps = [(int(n), int(t)) for n, t in re.findall(r"\[(\d+)/(\d+)\]", demo.stdout)]
    assert len(steps) >= 5
    assert [n for n, _ in steps] == list(range(1, len(steps) + 1))
    assert {t for _, t in steps} == {len(steps)}
    assert demo.stdout.count("listo en") == len(steps)
    assert re.search(r"Demostraci.n completada", demo.stdout)


def test_script_artifacts_exist(demo: Demo) -> None:
    """Corrida, modelo, métricas, programación y simulación quedan en disco."""
    manifest = json.loads((demo.run_dir / "manifest.json").read_text())
    assert manifest["run"]["size"] == 1000
    run_id = demo.run_dir.name
    assert (demo.root / "models" / run_id / "noshow_model.joblib").is_file()
    assert (demo.root / "results" / "noshow.json").is_file()
    # El nombre real lleva un sufijo (`_all_<hash>`); el contrato solo fija el prefijo.
    schedules = list((demo.root / "results").glob(f"schedule_{run_id}_4w*.json"))
    assert len(schedules) == 1
    report = json.loads(schedules[0].read_text())
    assert set(report["policies"]) == POLICIES
    assert report["disclaimer"] == DISCLAIMER
    sim = json.loads((demo.root / "results" / "simulation.json").read_text())
    assert set(sim["aggregate"]) == SIM_POLICIES
    assert len(sim["replicas"]) == 1
    assert set(sim["replicas"][0]["policies"]) == SIM_POLICIES
    assert sim["disclaimer"] == DISCLAIMER
    assert list((demo.root / "logs").glob("*.log"))


def test_users_file_permissions_and_roles(demo: Demo) -> None:
    """`users.json` es privado (600) y trae los tres roles con claves distintas."""
    path = demo.root / "users.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    users = json.loads(path.read_text())
    assert sorted(u["role"] for u in users.values()) == ["gestor", "lectura", "revisor"]
    assert len(set(users)) == 3
    assert all(len(key) >= 32 for key in users)


def test_keys_never_leak_to_output_or_logs(demo: Demo) -> None:
    """Con `--no-serve` el contrato no imprime claves; los logs tampoco las tienen."""
    assert demo.keys
    for key in demo.keys.values():
        assert key not in demo.stdout
        assert key not in demo.stderr
        for log in (demo.root / "logs").glob("*.log"):
            assert key not in log.read_text(errors="replace")


# ------------------------------------------------------------------ 2. API en proceso


def test_api_read_only_endpoints(demo: Demo, api: TestClient) -> None:
    """La clave de lectura consulta usuario, resumen y una página de la lista."""
    h = headers(demo, "lectura")
    me = api.get("/v1/me", headers=h)
    assert me.status_code == 200
    assert me.json()["role"] == "lectura"
    summary = api.get("/v1/waitlist/summary", headers=h)
    assert summary.status_code == 200
    assert summary.json()["total"] > 0
    page = api.get("/v1/waitlist", params={"limit": 5}, headers=h)
    assert page.status_code == 200
    assert len(page.json()["items"]) == 5
    for response in (summary, page):
        assert response.json()["disclaimer"] == DISCLAIMER


def test_me_response_carries_disclaimer(demo: Demo, api: TestClient) -> None:
    """Toda respuesta de la API debe traer el aviso obligatorio (hoy `/v1/me` no lo trae)."""
    me = api.get("/v1/me", headers=headers(demo, "lectura"))
    assert me.json()["disclaimer"] == DISCLAIMER


def test_plan_lifecycle_and_simulation(demo: Demo, api: TestClient) -> None:
    """Gestor programa, revisor aprueba, gestor marca vigente; la simulación trae equidad."""
    gestor, revisor = headers(demo, "gestor"), headers(demo, "revisor")
    plan_ids: dict[str, str] = {}
    for policy in ("fifo", "optimized"):
        body: dict[str, Any] = {"policy": policy, "horizon_weeks": 4, "time_limit_s": 30}
        if policy == "optimized":
            body["overbooking"] = True
        created = api.post("/v1/schedule-runs", json=body, headers=gestor)
        assert created.status_code == 202, created.text
        assert created.json()["disclaimer"] == DISCLAIMER
        job = api.get(f"/v1/schedule-runs/{created.json()['job_id']}", headers=gestor).json()
        assert job["status"] == "succeeded", job
        assert job["disclaimer"] == DISCLAIMER
        plan_ids[policy] = job["plan_id"]
    plan_id = plan_ids["optimized"]

    plan = api.get(f"/v1/plans/{plan_id}", headers=gestor).json()
    assert plan["review_status"] == "pending"  # todo plan requiere revisión humana

    reviewed = api.post(
        f"/v1/plans/{plan_id}/review",
        json={"decision": "approved", "note": "Revisión sintética de prueba"},
        headers=revisor,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["disclaimer"] == DISCLAIMER

    activated = api.post(f"/v1/plans/{plan_id}/activate", json={"note": None}, headers=gestor)
    assert activated.status_code == 200, activated.text

    current = api.get("/v1/plans/current", headers=headers(demo, "lectura"))
    assert current.status_code == 200
    assert current.json()["plan_id"] == plan_id
    assert current.json()["disclaimer"] == DISCLAIMER

    sim = api.get("/v1/simulation", headers=headers(demo, "lectura"))
    assert sim.status_code == 200
    assert sim.json()["equity"]
    assert sim.json()["disclaimer"] == DISCLAIMER


# ------------------------------------------------------------------ 3. panel


class _AsgiTransport(httpx.BaseTransport):
    """Transporte que delega cada petición del cliente del panel en el `TestClient`."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._client.request(
            request.method,
            request.url.raw_path.decode(),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            response.status_code,
            headers={"content-type": response.headers.get("content-type", "application/json")},
            content=response.content,
        )


def test_panel_layout_and_views_with_real_api(demo: Demo, api: TestClient) -> None:
    """El panel muestra el aviso y sus vistas puras se construyen con datos reales de la API."""
    client = ApiClient("http://api.test", transport=_AsgiTransport(api))
    app = create_panel(DashboardSettings(api_url="http://api.test"))
    runtime.set_client(client)
    try:
        layout = json.dumps(app.layout, default=lambda o: o.to_plotly_json(), ensure_ascii=False)
        assert DISCLAIMER in layout
        key = demo.keys["lectura"]
        session = Session(api_key=key, user="lectura.demo", role="lectura")

        data = resumen.fetch_resumen(client, session)
        assert data.summary["total"] > 0
        assert resumen.build_resumen(data) is not None

        params = lista.build_params(
            service=None, specialty=None, care=None, priority=None, ges=None,
            tier=None, order=None, page=0, page_size=5,
        )  # fmt: skip
        page = lista.fetch_lista(client, session, params)
        assert 0 < len(page.rows) <= 5
        assert page.pages >= 1
    finally:
        runtime.set_client(None)
        client.close()


# ------------------------------------------------------------------ 4. opciones inválidas


def test_size_below_minimum_fails_with_clear_message(tmp_path: Path) -> None:
    """`--size 500` sale con error y dice cuál es el mínimo."""
    proc = run_script("--size", "500", "--no-sync", "--dir", str(tmp_path / "x"))
    assert proc.returncode != 0
    assert "1000" in proc.stderr


def test_help_exits_zero() -> None:
    """`--help` muestra el uso y sale con 0."""
    proc = run_script("--help")
    assert proc.returncode == 0
    assert "Uso:" in proc.stdout
    assert "--size" in proc.stdout
