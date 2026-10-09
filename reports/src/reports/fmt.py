"""Filtros de formato en español de Chile para las plantillas del informe.

Miles con punto, decimal con coma, porcentajes con espacio ("14,5 %"), fechas ``dd-mm-aaaa``.
Son funciones puras: un valor ``None`` o no numérico levanta ``TypeError`` en vez de imprimirse
como un cero silencioso (las plantillas deciden qué mostrar cuando un dato no existe).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_MINUS = "-"
_AGE_RANGE = re.compile(r"^(\d+)_(\d+)$")
_AGE_OPEN = re.compile(r"^(\d+)_plus$")
_MAX_DECIMALS = 12
_TINY = 1e-9


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"se esperaba un número y llegó {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError(f"se esperaba un número finito y llegó {value!r}")
    return float(value)


def _localize(text: str) -> str:
    """Pasa de formato inglés (``1,234.5``) a español (``1.234,5``)."""
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _rounded(value: float, decimals: int) -> Decimal:
    """Redondeo a ``decimals`` decimales con la mitad hacia arriba (no el redondeo bancario)."""
    if decimals < 0 or decimals > _MAX_DECIMALS:
        raise ValueError(f"decimals fuera de rango: {decimals}")
    quantum = Decimal(1).scaleb(-decimals)
    rounded = Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return abs(rounded) if rounded == 0 else rounded  # sin "-0"


def _fixed(value: float, decimals: int) -> str:
    """Número con ``decimals`` decimales y separadores en español."""
    return _localize(f"{_rounded(value, decimals):,.{decimals}f}")


def num(value: Any, decimals: int = 0) -> str:
    """Número con miles en punto y decimal en coma: ``1.234,5``."""
    return _fixed(_number(value), decimals)


def raw(value: Any) -> str:
    """Entero sin separadores (para comandos, identificadores y semillas)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"se esperaba un entero y llegó {value!r}")
    return str(value)


def pct(value: Any, decimals: int = 1) -> str:
    """Fracción como porcentaje: ``0.1458`` -> ``14,6 %``."""
    return f"{_fixed(_number(value) * 100, decimals)} %"


def pp(value: Any, decimals: int = 1) -> str:
    """Diferencia de fracciones en puntos porcentuales, con signo: ``+1,2 pp``."""
    return f"{_signed_fixed(_number(value) * 100, decimals)} pp"


def days(value: Any, decimals: int = 0) -> str:
    """Días con su unidad, en singular cuando vale uno: ``242 días``."""
    number = _number(value)
    unit = "día" if _rounded(number, decimals) == 1 else "días"
    return f"{_fixed(number, decimals)} {unit}"


def _signed_fixed(value: float, decimals: int) -> str:
    text = _fixed(value, decimals)
    if _rounded(value, decimals) == 0:
        return text  # cero: sin signo
    return text if value < 0 else f"+{text}"


def signed(value: Any, decimals: int = 0) -> str:
    """Número con signo explícito: ``+1,5``, ``-3``, ``0``."""
    return _signed_fixed(_number(value), decimals)


def sig(value: Any, digits: int = 3) -> str:
    """Número con ``digits`` cifras significativas y sin notación científica."""
    number = _number(value)
    if abs(number) < _TINY:
        return "0"  # ruido de coma flotante (por ejemplo 1e-17), no un valor medido
    if number == int(number):
        return _fixed(number, 0)
    decimals = max(0, digits - 1 - math.floor(math.log10(abs(number))))
    return _fixed(number, min(decimals, _MAX_DECIMALS))


def date(value: Any) -> str:
    """Fecha ISO (con o sin hora) como ``dd-mm-aaaa``."""
    if not isinstance(value, str):
        raise TypeError(f"se esperaba una fecha ISO y llegó {value!r}")
    return datetime.fromisoformat(value).strftime("%d-%m-%Y")


def _stat_values(stat: Mapping[str, Any]) -> tuple[float, float, float]:
    try:
        return (
            _number(stat["mean"]),
            _number(stat["ci95_low"]),
            _number(stat["ci95_high"]),
        )
    except KeyError as exc:
        raise TypeError(f"la estadística no tiene la clave {exc}") from exc


def _one(value: float, kind: str, decimals: int | None, with_sign: bool) -> str:
    if kind == "rate":
        places = 1 if decimals is None else decimals
        return pp(value, places) if with_sign else pct(value, places)
    places = 1 if decimals is None else decimals
    return _signed_fixed(value, places) if with_sign else _fixed(value, places)


def ci(
    stat: Mapping[str, Any],
    kind: str = "count",
    decimals: int | None = None,
    with_sign: bool = False,
) -> str:
    """Media con su IC 95 %: ``x (IC 95 % a a b)``.

    ``stat`` trae ``mean``, ``ci95_low`` y ``ci95_high``. ``kind`` es ``count``/``days`` (número) o
    ``rate`` (fracción mostrada como porcentaje, o como puntos porcentuales si ``with_sign``).
    """
    if kind not in {"count", "days", "rate"}:
        raise ValueError(f"kind desconocido: {kind!r}")
    mean, low, high = _stat_values(stat)
    center = _one(mean, kind, decimals, with_sign)
    lower = _one(low, kind, decimals, with_sign)
    upper = _one(high, kind, decimals, with_sign)
    return f"{center} (IC 95 % {lower} a {upper})"


def label(value: Any) -> str:
    """Nombre de grupo legible y seguro en una celda de tabla Markdown.

    ``0_14`` -> ``0-14``, ``65_plus`` -> ``65+``; el resto cambia ``_`` por espacio y escapa ``|``.
    """
    if not isinstance(value, str):
        raise TypeError(f"se esperaba un texto y llegó {value!r}")
    ranged = _AGE_RANGE.match(value)
    if ranged:
        return f"{ranged.group(1)}-{ranged.group(2)}"
    opened = _AGE_OPEN.match(value)
    if opened:
        return f"{opened.group(1)}+"
    return cell(value.replace("_", " "))


def cell(value: Any) -> str:
    """Texto seguro para una celda de tabla Markdown (escapa ``|`` y saltos de línea)."""
    text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def arg(value: Any) -> str:
    """Valor para la línea de comandos de la metodología (sin separadores de miles)."""
    if isinstance(value, bool):
        raise TypeError("un booleano no es un argumento numérico")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list | tuple):
        return ",".join(arg(v) for v in value)
    if isinstance(value, str):
        return value
    raise TypeError(f"argumento no soportado: {value!r}")


def short(value: Any, length: int = 8) -> str:
    """Prefijo de un identificador (por ejemplo, el id corto de una corrida)."""
    if not isinstance(value, str):
        raise TypeError(f"se esperaba un texto y llegó {value!r}")
    return value[:length]


def show(value: Any) -> str:
    """Valor de un parámetro de las reglas o de la configuración, con formato por tipo."""
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, int):
        return num(value)
    if isinstance(value, float):
        text = sig(value, 4)
        return text.rstrip("0").rstrip(",") if "," in text else text
    if isinstance(value, list | tuple):
        return ", ".join(show(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {show(v)}" for k, v in value.items())
    if value is None:
        return "sin valor"
    return cell(value)


FILTERS: dict[str, Callable[..., str]] = {
    "num": num,
    "raw": raw,
    "pct": pct,
    "pp": pp,
    "days": days,
    "signed": signed,
    "sig": sig,
    "date": date,
    "ci": ci,
    "label": label,
    "cell": cell,
    "show": show,
    "arg": arg,
    "short": short,
}
