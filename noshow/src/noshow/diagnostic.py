"""Diagnóstico (solo medición) del costo en desempeño de las variables excluidas por equidad.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Responde una sola pregunta: ¿cuánto desempeño se pierde por no usar ``age_group``,
``insurance``, ``commune_code`` y ``health_service_code``? Para eso reentrena, con el MISMO
split temporal, los mismos candidatos e hiperparámetros, la misma regla de calibración, la
misma selección en el conjunto de calibración y la misma semilla que el modelo principal,
variantes que agregan esas variables (por separado y juntas) a las permitidas.

Garantías (verificadas en ``noshow/tests/test_noshow_diagnostic.py``):

- Es solo medición. Ningún modelo de este módulo sale de ``diagnose_excluded``: la función
  devuelve un ``dict`` JSON-compatible con métricas, nunca estimadores. No importa ``joblib`` ni
  ``noshow.train.save``; ``save`` además rechaza cualquier bundle con modelos o columnas que no
  sean de producción (``assert_production_bundle``).
- No cambia ``MODEL_FEATURES``, ``FORBIDDEN_FEATURES`` ni el bundle persistido.
- El programador y la simulación no importan este módulo (``used_by_scheduler: false``).
- Nunca entran sexo, etnia, nacionalidad (prohibidas y ausentes en los datos) ni la verdad
  sintética (``noshow_frailty``, ``true_noshow_prob``), que solo se usa como referencia de
  evaluación igual que en ``train``.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
import polars as pl

from noshow.data import RunData, load_fairness_attributes, load_truth_for_evaluation
from noshow.features import GROUP, LABEL
from noshow.metrics import evaluate, group_calibration, paired_brier_bootstrap
from noshow.train import (
    TrainConfig,
    TrainOutput,
    build_candidates,
    fit_and_select,
    predict_noshow,
    prepare,
)

# Variables excluidas por equidad cuyo costo se mide. Están en ``FORBIDDEN_FEATURES`` y así
# siguen: este módulo no las habilita para producción.
DIAGNOSTIC_FEATURES: Final[tuple[str, ...]] = (
    "age_group",
    "insurance",
    "commune_code",
    "health_service_code",
)

# Nunca entran a una variante, ni siquiera de diagnóstico.
NEVER_DIAGNOSED: Final[frozenset[str]] = frozenset(
    {
        "sex",
        "gender",
        "ethnicity",
        "nationality",
        "noshow_frailty",
        "true_noshow_prob",
        "patient_id",
        "id",
        "entry_id",
        "run_id",
    }
)

VARIANTS: Final[dict[str, tuple[str, ...]]] = {
    **{f"plus_{name}": (name,) for name in DIAGNOSTIC_FEATURES},
    "plus_all_excluded": DIAGNOSTIC_FEATURES,
}

# ``HistGradientBoostingClassifier`` admite como máximo ``max_bins`` (255) categorías por
# variable; la comuna tiene más (338 en la corrida canónica). En las variantes que lo necesitan,
# el codificador ordinal agrupa las comunas menos frecuentes en una sola categoría. Las variables
# con 255 categorías o menos se codifican igual que en producción.
GB_MAX_CATEGORIES: Final = 255

FAIRNESS_DIMENSIONS: Final[tuple[str, ...]] = (
    "age_group",
    "insurance",
    "health_service_code",
    "commune_code",
)

PURPOSE: Final = (
    "Solo medición: costo en desempeño de no usar variables excluidas por equidad. Ningún "
    "modelo de diagnóstico se persiste ni lo usa el programador o la simulación; las variables "
    "siguen prohibidas en el modelo de producción."
)


def _check_variant(extra: tuple[str, ...]) -> None:
    """Falla si una variante pide algo fuera de ``DIAGNOSTIC_FEATURES`` o nunca permitido."""
    never = sorted(NEVER_DIAGNOSED.intersection(extra))
    if never:
        raise ValueError(f"variables nunca permitidas, ni en diagnóstico: {never}")
    unknown = sorted(set(extra) - set(DIAGNOSTIC_FEATURES))
    if unknown:
        raise ValueError(f"variables fuera del diagnóstico de excluidas: {unknown}")


def _with_attributes(frame: pl.DataFrame, attrs: pl.DataFrame) -> pl.DataFrame:
    """Agrega los atributos de equidad (como texto) por paciente, conservando el orden."""
    return frame.join(attrs, on=GROUP, how="left", maintain_order="left")


def _metrics(y: np.ndarray, p: np.ndarray, bins: int) -> dict[str, Any]:
    """Métricas de ``evaluate`` sin la curva de calibración (para un JSON compacto)."""
    return {k: v for k, v in evaluate(y, p, bins).items() if k != "calibration_curve"}


def _max_gaps(frame: pl.DataFrame, prob: str, min_n: int) -> dict[str, float | None]:
    """Máxima brecha absoluta (predicha - verdad) por dimensión de equidad, grupos n >= min_n."""
    out: dict[str, float | None] = {}
    for column in FAIRNESS_DIMENSIONS:
        rows = group_calibration(frame, column, prob, min_n, "true_noshow_prob")
        out[column] = max(abs(r["gap_vs_truth"]) for r in rows) if rows else None
    return out


def _age_gaps(frame: pl.DataFrame, prob: str, min_n: int) -> dict[str, float]:
    """Brecha (predicha - verdad) por grupo etario: muestra hacia dónde se movería el sesgo."""
    rows = group_calibration(frame, "age_group", prob, min_n, "true_noshow_prob")
    return {r["group"]: r["gap_vs_truth"] for r in rows}


def diagnose_excluded(run: RunData, config: TrainConfig, production: TrainOutput) -> dict[str, Any]:
    """Mide en prueba cuánto mejorarían AUC, Brier y ECE con las variables excluidas.

    ``production`` es la salida de ``train`` sobre la misma corrida y configuración: se
    verifica que el split y las columnas coincidan y su principal es la referencia. Devuelve
    solo números (JSON-compatible); los modelos de diagnóstico se descartan al terminar.
    """
    prep = prepare(run, config)
    bundle = production.bundle
    if [prep.categorical, prep.numeric] != [
        bundle["columns"]["categorical"],
        bundle["columns"]["numeric"],
    ]:
        raise ValueError("las columnas del diagnóstico no coinciden con las del modelo principal")
    if prep.split.test_start.isoformat() != bundle["split"]["test_start"]:
        raise ValueError("el split del diagnóstico no coincide con el del modelo principal")

    attrs = load_fairness_attributes(run.run_dir).with_columns(
        pl.col(c).cast(pl.String) for c in DIAGNOSTIC_FEATURES
    )
    train_frame = _with_attributes(prep.split.train, attrs)
    cal_frame = _with_attributes(prep.split.calibration, attrs)
    test_frame = _with_attributes(prep.split.test, attrs).join(
        load_truth_for_evaluation(run.run_dir), on="id", how="left", maintain_order="left"
    )
    y_tr = train_frame[LABEL].to_numpy().astype(np.int64)
    y_cal = cal_frame[LABEL].to_numpy().astype(np.int64)
    y_te = test_frame[LABEL].to_numpy().astype(np.int64)
    groups = test_frame[GROUP].to_numpy()

    p_ref = predict_noshow(bundle, prep.split.test)
    ref_metrics = _metrics(y_te, p_ref, config.ece_bins)
    if ref_metrics["brier"] != production.results["test_metrics"][bundle["primary"]]["brier"]:
        raise ValueError("la referencia del diagnóstico no reproduce el Brier del principal")
    oracle = production.results["oracle_reference"]["metrics"]
    oracle_brier = None if oracle is None else float(oracle["brier"])
    eval_frame = test_frame.with_columns(pl.Series("p_reference", p_ref))

    variants: dict[str, Any] = {}
    for name, extra in VARIANTS.items():
        _check_variant(extra)
        categorical = [*prep.categorical, *extra]
        numeric = list(prep.numeric)
        columns = categorical + numeric
        unfitted = build_candidates(categorical, numeric, config.seed)
        capped = [c for c in extra if train_frame[c].n_unique() > GB_MAX_CATEGORIES]
        if capped:
            unfitted["gradient_boosting"].set_params(pre__cat__max_categories=GB_MAX_CATEGORIES)
        fitted = fit_and_select(
            unfitted,
            train_frame.select(columns),
            y_tr,
            cal_frame.select(columns),
            y_cal,
            config,
        )
        X_te = test_frame.select(columns)
        by_candidate = {
            cand: np.asarray(m.predict_proba(X_te)[:, 1], dtype=np.float64)
            for cand, m in sorted(fitted.candidates.items())
        }
        p = by_candidate[fitted.primary]
        metrics = _metrics(y_te, p, config.ece_bins)
        cmp_ = paired_brier_bootstrap(y_te, p, p_ref, groups, config.n_boot, config.seed)
        cmp_["variant_better_brier"] = bool(cmp_["brier_difference"] < 0)
        # el IC 95 % excluye el 0, en cualquiera de los dos sentidos
        cmp_["significant_at_95"] = bool(cmp_["ci95_high"] < 0 or cmp_["ci95_low"] > 0)
        gap = None
        if oracle_brier is not None and ref_metrics["brier"] > oracle_brier:
            gap = round(
                (ref_metrics["brier"] - metrics["brier"]) / (ref_metrics["brier"] - oracle_brier),
                4,
            )
        frame = eval_frame.with_columns(pl.Series("p_variant", p))
        variants[name] = {
            "added_features": list(extra),
            "selected_candidate": fitted.primary,
            "calibration_method": fitted.method,
            "brier_calibration_set": fitted.selection,
            "gradient_boosting_max_categories": GB_MAX_CATEGORIES if capped else None,
            "test_metrics": metrics,
            # secundario, solo para explicar la selección: el titular es el candidato elegido
            "test_metrics_by_candidate": {
                cand: {
                    k: v
                    for k, v in _metrics(y_te, pc, config.ece_bins).items()
                    if k in ("auc", "brier", "ece", "mean_predicted")
                }
                for cand, pc in by_candidate.items()
            },
            "auc_difference": round(float(metrics["auc"] - ref_metrics["auc"]), 6),
            "ece_difference": round(float(metrics["ece"] - ref_metrics["ece"]), 6),
            "vs_primary": cmp_,
            "share_of_oracle_brier_gap_closed": gap,
            "fairness_max_abs_gap_vs_truth": _max_gaps(frame, "p_variant", config.fairness_min_n),
            "age_group_gap_vs_truth": _age_gaps(frame, "p_variant", config.fairness_min_n),
        }

    return {
        "purpose": PURPOSE,
        "used_by_scheduler": False,
        "persisted": False,
        "method": (
            "Cada variante agrega variables a las permitidas y repite el pipeline del principal: "
            "mismo split temporal, candidatos, hiperparámetros, regla de calibración, selección "
            "por Brier en calibración y semilla. Se reporta el candidato elegido de cada variante "
            "en el conjunto de prueba. vs_primary = Brier(variante) - Brier(principal) con IC 95 % "
            "por bootstrap de pacientes (negativo = la variante es mejor)."
        ),
        "never_included": sorted(NEVER_DIAGNOSED),
        "reference": {
            "model": bundle["primary"],
            "test_metrics": ref_metrics,
            "fairness_max_abs_gap_vs_truth": _max_gaps(
                eval_frame, "p_reference", config.fairness_min_n
            ),
            "age_group_gap_vs_truth": _age_gaps(eval_frame, "p_reference", config.fairness_min_n),
        },
        "oracle_reference": None
        if oracle is None
        else {k: oracle[k] for k in ("auc", "brier", "ece", "log_loss")},
        "variants": variants,
    }
