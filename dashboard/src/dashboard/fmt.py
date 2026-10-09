"""Formato de cifras, fechas y nombres en español de Chile.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

NBSP = " "
MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

AGE_LABELS = {
    "0_14": "0-14",
    "15_19": "15-19",
    "20_44": "20-44",
    "45_64": "45-64",
    "65_plus": "65 o más",
}
INSURANCE_LABELS = {
    "fonasa_a": "Fonasa A",
    "fonasa_b": "Fonasa B",
    "fonasa_c": "Fonasa C",
    "fonasa_d": "Fonasa D",
    "other": "Otra previsión",
}
CARE_LABELS = {"consultation": "Consulta nueva", "surgery": "Cirugía"}
CAUSE_LABELS = {
    "no_block_in_horizon": "Sin bloque en el horizonte",
    "deadline_before_first_block": "Vence antes del primer bloque",
    "capacity_taken": "Cupos tomados",
    "overbooking_interaction": "Interacción con el sobrecupo",
}
STATUS_LABELS = {
    "scheduled": "Agendada",
    "capacity_taken": "Cupos tomados",
    "no_compatible_block": "Sin bloque compatible",
    "overbooking_interaction": "Interacción con el sobrecupo",
}
KIND_LABELS = {"specialist_agenda": "Agenda de especialista", "operating_room": "Pabellón"}


def num(value: float | int | None, decimals: int = 0) -> str:
    """Número con punto de miles y coma decimal (`1.234,5`); `—` si falta."""
    if value is None:
        return "—"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pct(fraction: float | None, decimals: int = 1) -> str:
    """Fracción como porcentaje con espacio duro (`22,7 %`)."""
    if fraction is None:
        return "—"
    return f"{num(fraction * 100, decimals)}{NBSP}%"


def days(value: float | int | None) -> str:
    """Días con unidad (`301 días`)."""
    if value is None:
        return "—"
    return f"{num(value)}{NBSP}día" + ("" if round(value) == 1 else "s")


def date_es(value: date | datetime | str | None, *, year: bool = True) -> str:
    """Fecha corta (`9 oct 2026`); acepta texto ISO."""
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    text = f"{value.day} {MONTHS[value.month - 1]}"
    return f"{text} {value.year}" if year else text


def weekday_date(value: date | str) -> str:
    """Día de la semana y fecha (`lun 6 oct`)."""
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def short_id(value: str | None) -> str:
    """Primeros 8 caracteres de un identificador."""
    return (value or "")[:8]


def humanize(code: str | None) -> str:
    """Texto legible de un código (`cne_medical:medicina_interna` -> `Medicina interna`)."""
    if not code:
        return "—"
    tail = code.split(":")[-1].replace("_", " ")
    return tail[:1].upper() + tail[1:]


def group_label(dimension: str, value: Any) -> str:
    """Nombre de un grupo de equidad."""
    text = str(value)
    if dimension == "age_group":
        return AGE_LABELS.get(text, text)
    if dimension == "insurance":
        return INSURANCE_LABELS.get(text, text)
    if dimension == "commune_code":
        return f"Comuna {text}"
    return text


def cause_label(cause: str | None) -> str:
    """Causa de incumplimiento GES en español."""
    if cause is None:
        return "Sin causa registrada"
    return CAUSE_LABELS.get(cause, humanize(cause))


def status_label(status: str | None) -> str:
    """Estado de una explicación en español."""
    if status is None:
        return "—"
    return STATUS_LABELS.get(status, humanize(status))
