"""Cálculo de prioridades basado en reglas explícitas para Prioriza.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Implementa el puntaje transparente y auditable que combina prioridad clínica (definida por
profesionales), tiempo de espera y plazos de garantías GES. El sistema apoya, no decide.
"""

from priority.explain import Explanation, explain, explain_ranked, explanation_to_dict
from priority.inputs import PriorityInput
from priority.rules import (
    RulesError,
    RuleSet,
    load_default_rules,
    load_rules,
    parse_rules,
)
from priority.score import (
    ComponentContribution,
    PriorityScore,
    RankedEntry,
    Ranking,
    StrictTier,
    rank,
    score_entry,
    sort_key,
    strict_tier,
)

__all__ = [
    "ComponentContribution",
    "Explanation",
    "PriorityInput",
    "PriorityScore",
    "RankedEntry",
    "Ranking",
    "RuleSet",
    "RulesError",
    "StrictTier",
    "explain",
    "explain_ranked",
    "explanation_to_dict",
    "load_default_rules",
    "load_rules",
    "parse_rules",
    "rank",
    "score_entry",
    "sort_key",
    "strict_tier",
]
