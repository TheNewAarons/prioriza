"""Insignias de estado con icono y texto (nunca solo color; ver `docs/design.md` §3).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from dash import html

from dashboard.components.attrs import aria
from dashboard.theme import STATUS


def status_badge(kind: str, text: str, *, extra_class: str = "") -> html.Span:
    """Insignia de un estado (`ok`, `pending`, `risk`, `overdue`, `current`)."""
    style = STATUS[kind]
    return html.Span(
        [html.Span(style.icon, **aria({"aria-hidden": "true"})), html.Span(text)],
        className=f"badge badge--{kind} {extra_class}".strip(),
    )


REVIEW_BADGES = {
    "pending": ("pending", "Pendiente de revisión"),
    "approved": ("ok", "Aprobado"),
    "rejected": ("overdue", "Rechazado"),
}


def plan_badges(review_status: str, is_current: bool) -> html.Span:
    """Estado de revisión del plan y, si corresponde, la insignia de vigente."""
    kind, text = REVIEW_BADGES.get(review_status, ("pending", review_status))
    items = [status_badge(kind, text, extra_class="fade-in")]
    if is_current:
        items.append(status_badge("current", "Vigente"))
    return html.Span(items, className="badge-row")


JOB_BADGES = {
    "queued": ("pending", "En cola", ""),
    "running": ("pending", "En curso", "pulse"),
    "succeeded": ("ok", "Terminado", ""),
    "failed": ("overdue", "Falló", ""),
}


def job_badge(job_status: str) -> html.Span:
    """Estado de un trabajo de programación (late mientras está en curso)."""
    kind, text, cls = JOB_BADGES.get(job_status, ("pending", job_status, ""))
    return status_badge(kind, text, extra_class=cls)


def ges_badge(state: str | None) -> html.Span | str:
    """Insignia GES: `risk`, `overdue`, `met`, `unmet`, `ges` (sin alerta) o texto vacío."""
    if state == "risk":
        return status_badge("risk", "En riesgo")
    if state == "overdue":
        return status_badge("overdue", "Vencida")
    if state == "met":
        return status_badge("ok", "Cumplida")
    if state == "unmet":
        return status_badge("overdue", "No cumplida")
    return ""
