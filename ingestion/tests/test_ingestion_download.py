"""Tests del descargador con ``httpx.MockTransport`` (sin red, con ``sleep`` inyectado)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date
from pathlib import Path

import httpx
import pytest
from ingestion.download import (
    USER_AGENT,
    DownloadResult,
    RawMetadata,
    fetch,
    resolve_url,
    sha256_file,
)
from ingestion.errors import DownloadError
from ingestion.sources import SourceSpec, get_source

PAYLOAD = b"%PDF-1.4 contenido de prueba sintetico\n"
URL = "https://example.test/files/prueba.pdf"
TODAY = date(2026, 10, 3)

Handler = Callable[[httpx.Request], httpx.Response]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def spec() -> SourceSpec:
    """Fuente de prueba basada en una Glosa, con URL y sha256 propios."""
    return dataclasses.replace(
        get_source("glosa06_2026q1"),
        source_id="fuente_prueba",
        url=URL,
        filename="prueba.pdf",
        expected_sha256=_sha(PAYLOAD),
        max_cache_age_days=None,
    )


class Recorder:
    """Handler de MockTransport que registra requests y responde con una secuencia."""

    def __init__(self, responses: list[httpx.Response | Exception] | Handler) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = responses

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if callable(self._responses):
            return self._responses(request)
        item = self._responses[min(len(self.requests), len(self._responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


def ok(content: bytes = PAYLOAD, content_type: str = "application/pdf") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": content_type})


def status(code: int) -> httpx.Response:
    return httpx.Response(code, content=b"error")


# --- descarga exitosa ---------------------------------------------------------------------


def test_success_writes_file_and_metadata(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([ok()])
    sleeps: list[float] = []
    result = fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=sleeps.append)

    assert isinstance(result, DownloadResult)
    assert result.from_cache is False
    assert result.path == tmp_path / "fuente_prueba" / "2026-10-03" / "prueba.pdf"
    assert result.path.read_bytes() == PAYLOAD
    assert sleeps == []
    assert len(rec.requests) == 1
    assert not list(result.path.parent.glob("*.part"))

    meta_path = result.path.parent / "metadata.json"
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    assert raw["sha256"] == _sha(PAYLOAD)
    assert raw["url"] == URL
    assert raw["resolved_url"] == URL
    assert raw["size_bytes"] == len(PAYLOAD)
    assert raw["http_status"] == 200
    assert raw["content_type"] == "application/pdf"
    assert raw["filename"] == "prueba.pdf"
    assert raw["source_id"] == "fuente_prueba"
    metadata = RawMetadata.model_validate(raw)
    assert metadata == result.metadata
    assert metadata.downloaded_at.tzinfo is not None
    assert metadata.downloaded_at.utcoffset() == UTC.utcoffset(None)


def test_request_sends_browser_like_user_agent(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([ok()])
    fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=lambda _s: None)
    agent = rec.requests[0].headers["user-agent"]
    assert agent == USER_AGENT
    assert agent.startswith("Mozilla/5.0 (compatible; Prioriza/0.1;")


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(PAYLOAD * 1000)
    assert sha256_file(path) == _sha(PAYLOAD * 1000)


# --- reintentos -------------------------------------------------------------------------


def test_503_503_200_waits_1_then_2_seconds(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([status(503), status(503), ok()])
    sleeps: list[float] = []
    result = fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=sleeps.append)
    assert len(rec.requests) == 3
    assert sleeps == [1, 2]
    assert result.path.read_bytes() == PAYLOAD


def test_backoff_base_scales_the_waits(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([status(500), status(502), status(504), ok()])
    sleeps: list[float] = []
    fetch(
        spec,
        raw_dir=tmp_path,
        today=TODAY,
        client=rec.client(),
        sleep=sleeps.append,
        backoff_base=0.5,
    )
    assert sleeps == [0.5, 1.0, 2.0]


def test_exhausted_retries_raise_download_error(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([status(503)])
    sleeps: list[float] = []
    with pytest.raises(DownloadError) as excinfo:
        fetch(
            spec,
            raw_dir=tmp_path,
            today=TODAY,
            client=rec.client(),
            sleep=sleeps.append,
            max_attempts=4,
        )
    assert len(rec.requests) == 4
    assert sleeps == [1, 2, 4]
    assert "fuente_prueba" in str(excinfo.value)
    assert not list((tmp_path / "fuente_prueba").rglob("prueba.pdf*"))


def test_max_attempts_is_respected(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([status(500)])
    with pytest.raises(DownloadError):
        fetch(
            spec,
            raw_dir=tmp_path,
            today=TODAY,
            client=rec.client(),
            sleep=lambda _s: None,
            max_attempts=2,
        )
    assert len(rec.requests) == 2


def test_429_is_retried(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([status(429), ok()])
    sleeps: list[float] = []
    fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=sleeps.append)
    assert len(rec.requests) == 2
    assert sleeps == [1]


def test_transport_errors_are_retried(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([httpx.ConnectError("sin conexion"), httpx.ReadTimeout("lento"), ok()])
    sleeps: list[float] = []
    result = fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=sleeps.append)
    assert len(rec.requests) == 3
    assert sleeps == [1, 2]
    assert result.path.read_bytes() == PAYLOAD


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410])
def test_4xx_fails_immediately_without_retry(spec: SourceSpec, tmp_path: Path, code: int) -> None:
    rec = Recorder([status(code)])
    sleeps: list[float] = []
    with pytest.raises(DownloadError) as excinfo:
        fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=sleeps.append)
    assert len(rec.requests) == 1
    assert sleeps == []
    assert str(code) in str(excinfo.value)


# --- verificación de sha256 -------------------------------------------------------------


def test_sha_mismatch_removes_everything_and_raises(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([ok(content=b"otro contenido")])
    with pytest.raises(DownloadError) as excinfo:
        fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=lambda _s: None)
    assert "sha256" in str(excinfo.value)
    leftovers = [p for p in (tmp_path / "fuente_prueba").rglob("*") if p.is_file()]
    assert leftovers == []  # ni .part ni archivo ni metadata


def test_no_expected_sha_accepts_any_content(spec: SourceSpec, tmp_path: Path) -> None:
    free = dataclasses.replace(spec, expected_sha256=None)
    other = b"%PDF-1.7 otro contenido sintetico\n"
    rec = Recorder([ok(content=other)])
    result = fetch(free, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=lambda _s: None)
    assert result.metadata.sha256 == _sha(other)


# --- caché ------------------------------------------------------------------------------


def test_cache_hit_makes_no_requests(spec: SourceSpec, tmp_path: Path) -> None:
    first = Recorder([ok()])
    fetch(spec, raw_dir=tmp_path, today=TODAY, client=first.client(), sleep=lambda _s: None)

    second = Recorder([status(500)])
    result = fetch(
        spec,
        raw_dir=tmp_path,
        today=date(2026, 11, 20),
        client=second.client(),
        sleep=lambda _s: None,
    )
    assert second.requests == []
    assert result.from_cache is True
    assert result.path.read_bytes() == PAYLOAD
    assert result.metadata.sha256 == _sha(PAYLOAD)


def test_refresh_forces_a_new_download(spec: SourceSpec, tmp_path: Path) -> None:
    fetch(
        spec, raw_dir=tmp_path, today=TODAY, client=Recorder([ok()]).client(), sleep=lambda _s: None
    )
    rec = Recorder([ok()])
    result = fetch(
        spec,
        raw_dir=tmp_path,
        today=date(2026, 10, 4),
        refresh=True,
        client=rec.client(),
        sleep=lambda _s: None,
    )
    assert len(rec.requests) == 1
    assert result.from_cache is False
    assert result.path.parent.name == "2026-10-04"


def test_cache_expires_after_max_cache_age_days(spec: SourceSpec, tmp_path: Path) -> None:
    aging = dataclasses.replace(spec, max_cache_age_days=7)
    fetch(
        aging,
        raw_dir=tmp_path,
        today=TODAY,
        client=Recorder([ok()]).client(),
        sleep=lambda _s: None,
    )

    fresh = Recorder([ok()])
    still_valid = fetch(
        aging,
        raw_dir=tmp_path,
        today=date(2026, 10, 10),  # 7 días: aún vigente
        client=fresh.client(),
        sleep=lambda _s: None,
    )
    assert still_valid.from_cache is True
    assert fresh.requests == []

    expired = Recorder([ok()])
    result = fetch(
        aging,
        raw_dir=tmp_path,
        today=date(2026, 10, 11),  # 8 días: vencida
        client=expired.client(),
        sleep=lambda _s: None,
    )
    assert len(expired.requests) == 1
    assert result.from_cache is False


def test_no_max_age_means_the_cache_never_expires(spec: SourceSpec, tmp_path: Path) -> None:
    fetch(
        spec, raw_dir=tmp_path, today=TODAY, client=Recorder([ok()]).client(), sleep=lambda _s: None
    )
    rec = Recorder([ok()])
    result = fetch(
        spec,
        raw_dir=tmp_path,
        today=date(2030, 1, 1),
        client=rec.client(),
        sleep=lambda _s: None,
    )
    assert result.from_cache is True
    assert rec.requests == []


def test_corrupted_cache_is_not_reused(spec: SourceSpec, tmp_path: Path) -> None:
    first = fetch(
        spec, raw_dir=tmp_path, today=TODAY, client=Recorder([ok()]).client(), sleep=lambda _s: None
    )
    first.path.write_bytes(b"corrupto")
    rec = Recorder([ok()])
    result = fetch(
        spec,
        raw_dir=tmp_path,
        today=date(2026, 10, 5),
        client=rec.client(),
        sleep=lambda _s: None,
    )
    assert len(rec.requests) == 1
    assert result.from_cache is False
    assert result.path.read_bytes() == PAYLOAD


def test_most_recent_valid_cache_directory_is_used(spec: SourceSpec, tmp_path: Path) -> None:
    for day in (date(2026, 9, 1), date(2026, 9, 20)):
        fetch(
            spec,
            raw_dir=tmp_path,
            today=day,
            refresh=True,
            client=Recorder([ok()]).client(),
            sleep=lambda _s: None,
        )
    rec = Recorder([status(500)])
    result = fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=lambda _s: None)
    assert result.path.parent.name == "2026-09-20"
    assert rec.requests == []


# --- modo offline -----------------------------------------------------------------------


def test_offline_without_cache_raises(spec: SourceSpec, tmp_path: Path) -> None:
    rec = Recorder([ok()])
    with pytest.raises(DownloadError) as excinfo:
        fetch(
            spec,
            raw_dir=tmp_path,
            today=TODAY,
            offline=True,
            client=rec.client(),
            sleep=lambda _s: None,
        )
    assert rec.requests == []
    assert "offline" in str(excinfo.value).lower()


def test_offline_uses_cache_even_if_expired(spec: SourceSpec, tmp_path: Path) -> None:
    aging = dataclasses.replace(spec, max_cache_age_days=7)
    fetch(
        aging,
        raw_dir=tmp_path,
        today=TODAY,
        client=Recorder([ok()]).client(),
        sleep=lambda _s: None,
    )
    rec = Recorder([ok()])
    result = fetch(
        aging,
        raw_dir=tmp_path,
        today=date(2027, 1, 1),
        offline=True,
        client=rec.client(),
        sleep=lambda _s: None,
    )
    assert result.from_cache is True
    assert rec.requests == []


# --- CKAN (datos.gob.cl) en dos pasos ----------------------------------------------------


@pytest.fixture
def ckan_json(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "minsal_establishments" / "ckan_resource_show.json").read_bytes()


@pytest.fixture
def sample_csv_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "minsal_establishments" / "establishments_sample.csv").read_bytes()


def _ckan_handler(ckan_json: bytes, csv_bytes: bytes) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/3/action/resource_show":
            return httpx.Response(
                200, content=ckan_json, headers={"content-type": "application/json"}
            )
        if request.url.path.endswith(".csv"):
            return httpx.Response(200, content=csv_bytes, headers={"content-type": "text/csv"})
        return httpx.Response(404)

    return handler


def test_ckan_source_resolves_the_url_then_downloads(
    tmp_path: Path, ckan_json: bytes, sample_csv_bytes: bytes
) -> None:
    spec = get_source("minsal_establishments")
    rec = Recorder(_ckan_handler(ckan_json, sample_csv_bytes))
    result = fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=lambda _s: None)

    assert len(rec.requests) == 2
    first, second = rec.requests
    assert first.url.host == "datos.gob.cl"
    assert first.url.path == "/api/3/action/resource_show"
    assert first.url.params["id"] == "2c44d782-3365-44e3-aefb-2c8b8363a1bc"
    expected_url = json.loads(ckan_json)["result"]["url"]
    assert str(second.url) == expected_url
    assert result.metadata.resolved_url == expected_url
    assert "resource_show" in result.metadata.url
    assert result.path.read_bytes() == sample_csv_bytes
    assert result.path.name == spec.filename
    assert result.metadata.sha256 == _sha(sample_csv_bytes)


def test_ckan_cache_expires_after_a_week(
    tmp_path: Path, ckan_json: bytes, sample_csv_bytes: bytes
) -> None:
    spec = get_source("minsal_establishments")
    assert spec.max_cache_age_days == 7
    fetch(
        spec,
        raw_dir=tmp_path,
        today=TODAY,
        client=Recorder(_ckan_handler(ckan_json, sample_csv_bytes)).client(),
        sleep=lambda _s: None,
    )
    within = Recorder(_ckan_handler(ckan_json, sample_csv_bytes))
    hit = fetch(
        spec,
        raw_dir=tmp_path,
        today=date(2026, 10, 9),
        client=within.client(),
        sleep=lambda _s: None,
    )
    assert hit.from_cache is True
    assert within.requests == []

    later = Recorder(_ckan_handler(ckan_json, sample_csv_bytes))
    miss = fetch(
        spec,
        raw_dir=tmp_path,
        today=date(2026, 10, 12),
        client=later.client(),
        sleep=lambda _s: None,
    )
    assert miss.from_cache is False
    assert len(later.requests) == 2


def test_resolve_url_for_fixed_url_sources_needs_no_request(spec: SourceSpec) -> None:
    rec = Recorder([status(500)])
    assert resolve_url(spec, rec.client()) == URL
    assert rec.requests == []


@pytest.mark.parametrize(
    "body",
    [b"no es json", b"{}", b'{"result": {}}', b'{"result": {"url": ""}}', b'{"result": null}'],
)
def test_malformed_ckan_response_raises_download_error(tmp_path: Path, body: bytes) -> None:
    spec = get_source("minsal_establishments")
    rec = Recorder([httpx.Response(200, content=body)])
    with pytest.raises(DownloadError):
        fetch(spec, raw_dir=tmp_path, today=TODAY, client=rec.client(), sleep=lambda _s: None)


# --- la red real está bloqueada en los tests ----------------------------------------------


def test_conftest_blocks_the_real_httpx_transport() -> None:
    with pytest.raises(RuntimeError, match="red bloqueada"), httpx.Client() as client:
        client.get("https://example.com/")


def test_fetch_without_client_cannot_reach_the_network(spec: SourceSpec, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="red bloqueada"):
        fetch(spec, raw_dir=tmp_path, today=TODAY, sleep=lambda _s: None)
    assert not list(tmp_path.rglob("prueba.pdf*"))
