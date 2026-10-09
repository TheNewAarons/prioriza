"""Atributos `aria-*` para componentes de Dash.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from typing import Any


def aria(values: dict[str, str]) -> dict[str, Any]:
    """Devuelve los atributos `aria-*` con tipo `Any` (los stubs de Dash no los conocen)."""
    return dict(values)
