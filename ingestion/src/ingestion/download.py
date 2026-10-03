"""Descarga con caché local, reintentos y verificación de sha256.

Layout de la caché: ``<raw_dir>/<source_id>/<YYYY-MM-DD>/<filename>`` más un
``metadata.json`` con la procedencia. Los archivos se escriben primero a ``<archivo>.part``
y se renombran atómicamente.
"""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel

from ingestion.errors import DownloadError
from ingestion.sources import SourceKind, SourceSpec

USER_AGENT = "Mozilla/5.0 (compatible; Prioriza/0.1; +https://github.com/TheNewAarons/prioriza)"
CKAN_RESOURCE_SHOW = "https://datos.gob.cl/api/3/action/resource_show"
METADATA_NAME = "metadata.json"
_TIMEOUT = httpx.Timeout(120, connect=10)


class RawMetadata(BaseModel):
    """Procedencia de un archivo descargado (sidecar ``metadata.json``)."""

    source_id: str
    url: str
    resolved_url: str
    downloaded_at: datetime
    sha256: str
    size_bytes: int
    content_type: str | None
    http_status: int
    filename: str


@dataclass
class DownloadResult:
    """Resultado de :func:`fetch`: ruta local, metadatos y si vino de la caché."""

    path: Path
    metadata: RawMetadata
    from_cache: bool


def sha256_file(path: Path) -> str:
    """Calcula el sha256 hexadecimal de un archivo."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get(
    client: httpx.Client,
    url: str,
    *,
    source_id: str,
    sleep: Callable[[float], None],
    max_attempts: int,
    backoff_base: float,
) -> httpx.Response:
    """GET con reintento solo ante errores de transporte, 429 y 5xx."""
    last_error = ""
    for attempt in range(max_attempts):
        if attempt > 0:
            sleep(backoff_base * 2 ** (attempt - 1))
        try:
            response = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.TransportError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        status = response.status_code
        if status == 429 or status >= 500:
            last_error = f"HTTP {status}"
            continue
        if status >= 400:
            raise DownloadError(f"[{source_id}] HTTP {status} al descargar {url}")
        return response
    raise DownloadError(
        f"[{source_id}] sin respuesta válida tras {max_attempts} intentos ({last_error}): {url}"
    )


def _check_content(spec: SourceSpec, body: bytes) -> None:
    """Verifica que el contenido corresponda al tipo esperado (PDF, XLSX o CSV).

    Un WAF o una página de error pueden responder 200 con HTML (a veces con un
    ``content-type`` engañoso): se mira el contenido, no los encabezados.
    """
    head = body[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if spec.kind is SourceKind.GLOSA06_PDF:
        ok, expected = body.startswith(b"%PDF"), "PDF (empieza con '%PDF')"
    elif spec.kind is SourceKind.SIS_GES_XLSX:
        ok, expected = body.startswith(b"PK"), "XLSX (zip, empieza con 'PK')"
    else:
        lowered = head[:64].lower()
        ok = bool(head) and not (
            head.startswith(b"<") or lowered.startswith((b"<!doctype", b"<html"))
        )
        expected = "CSV (no HTML)"
    if not ok:
        raise DownloadError(
            f"[{spec.source_id}] el contenido descargado no es un archivo {expected}: "
            f"empieza con {body[:24]!r}. Probable página de error o bloqueo; no se guardó."
        )


def resolve_url(
    spec: SourceSpec,
    client: httpx.Client,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = 4,
    backoff_base: float = 1.0,
) -> str:
    """Devuelve la URL de descarga: la fija o, para CKAN, la que informa ``resource_show``."""
    if spec.kind is not SourceKind.CKAN_CSV:
        if spec.url is None:
            raise DownloadError(f"[{spec.source_id}] la fuente no define url")
        return spec.url
    api_url = f"{CKAN_RESOURCE_SHOW}?id={spec.ckan_resource_id}"
    response = _get(
        client,
        api_url,
        source_id=spec.source_id,
        sleep=sleep,
        max_attempts=max_attempts,
        backoff_base=backoff_base,
    )
    try:
        url = response.json()["result"]["url"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DownloadError(f"[{spec.source_id}] respuesta CKAN inesperada: {exc!r}") from exc
    if not isinstance(url, str) or not url:
        raise DownloadError(f"[{spec.source_id}] CKAN no devolvió una url de recurso")
    return url


def _find_cache(spec: SourceSpec, raw_dir: Path) -> tuple[DownloadResult, date] | None:
    """Busca el directorio de caché más reciente cuyo archivo coincide con su sha256."""
    base = raw_dir / spec.source_id
    if not base.is_dir():
        return None
    for directory in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        path = directory / spec.filename
        meta_path = directory / METADATA_NAME
        if not path.is_file() or not meta_path.is_file():
            continue
        try:
            metadata = RawMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
            dir_date = date.fromisoformat(directory.name)
        except ValueError:
            continue
        digest = sha256_file(path)
        if digest != metadata.sha256:
            continue
        if spec.expected_sha256 is not None and digest != spec.expected_sha256:
            continue
        return DownloadResult(path=path, metadata=metadata, from_cache=True), dir_date
    return None


def fetch(
    spec: SourceSpec,
    *,
    raw_dir: Path,
    today: date,
    refresh: bool = False,
    offline: bool = False,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = 4,
    backoff_base: float = 1.0,
) -> DownloadResult:
    """Obtiene el archivo de la fuente, desde la caché si es válida o descargándolo.

    - ``refresh`` fuerza la descarga; ``offline`` prohíbe la red (error si no hay caché).
    - La caché vence tras ``spec.max_cache_age_days`` (salvo en modo ``offline``).
    - Si el sha256 esperado no coincide, se borra lo descargado y se lanza ``DownloadError``.
    """
    cached = _find_cache(spec, raw_dir)
    if cached is not None and not refresh:
        result, dir_date = cached
        age = (today - dir_date).days
        if offline or spec.max_cache_age_days is None or age <= spec.max_cache_age_days:
            return result
    if offline:
        raise DownloadError(
            f"[{spec.source_id}] modo offline y no hay caché válida en {raw_dir / spec.source_id}"
        )

    owns_client = client is None
    http = client or httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    try:
        resolved = resolve_url(
            spec, http, sleep=sleep, max_attempts=max_attempts, backoff_base=backoff_base
        )
        response = _get(
            http,
            resolved,
            source_id=spec.source_id,
            sleep=sleep,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    finally:
        if owns_client:
            http.close()

    target_dir = raw_dir / spec.source_id / today.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / spec.filename
    part = path.with_name(path.name + ".part")
    part.write_bytes(response.content)
    digest = sha256_file(part)
    if spec.expected_sha256 is not None and digest != spec.expected_sha256:
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"[{spec.source_id}] sha256 distinto del esperado: esperado "
            f"{spec.expected_sha256}, obtenido {digest}. El archivo publicado cambió; "
            "revise la fuente y actualice el registro (sources.py)."
        )
    try:
        _check_content(spec, response.content)
    except DownloadError:
        part.unlink(missing_ok=True)
        raise
    part.replace(path)
    metadata = RawMetadata(
        source_id=spec.source_id,
        url=spec.url or f"{CKAN_RESOURCE_SHOW}?id={spec.ckan_resource_id}",
        resolved_url=resolved,
        downloaded_at=datetime.now(UTC),
        sha256=digest,
        size_bytes=path.stat().st_size,
        content_type=response.headers.get("content-type"),
        http_status=response.status_code,
        filename=spec.filename,
    )
    (target_dir / METADATA_NAME).write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    return DownloadResult(path=path, metadata=metadata, from_cache=False)
