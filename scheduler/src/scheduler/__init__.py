"""Programación óptima de pacientes con OR-Tools CP-SAT para Prioriza.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Asigna entradas de la lista de espera a bloques (sesiones CNE y bloques de pabellón)
según ``docs/scheduler-formulation.md``: cesión a p1, garantías GES duras cuando es factible,
suma de puntajes P4 y sobreagendamiento con límite de riesgo explícito. El sistema apoya, no
decide: todo plan requiere revisión humana.
"""

from scheduler.config import SchedulerConfig
from scheduler.instance import Block, Entry, SchedulingInstance
from scheduler.plan import SchedulePlan, greedy_schedule, solve

__all__ = [
    "Block",
    "Entry",
    "SchedulePlan",
    "SchedulerConfig",
    "SchedulingInstance",
    "greedy_schedule",
    "solve",
]
