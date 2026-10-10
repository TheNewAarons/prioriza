"""Redacción de datos personales y secretos en logs (P16-T1).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Los RUT, correos y ids de estos tests son inventados.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from shared.logging import (
    REDACTED,
    RedactingFilter,
    clear_secrets,
    install_redaction,
    redact,
    register_secret,
    uninstall_redaction,
)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    install_redaction()
    yield
    uninstall_redaction()
    clear_secrets()


@pytest.mark.parametrize(
    "text",
    [
        "paciente 12.345.678-5 llamó",
        "rut 12345678-K registrado",
        "contacto ana.perez@example.cl listo",
    ],
)
def test_rut_and_email_are_redacted(text: str) -> None:
    out = redact(text)
    assert REDACTED in out
    assert "12.345.678" not in out and "12345678" not in out and "example.cl" not in out


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("GET /v1/patients/P-000123 HTTP/1.1", "P-000123"),
        ("GET /v1/patients/abc123?x=1 HTTP/1.1", "abc123"),
        ("no existe el paciente P-000123", "P-000123"),
        ("patient_id=ZZ99 fallo", "ZZ99"),
        ("body {'entry_id': 'E-77'}", "E-77"),
        ("X-API-Key: super-secreta-123", "super-secreta-123"),
        ("headers={'x-api-key': 'otra-clave-456'}", "otra-clave-456"),
    ],
)
def test_ids_and_key_header_are_redacted(text: str, leaked: str) -> None:
    assert leaked not in redact(text)


def test_plain_text_is_untouched() -> None:
    text = "plan 3 aprobado por la persona revisora; paciente sintético sin id"
    assert redact(text) == text


def test_registered_secret_is_redacted_anywhere() -> None:
    register_secret("clave-muy-larga-de-prueba")
    assert "clave-muy-larga" not in redact("fallo con clave-muy-larga-de-prueba en la URL")
    register_secret("corta")  # demasiado corta: se ignora para evitar falsos positivos
    assert redact("corta") == "corta"


def test_caplog_messages_args_and_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    register_secret("clave-registrada-999")
    log = logging.getLogger("api.prueba")
    with caplog.at_level(logging.INFO):
        log.info("consulta %s de %s", "/v1/patients/P-1", "12.345.678-5")
        log.warning("clave %s", "clave-registrada-999")
        log.error("fallo: %s", ValueError("rut 12.345.678-5"))
    assert "P-1" not in caplog.text
    assert "12.345.678" not in caplog.text
    assert "clave-registrada-999" not in caplog.text
    assert "/v1/patients/" in caplog.text  # la estructura útil se conserva


def test_filter_redacts_exception_traceback() -> None:
    try:
        raise ValueError("rut 12.345.678-5")
    except ValueError:
        record = logging.LogRecord(
            "x", logging.ERROR, "f", 1, "falló", None, __import__("sys").exc_info()
        )
    RedactingFilter().filter(record)
    assert record.exc_text is not None and "12.345.678" not in record.exc_text


def test_install_is_idempotent() -> None:
    factory = logging.getLogRecordFactory()
    install_redaction()
    assert logging.getLogRecordFactory() is factory


def test_traceback_redacted_in_handlers_without_filter() -> None:
    """Un manejador sin `RedactingFilter` (como los de uvicorn) recibe el trazado ya limpio."""
    import io
    import logging

    from shared.logging import install_redaction, uninstall_redaction

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("prueba.uvicorn.error")
    logger.addHandler(handler)
    logger.propagate = False
    install_redaction()
    try:
        try:
            raise LookupError("no existe el paciente P-00123 (rut 12.345.678-5)")
        except LookupError:
            logger.exception("fallo en GET /v1/patients/P-00123")
    finally:
        uninstall_redaction()
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "P-00123" not in out and "12.345.678-5" not in out
    assert "Traceback" in out and "LookupError" in out
