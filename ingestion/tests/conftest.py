"""Configuración común de los tests de ingestion.

Ningún test puede usar la red: se bloquea el transporte real de httpx. Los tests del
descargador usan ``httpx.MockTransport`` (que no pasa por ``HTTPTransport``).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from ingestion.parsers.glosa06 import TableResult, parse_glosa06
from ingestion.pdf_words import PageWords, load_words_json
from ingestion.sources import get_source

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class NetworkBlockedError(RuntimeError):
    """Se intentó usar la red real dentro de un test."""


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bloquea la red real: cualquier request por ``httpx.HTTPTransport`` falla."""

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise NetworkBlockedError(f"red bloqueada en tests: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directorio con las fixtures grabadas."""
    return FIXTURES_DIR


GLOSA_QUARTERS = ("glosa06_2025q3", "glosa06_2025q4", "glosa06_2026q1")


def load_glosa_pages(fixtures: Path, source_id: str) -> list[PageWords]:
    """Carga los volcados de palabras de una Glosa, ordenados por página."""
    folder = fixtures / "glosa06" / source_id
    return [load_words_json(path) for path in sorted(folder.glob("p*.words.json"))]


@pytest.fixture(scope="session")
def glosa_pages(fixtures_dir: Path) -> dict[str, list[PageWords]]:
    """Páginas (volcados de palabras) de los tres trimestres, por ``source_id``."""
    return {sid: load_glosa_pages(fixtures_dir, sid) for sid in GLOSA_QUARTERS}


@pytest.fixture(scope="session")
def glosa_results(
    glosa_pages: dict[str, list[PageWords]],
) -> dict[str, dict[str, TableResult]]:
    """Tablas parseadas por trimestre y clave. NO mutar: usar copias."""
    return {
        sid: {r.key: r for r in parse_glosa06(pages, get_source(sid))}
        for sid, pages in glosa_pages.items()
    }
