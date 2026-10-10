"""Redacción de datos personales y secretos en los logs.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

`install_redaction()` registra una fábrica de `LogRecord` que limpia el mensaje y cada
argumento textual al crear el registro, antes de que cualquier manejador o formateador lo vea.
Así cubre todos los loggers (API, uvicorn y su access log, werkzeug, panel) sin tocar su
configuración, y conserva la estructura de `args`: el `AccessFormatter` de uvicorn desempaqueta
`(cliente, método, ruta, versión, código)` y seguiría funcionando.

Se redactan: identificadores de paciente y de entrada en rutas, parámetros y mensajes, RUT
chilenos, correos, la cabecera `X-API-Key` y cualquier valor registrado con `register_secret`.
Los trazados de excepciones se limpian con `RedactingFilter` (se añade a los manejadores).
Es una red de seguridad: el código no debe registrar datos personales en primer lugar.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any

REDACTED = "[REDACTADO]"
# Un secreto más corto que esto produciría falsos positivos al buscarlo en texto libre.
MIN_SECRET_LENGTH = 8

_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Segmento de ruta tras /patients/ (o /pacientes/, /entries/, /entradas/).
_PATH_ID = re.compile(r"(?i)(/(?:patients|pacientes|entries|entradas)/)[^/?#\s\"']+")
# `patient_id=..`, `entry_id: ..`, `"patient_id": ".."`.
_KEY_ID = re.compile(
    r"(?i)((?:patient|paciente|entry|entrada)_?id[\"']?\s*[=:]\s*[\"']?)[^\s&,;\"'}\]]+"
)
# "no existe el paciente P-00123": solo si el identificador lleva algún dígito.
_WORD_ID = re.compile(r"(?i)\b(paciente|patient|entrada|entry)(\s+)(?=[\w-]*\d)[\w-]+")
_API_KEY_HEADER = re.compile(r"(?i)(x-api-key[\"']?\s*[=:,]\s*(?:b?[\"'])?)[^\s\"',;}]+")

_lock = threading.Lock()
_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Registra un valor (p. ej. una clave de API) que no debe aparecer nunca en un log."""
    if value and len(value) >= MIN_SECRET_LENGTH:
        with _lock:
            _secrets.add(value)


def clear_secrets() -> None:
    """Olvida los secretos registrados (tests)."""
    with _lock:
        _secrets.clear()


def redact(text: str) -> str:
    """Devuelve `text` sin identificadores, RUT, correos, cabecera de clave ni secretos."""
    with _lock:
        known = sorted(_secrets, key=len, reverse=True)
    for secret in known:
        if secret in text:
            text = text.replace(secret, REDACTED)
    text = _API_KEY_HEADER.sub(rf"\1{REDACTED}", text)
    text = _PATH_ID.sub(rf"\1{REDACTED}", text)
    text = _KEY_ID.sub(rf"\1{REDACTED}", text)
    text = _WORD_ID.sub(rf"\1\2{REDACTED}", text)
    text = _RUT.sub(REDACTED, text)
    return _EMAIL.sub(REDACTED, text)


def _redact_arg(arg: object) -> object:
    if isinstance(arg, str):
        return redact(arg)
    if isinstance(arg, BaseException):
        return redact(str(arg))
    return arg


def _redact_args(args: Any) -> Any:
    if isinstance(args, tuple):
        return tuple(_redact_arg(a) for a in args)
    if isinstance(args, Mapping):
        return {k: _redact_arg(v) for k, v in args.items()}
    return args


def _redact_record(record: logging.LogRecord) -> None:
    if isinstance(record.msg, str):
        record.msg = redact(record.msg)
    record.args = _redact_args(record.args)
    # El trazado se formatea aquí, ya limpio: `logging.Formatter.format` usa `exc_text` si existe
    # y no vuelve a formatear `exc_info`. Así quedan cubiertos también los manejadores propios de
    # uvicorn o werkzeug, que no tienen `RedactingFilter`.
    if record.exc_info and record.exc_info[0] is not None and not record.exc_text:
        record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
    if record.stack_info:
        record.stack_info = redact(record.stack_info)


class RedactingFilter(logging.Filter):
    """Filtro de manejador o logger: limpia mensaje, argumentos y trazado de excepción."""

    def filter(self, record: logging.LogRecord) -> bool:
        _redact_record(record)
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


_installed = False
_previous_factory: Callable[..., logging.LogRecord] | None = None


def install_redaction() -> None:
    """Instala la redacción para todos los loggers del proceso (idempotente)."""
    global _installed, _previous_factory
    with _lock:
        if _installed:
            return
        _installed = True
        previous = logging.getLogRecordFactory()
        _previous_factory = previous

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        _redact_record(record)
        return record

    logging.setLogRecordFactory(factory)
    root_filter = RedactingFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(root_filter)


def uninstall_redaction() -> None:
    """Restaura la fábrica anterior (tests)."""
    global _installed, _previous_factory
    with _lock:
        if _installed and _previous_factory is not None:
            logging.setLogRecordFactory(_previous_factory)
        _installed = False
        _previous_factory = None
