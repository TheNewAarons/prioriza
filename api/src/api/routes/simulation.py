"""Resultados de la simulación de políticas."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from shared.db.enums import Policy

from api.auth import current_user
from api.deps import ServicesDep, errors
from api.schemas import SimulationOut

router = APIRouter(prefix="/v1", dependencies=[Depends(current_user)])


# Métricas por grupo de `replicas[i].policies[p].groups` que se resumen entre réplicas.
GROUP_METRICS = (
    "entries",
    "attended",
    "attention_rate",
    "ges_breached",
    "removed_no_show",
    "no_show_realized_rate",
    "overbooking_exposure",
    "overflow_share",
)
GAP_KEYS = (
    "max_gap_attention_rate",
    "max_gap_overbooking_exposure",
    "max_gap_no_show_realized_rate",
)


def _summary(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def equity_summary(replicas: list[dict[str, Any]], policies: set[str]) -> dict[str, Any]:
    """Equidad por política, dimensión y grupo, resumida entre réplicas (sin filtrar grupos).

    `{policy: {dimension: {"min_n", "groups": {value: {metric: resumen}}, gaps...}}}`; los
    grupos con menos de `min_n` entradas ya vienen excluidos de la simulación.
    """
    acc: dict[str, dict[str, dict[str, Any]]] = {}
    for replica in replicas:
        for policy, result in replica.get("policies", {}).items():
            if policy not in policies:
                continue
            for dim in result.get("groups", []):
                d = acc.setdefault(policy, {}).setdefault(
                    dim["dimension"], {"min_n": dim.get("min_n"), "groups": {}, "gaps": {}}
                )
                for key in GAP_KEYS:
                    if dim.get(key) is not None:
                        d["gaps"].setdefault(key, []).append(float(dim[key]))
                for g in dim.get("groups", []):
                    metrics = d["groups"].setdefault(str(g["value"]), {})
                    for m in GROUP_METRICS:
                        value = g.get(m)
                        if value is None:
                            continue
                        metrics.setdefault(m, []).append(float(value))
                    wait = (g.get("wait_attended") or {}).get("median")
                    if wait is not None:
                        metrics.setdefault("wait_attended_median", []).append(float(wait))
    out: dict[str, Any] = {}
    for policy, dims in sorted(acc.items()):
        out[policy] = {
            dim: {
                "min_n": d["min_n"],
                "groups": {
                    value: {m: _summary(vs) for m, vs in sorted(ms.items())}
                    for value, ms in sorted(d["groups"].items())
                },
                **{key: _summary(vs) for key, vs in sorted(d["gaps"].items())},
            }
            for dim, d in sorted(dims.items())
        }
    return out


def _involves(key: str, variants: set[str]) -> bool:
    """Una comparación `a_vs_b` involucra a la política si alguno de sus lados es una variante."""
    return any(side in variants for side in key.split("_vs_"))


@router.get(
    "/simulation",
    response_model=SimulationOut,
    tags=["simulación"],
    summary="Resumen de results/simulation.json",
    responses=errors(401, 404, e404="no hay resultados de simulación; ejecuta `make simulate`"),
)
def simulation(
    svc: ServicesDep,
    policy: Annotated[Policy | None, Query(description="Deja solo esta política.")] = None,
) -> SimulationOut:
    """Configuración, cobertura de oferta, agregados, comparaciones, equidad y limitaciones.

    Los resultados se informan tal cual, incluidas las métricas y los grupos en que la
    política optimizada no mejora o queda más expuesta al sobrecupo.
    """
    path = svc.settings.results_dir / "simulation.json"
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="no hay resultados de simulación; ejecuta `make simulate`",
        )
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    aggregate: dict[str, Any] = data["aggregate"]
    comparisons: dict[str, Any] = data["comparisons"]
    if policy is not None:
        variants = {k for k in aggregate if k == policy.value or k.startswith(f"{policy.value}_")}
        aggregate = {k: v for k, v in aggregate.items() if k in variants}
        comparisons = {k: v for k, v in comparisons.items() if _involves(k, variants)}
    equity = equity_summary(data.get("replicas", []), set(aggregate))
    return SimulationOut(
        generated_at=data["generated_at"],
        run=data["run"],
        noshow_model_version=data.get("noshow_model_version"),
        config=data["config"],
        supply_coverage=data["supply_coverage"],
        aggregate=aggregate,
        comparisons=comparisons,
        equity=equity,
        limitations=data["limitations"],
    )
