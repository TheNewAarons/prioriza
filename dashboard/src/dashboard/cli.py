"""Línea de comandos del panel: `prioriza-dashboard [--with-api]`.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Con `--with-api`, si la API no responde en `api_url` y es local, lanza
`uvicorn --factory api.main:create_app` como subproceso (con los mismos `PRIORIZA_API_*` del
entorno) y lo detiene al salir. El panel sigue hablando con la API solo por HTTP.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx

from dashboard.config import DashboardSettings

log = logging.getLogger("dashboard.cli")

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
API_START_TIMEOUT_S = 120.0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(prog="prioriza-dashboard", description="Panel de Prioriza.")
    parser.add_argument("--with-api", action="store_true", help="lanza la API si no responde")
    parser.add_argument("--host", help="host del panel (PRIORIZA_DASHBOARD_HOST)")
    parser.add_argument("--port", type=int, help="puerto del panel (PRIORIZA_DASHBOARD_PORT)")
    parser.add_argument("--api-url", help="dirección de la API (PRIORIZA_DASHBOARD_API_URL)")
    parser.add_argument("--debug", action="store_true", help="modo de depuración de Dash")
    return parser.parse_args(argv)


def build_settings(args: argparse.Namespace) -> DashboardSettings:
    """Ajustes del entorno, con los argumentos encima."""
    settings = DashboardSettings()
    updates = {
        k: v
        for k, v in {
            "host": args.host,
            "port": args.port,
            "api_url": args.api_url,
            "debug": True if args.debug else None,
        }.items()
        if v is not None
    }
    return settings.model_copy(update=updates)


def api_is_up(api_url: str, timeout_s: float = 2.0) -> bool:
    """Si la API responde en `/healthz`."""
    try:
        return httpx.get(f"{api_url.rstrip('/')}/healthz", timeout=timeout_s).status_code == 200
    except httpx.HTTPError:
        return False


def is_local(api_url: str) -> bool:
    """Si la API está en esta máquina (solo en ese caso se lanza como subproceso)."""
    return (urlparse(api_url).hostname or "") in LOCAL_HOSTS


def api_command(api_url: str) -> list[str]:
    """Comando que lanza la API con la misma dirección que usa el panel."""
    parsed = urlparse(api_url)
    return [
        "uv",
        "run",
        "--package",
        "api",
        "uvicorn",
        "--factory",
        "api.main:create_app",
        "--host",
        parsed.hostname or "127.0.0.1",
        "--port",
        str(parsed.port or 8000),
    ]


def start_api(api_url: str) -> subprocess.Popen[bytes] | None:
    """Lanza la API si no responde; devuelve el proceso (o `None` si ya estaba arriba)."""
    if api_is_up(api_url):
        log.info("La API ya responde en %s", api_url)
        return None
    if not is_local(api_url):
        raise SystemExit(f"La API no responde en {api_url} y no es local: no se puede lanzar.")
    if shutil.which("uv") is None:
        raise SystemExit("No se encontró `uv`. Levanta la API con `make api`.")
    log.info("Lanzando la API en %s", api_url)
    proc = subprocess.Popen(api_command(api_url), env=os.environ.copy())
    atexit.register(stop_api, proc)
    deadline = time.monotonic() + API_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(
                f"La API terminó al arrancar (código {proc.returncode}). Revisa su registro."
            )
        if api_is_up(api_url):
            return proc
        time.sleep(0.5)
    stop_api(proc)
    raise SystemExit(
        f"La API no respondió en {API_START_TIMEOUT_S:.0f} s. Levántala con `make api`."
    )


def stop_api(proc: subprocess.Popen[bytes]) -> None:
    """Detiene la API lanzada por el panel."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada del script `prioriza-dashboard`."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    settings = build_settings(args)
    proc = start_api(settings.api_url) if args.with_api else None
    try:
        from dashboard.app import create_app

        create_app(settings).run(host=settings.host, port=settings.port, debug=settings.debug)
    finally:
        if proc is not None:
            stop_api(proc)
    return 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
