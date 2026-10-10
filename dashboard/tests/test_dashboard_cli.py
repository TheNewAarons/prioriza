"""Línea de comandos del panel: argumentos, arranque de la API local y cierre (sin red).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Ningún test lanza procesos reales ni abre sockets: `httpx.get`, `subprocess.Popen`, `shutil.which`
y el reloj se reemplazan por dobles.
"""

from __future__ import annotations

import subprocess
from typing import Any

import httpx
import pytest
from dashboard.config import DashboardSettings

from dashboard import cli


class FakeProc:
    """Proceso falso con el estado mínimo que usa `cli`."""

    def __init__(self, *, exits_with: int | None = None, hangs: bool = False) -> None:
        self.returncode = exits_with
        self.hangs = hangs
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.hangs:
            self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.hangs and not self.killed:
            raise subprocess.TimeoutExpired("api", timeout or 0)
        return self.returncode or 0


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HOST", "PORT", "API_URL", "DEBUG"):
        monkeypatch.delenv(f"PRIORIZA_DASHBOARD_{name}", raising=False)


# ------------------------------------------------------------------ argumentos y ajustes


def test_parse_args_defaults_and_flags() -> None:
    args = cli.parse_args([])
    assert not args.with_api and not args.debug
    assert args.host is None and args.port is None and args.api_url is None
    args = cli.parse_args(
        [
            "--with-api",
            "--host",
            "127.0.0.1",
            "--port",
            "9000",
            "--api-url",
            "http://x:1",
            "--debug",
        ]
    )
    assert args.with_api and args.debug and args.port == 9000 and args.api_url == "http://x:1"


def test_build_settings_cli_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIORIZA_DASHBOARD_PORT", "8123")
    monkeypatch.setenv("PRIORIZA_DASHBOARD_API_URL", "http://env:1")
    base = cli.build_settings(cli.parse_args([]))
    assert base.port == 8123 and base.api_url == "http://env:1" and base.debug is False
    over = cli.build_settings(cli.parse_args(["--port", "9001", "--debug"]))
    assert over.port == 9001 and over.api_url == "http://env:1" and over.debug is True


def test_api_command_uses_the_url_host_and_port() -> None:
    cmd = cli.api_command("http://127.0.0.1:9100")
    assert cmd[:3] == ["uv", "run", "--package"]
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--port") + 1] == "9100"
    default = cli.api_command("http://localhost")
    assert default[default.index("--port") + 1] == "8000"


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:8000", True),
        ("http://localhost:8000", True),
        ("http://[::1]:8000", True),
        ("http://api.interna.example:8000", False),
        ("http://10.0.0.5:8000", False),
    ],
)
def test_is_local(url: str, local: bool) -> None:
    assert cli.is_local(url) is local


# ------------------------------------------------------------------ api_is_up


def test_api_is_up_reads_healthz(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:
        seen.append(url)
        return httpx.Response(200)

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    assert cli.api_is_up("http://127.0.0.1:8000/") is True
    assert seen == ["http://127.0.0.1:8000/healthz"]
    monkeypatch.setattr(cli.httpx, "get", lambda url, timeout: httpx.Response(503))
    assert cli.api_is_up("http://127.0.0.1:8000") is False


def test_api_is_up_false_when_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("sin conexión")

    monkeypatch.setattr(cli.httpx, "get", boom)
    assert cli.api_is_up("http://127.0.0.1:8000") is False


# ------------------------------------------------------------------ start_api / stop_api


def test_start_api_returns_none_when_already_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "api_is_up", lambda url: True)
    popen_calls: list[Any] = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))
    assert cli.start_api("http://127.0.0.1:8000") is None
    assert popen_calls == []


def test_start_api_refuses_remote_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "api_is_up", lambda url: False)
    with pytest.raises(SystemExit, match="no es local"):
        cli.start_api("http://api.interna.example:8000")


def test_start_api_requires_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "api_is_up", lambda url: False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="make api"):
        cli.start_api("http://127.0.0.1:8000")


