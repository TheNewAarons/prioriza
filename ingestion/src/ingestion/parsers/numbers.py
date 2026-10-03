"""Números en formato chileno (punto de miles, coma decimal)."""

import re

_NUMBER = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?\*{0,2}$")


def is_number_token(token: str) -> bool:
    """True si el token es una cifra de tabla (incluye ``-``, que significa cero)."""
    return token == "-" or _NUMBER.match(token) is not None


def parse_cl_number(token: str) -> float:
    """Convierte un número chileno a ``float``.

    ``1.234`` -> 1234, ``1234`` -> 1234, ``201,2`` -> 201.2, ``-`` -> 0. Se ignoran los
    sufijos ``*``/``**`` de nota al pie. Lanza ``ValueError`` si el token no es un número.
    """
    text = token.strip().rstrip("*")
    if text == "-":
        return 0.0
    if not _NUMBER.match(text):
        raise ValueError(f"número chileno inválido: {token!r}")
    return float(text.replace(".", "").replace(",", "."))
