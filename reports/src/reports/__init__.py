"""Informe de resultados de Prioriza.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Lee los JSON de ``results/``, arma un diccionario de hechos (``facts``) y renderiza
``docs/results.md`` y ``docs/results.html`` con plantillas Jinja2. Ninguna cifra se escribe a mano:
todas pasan por ``load_facts`` y los filtros de ``reports.fmt``.
"""

from reports.build import build_report
from reports.facts import FactsError, load_facts

__all__ = ["FactsError", "build_report", "load_facts"]
