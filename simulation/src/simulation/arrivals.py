"""Celdas de llegada: θ por celda y filas donantes para copiar atributos (diseño §2).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simulation.world import World


@dataclass(frozen=True)
class ArrivalCell:
    """Celda de llegada con su θ, la parte GES y las filas donantes del stock."""

    service: int
    care_type: str
    specialty: str
    throughput_per_week: float
    ges_throughput_per_week: float
    donors: tuple[dict[str, Any], ...]
    ges_donors: tuple[dict[str, Any], ...]
    non_ges_donors: tuple[dict[str, Any], ...]


def arrival_cells(world: World) -> list[ArrivalCell]:
    """Una celda por ``world.cells`` con sus donantes (stock + atributos del paciente).

    El generador reparte la tasa GES de cada (servicio, tipo) entre todas sus especialidades
    según el stock, también las que no tienen problemas GES. Aquí la parte GES del grupo se
    reasigna solo a las celdas con filas GES en el stock, en proporción a esas filas, para que
    cada llegada GES copie procedimiento y plazo de su propia especialidad. La tasa total del
    grupo no cambia; si el grupo no tiene filas GES, su parte GES llega como no GES.
    """
    donors = world.stock.join(world.patient_frame, on="patient_id", how="left")
    rows_by_cell: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for r in donors.sort("id").iter_rows(named=True):
        key = (int(r["health_service_code"]), str(r["care_type"]), str(r["specialty_code"]))
        rows_by_cell.setdefault(key, []).append(dict(r))
    ges_rate: dict[tuple[int, str], float] = {}
    ges_rows: dict[tuple[int, str], int] = {}
    for cell in world.cells:
        group = (cell.service, cell.care_type)
        ges_rate[group] = ges_rate.get(group, 0.0) + cell.ges_throughput_per_week
        rows = rows_by_cell.get((cell.service, cell.care_type, cell.specialty), [])
        ges_rows[group] = ges_rows.get(group, 0) + sum(1 for r in rows if r["is_ges"])
    out: list[ArrivalCell] = []
    for cell in world.cells:
        group = (cell.service, cell.care_type)
        rows = rows_by_cell.get((cell.service, cell.care_type, cell.specialty), [])
        ges = [r for r in rows if r["is_ges"]]
        non_ges_rate = cell.throughput_per_week - cell.ges_throughput_per_week
        if ges_rows[group] > 0:
            cell_ges = ges_rate[group] * len(ges) / ges_rows[group]
        else:
            cell_ges, non_ges_rate = 0.0, cell.throughput_per_week
        out.append(
            ArrivalCell(
                service=cell.service,
                care_type=cell.care_type,
                specialty=cell.specialty,
                throughput_per_week=non_ges_rate + cell_ges,
                ges_throughput_per_week=cell_ges,
                donors=tuple(rows),
                ges_donors=tuple(ges),
                non_ges_donors=tuple(r for r in rows if not r["is_ges"]),
            )
        )
    return out