class Launch:
    """Lo que `start_api` pidió al sistema: comandos lanzados y funciones de cierre registradas."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.registered: list[tuple[Any, tuple[Any, ...]]] = []


def patch_launch(monkeypatch: pytest.MonkeyPatch, proc: FakeProc, up_after: int | None) -> Launch:
    """Lanza `proc` en vez de uvicorn; `api_is_up` responde True desde la consulta `up_after`."""
    launch = Launch()
    state = {"checks": 0}

    def is_up(url: str) -> bool:
        state["checks"] += 1
        return up_after is not None and state["checks"] > up_after

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda cmd, env=None: launch.commands.append(cmd) or proc
    )
    monkeypatch.setattr(cli, "api_is_up", is_up)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.atexit, "register", lambda fn, *a: launch.registered.append((fn, a)))
    return launch


def test_start_api_launches_and_waits_until_it_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = FakeProc()
    launched = patch_launch(monkeypatch, proc, up_after=3)
    assert cli.start_api("http://127.0.0.1:8000") is proc
    command = launched.commands[0]
    assert command[0] == "uv" and "api.main:create_app" in command
    assert launched.registered == [(cli.stop_api, (proc,))]


def test_start_api_reports_a_process_that_dies(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = FakeProc(exits_with=2)
    patch_launch(monkeypatch, proc, up_after=None)
    with pytest.raises(SystemExit, match="código 2"):
        cli.start_api("http://127.0.0.1:8000")


def test_start_api_times_out_and_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = FakeProc()
    patch_launch(monkeypatch, proc, up_after=None)
    clock = iter([0.0, 1.0, cli.API_START_TIMEOUT_S + 1.0])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    with pytest.raises(SystemExit, match="no respondió"):
        cli.start_api("http://127.0.0.1:8000")
    assert proc.terminated


def test_stop_api_cases() -> None:
    done = FakeProc(exits_with=0)
    cli.stop_api(done)  # type: ignore[arg-type]
    assert not done.terminated
    running = FakeProc()
    cli.stop_api(running)  # type: ignore[arg-type]
    assert running.terminated and not running.killed
    stuck = FakeProc(hangs=True)
    cli.stop_api(stuck)  # type: ignore[arg-type]
    assert stuck.terminated and stuck.killed


# ------------------------------------------------------------------ main


class FakeApp:
    def __init__(self) -> None:
        self.run_args: dict[str, Any] | None = None

    def run(self, **kwargs: Any) -> None:
        self.run_args = kwargs


def patch_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeApp, list[DashboardSettings]]:
    app = FakeApp()
    created: list[DashboardSettings] = []

    def create_app(settings: DashboardSettings) -> FakeApp:
        created.append(settings)
        return app

    monkeypatch.setattr("dashboard.app.create_app", create_app)
    return app, created


def test_main_runs_the_app_with_the_given_address(monkeypatch: pytest.MonkeyPatch) -> None:
    app, created = patch_app(monkeypatch)
    assert cli.main(["--host", "127.0.0.1", "--port", "9050"]) == 0
    assert app.run_args == {"host": "127.0.0.1", "port": 9050, "debug": False}
    assert created[0].port == 9050


def test_main_refuses_debug_on_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = patch_app(monkeypatch)
    for host in ("0.0.0.0", "panel.example"):
        with pytest.raises(SystemExit, match="debug"):
            cli.main(["--debug", "--host", host])
    assert app.run_args is None
    assert cli.main(["--debug", "--host", "localhost"]) == 0
    assert app.run_args is not None and app.run_args["debug"] is True


def test_main_with_api_stops_it_even_if_the_app_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = FakeProc()
    monkeypatch.setattr(cli, "start_api", lambda url: proc)

    class Boom(FakeApp):
        def run(self, **kwargs: Any) -> None:
            raise RuntimeError("falló el servidor")

    monkeypatch.setattr("dashboard.app.create_app", lambda settings: Boom())
    with pytest.raises(RuntimeError, match="falló"):
        cli.main(["--with-api"])
    assert proc.terminated


def test_main_with_api_already_running_has_nothing_to_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = patch_app(monkeypatch)
    monkeypatch.setattr(cli, "start_api", lambda url: None)
    assert cli.main(["--with-api"]) == 0
    assert app.run_args is not None
