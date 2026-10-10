"""Exportación de un plan a CSV.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Formato: UTF-8 sin BOM, separador coma, fin de línea `\\n`. Las primeras líneas empiezan con `#`
(aviso y estado de revisión): quien lea el archivo con un lector CSV debe saltar las líneas que
empiezan con `#`. Después viene la fila de encabezados y una fila por cita propuesta. Los
encabezados están en español; el orden y el nombre de las columnas son estables. Las celdas de
texto que empiezan con `=`, `+`, `-`, `@`, tabulación o retorno de carro se prefijan con `'` para
que una hoja de cálculo no las interprete como fórmula.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from shared.disclaimer import DISCLAIMER

# (clave del API, encabezado en español). No cambiar el orden ni los nombres sin avisar.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("entry_id", "Entrada"),
    ("patient_id", "Paciente sintético"),
    ("slot_id", "Cupo"),
    ("specialty_code", "Especialidad"),
    ("scheduled_start", "Inicio (UTC)"),
    ("duration_min", "Duración (min)"),
    ("lead_days", "Anticipación (días)"),
    ("is_overbooked", "Sobrecupo"),
    ("predicted_noshow_prob", "Probabilidad de inasistencia"),
)
HEADERS = tuple(h for _, h in COLUMNS)
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize(value: str) -> str:
    """Antepone `'` al texto que una hoja de cálculo leería como fórmula."""
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


def cell(value: Any) -> str:
    """Valor de una celda: booleanos `sí`/`no`, fechas ISO, nulos vacíos, texto neutralizado."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, datetime):
        return value.isoformat()
    return neutralize(str(value))


def comment_lines(
    plan_id: str, review_status: str, *, offset: int, exported: int, total: int
) -> list[str]:
    """Líneas `#` iniciales: aviso, estado de revisión y, si aplica, el recorte por el tope."""
    lines = [
        f"# aviso: {DISCLAIMER}",
        f"# plan: {plan_id}; estado de revisión: {review_status}; "
        "todo plan requiere revisión humana antes de usarse",
    ]
    if offset + exported < total:
        lines.append(
            f"# truncado: se exportaron {exported} filas desde la {offset + 1} de {total}; "
            "usa offset y limit para continuar"
        )
    return lines


def render_csv(
    rows: Sequence[Mapping[str, Any]],
    *,
    plan_id: str,
    review_status: str,
    total: int,
    offset: int = 0,
) -> str:
    """CSV completo: líneas `#`, encabezados y una fila por asignación."""
    buf = io.StringIO()
    for line in comment_lines(
        plan_id, review_status, offset=offset, exported=len(rows), total=total
    ):
        buf.write(line + "\n")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADERS)
    for row in rows:
        writer.writerow([cell(row.get(key)) for key, _ in COLUMNS])
    return buf.getvalue()
