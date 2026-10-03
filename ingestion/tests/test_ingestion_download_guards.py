"""Regresiones F5 (M3): contenido que no corresponde al tipo de la fuente no se guarda,
y los errores inesperados del parser no abortan la ejecución (sin red).
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest
from ingestion.download import fetch
from ingestion.errors import DownloadError
from ingestion.pipeline import RunResult
from ingestion.sources import SourceSpec, get_source

from ingestion import pipeline

TODAY = date(2026, 10, 3)
HTML_PAGE = (
    b"<!DOCTYPE html><html><head><title>Acceso denegado</title></head><body>WAF</body></html>"
)
PDF_BYTES = b"%PDF-1.4 contenido de prueba sintetico\n"
XLSX_BYTES = b"PK\x03\x04 contenido de prueba sintetico"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _client(body: bytes, content_type: str) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True), seen


def _spec(kind_source: str, filename: str, *, sha: str | None = None) -> SourceSpec:
    """Fuente de prueba sin sha256 esperado (como los catálogos que se refrescan)."""
    return dataclasses.replace(
        get_source(kind_source),
        source_id="fuente_guardia",
        url="https://example.test/archivo",
        filename=filename,
        expected_sha256=sha,
        max_cache_age_days=None,
    )


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def _fetch(spec: SourceSpec, tmp_path: Path, client: httpx.Client) -> None:
    fetch(spec, raw_dir=tmp_path, today=TODAY, client=client, sleep=lambda _s: None)


# --- descarga: magic bytes ----------------------------------------------------------------


@pytest.mark.parametrize("content_type", ["text/html; charset=utf-8", "application/pdf"])
def test_html_for_a_pdf_source_is_rejected_and_nothing_is_kept(
    tmp_path: Path, content_type: str
) -> None:
    """Un WAF puede devolver HTML con 200 (incluso con content-type engañoso)."""
    spec = _spec("glosa06_2026q1", "prueba.pdf")
    client, seen = _client(HTML_PAGE, content_type)
    with pytest.raises(DownloadError) as excinfo:
        _fetch(spec, tmp_path, client)
    assert seen, "debe haberse intentado la descarga"
    assert "fuente_guardia" in str(excinfo.value)
    assert _files(tmp_path) == []  # ni .part ni archivo final ni metadata


def test_html_for_an_xlsx_source_is_rejected(tmp_path: Path) -> None:
    spec = _spec("sis_ges_cases_2026q1", "prueba.xlsx")
    client, _ = _client(HTML_PAGE, "text/html")
    with pytest.raises(DownloadError):
        _fetch(spec, tmp_path, client)
    assert _files(tmp_path) == []


def test_pdf_bytes_for_an_xlsx_source_are_rejected(tmp_path: Path) -> None:
    spec = _spec("sis_ges_cases_2026q1", "prueba.xlsx")
    client, _ = _client(PDF_BYTES, "application/pdf")
    with pytest.raises(DownloadError):
        _fetch(spec, tmp_path, client)
    assert _files(tmp_path) == []


def test_html_for_a_csv_source_is_rejected(tmp_path: Path, fixtures_dir: Path) -> None:
    """Fuente CKAN (CSV): el paso 1 devuelve JSON válido y el paso 2 una página HTML."""
    ckan_json = (fixtures_dir / "minsal_establishments" / "ckan_resource_show.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/3/action/resource_show":
            return httpx.Response(200, content=ckan_json)
        return httpx.Response(200, content=HTML_PAGE, headers={"content-type": "text/html"})

    spec = get_source("minsal_establishments")
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with pytest.raises(DownloadError):
        _fetch(spec, tmp_path, client)
    assert _files(tmp_path) == []


@pytest.mark.parametrize("html", [b"  \n<html><body>x</body></html>", b"<!doctype html><p>x"])
def test_html_with_leading_whitespace_or_lowercase_doctype_is_also_rejected(
    tmp_path: Path, html: bytes
) -> None:
    spec = _spec("glosa06_2026q1", "prueba.pdf")
    client, _ = _client(html, "application/pdf")
    with pytest.raises(DownloadError):
        _fetch(spec, tmp_path, client)
    assert _files(tmp_path) == []


@pytest.mark.parametrize(
    ("source", "filename", "body", "content_type"),
    [
        ("glosa06_2026q1", "ok.pdf", PDF_BYTES, "application/pdf"),
        ("sis_ges_cases_2026q1", "ok.xlsx", XLSX_BYTES, "application/octet-stream"),
    ],
    ids=["pdf", "xlsx"],
)
def test_valid_magic_bytes_are_still_accepted(
    tmp_path: Path, source: str, filename: str, body: bytes, content_type: str
) -> None:
    """Control: el chequeo no debe rechazar archivos legítimos."""
    spec = _spec(source, filename)
    client, _ = _client(body, content_type)
    _fetch(spec, tmp_path, client)
    (final,) = [p for p in _files(tmp_path) if p.name == filename]
    assert final.read_bytes() == body


def test_a_rejected_download_does_not_poison_the_next_attempt(tmp_path: Path) -> None:
    """Tras un HTML rechazado, un reintento con el PDF real funciona (no quedó caché mala)."""
    spec = _spec("glosa06_2026q1", "prueba.pdf")
    bad, _ = _client(HTML_PAGE, "text/html")
    with pytest.raises(DownloadError):
        _fetch(spec, tmp_path, bad)
    good, seen = _client(PDF_BYTES, "application/pdf")
    _fetch(spec, tmp_path, good)
    assert len(seen) == 1, "el HTML rechazado no puede servirse desde la caché"
    (final,) = [p for p in _files(tmp_path) if p.name == "prueba.pdf"]
    assert final.read_bytes() == PDF_BYTES


# --- pipeline: los errores del parser quedan en RunResult ---------------------------------


def _raiser(exc: Exception) -> Callable[..., object]:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise exc

    return fail


@pytest.mark.parametrize(
    "exc",
    [ValueError("número inválido '1.23.4'"), RuntimeError("fallo inesperado de pdfplumber")],
    ids=["value_error", "runtime_error"],
)
def test_parser_exceptions_become_a_failed_run_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    pdf = tmp_path / "entrada.pdf"
    pdf.write_bytes(PDF_BYTES)
    monkeypatch.setattr(pipeline, "parse_glosa06_pdf", _raiser(exc))
    result = pipeline.run_source(
        "glosa06_2026q1", data_dir=tmp_path / "data", today=TODAY, input_path=pdf
    )
    assert isinstance(result, RunResult)
    assert result.ok is False
    assert result.rows == 0 and result.output is None
    assert result.error and "glosa06_2026q1" in result.error
    assert "Traceback" not in result.error
    assert not (tmp_path / "data" / "processed").exists() or not list(
        (tmp_path / "data" / "processed").glob("*.parquet")
    )


def test_a_file_that_is_not_a_pdf_gives_a_failed_run_result(tmp_path: Path) -> None:
    """HTML guardado como PDF (entrada local): pdfplumber falla y no debe propagarse."""
    fake = tmp_path / "entrada.pdf"
    fake.write_bytes(HTML_PAGE)
    result = pipeline.run_source(
        "glosa06_2026q1", data_dir=tmp_path / "data", today=TODAY, input_path=fake
    )
    assert result.ok is False
    assert result.error
