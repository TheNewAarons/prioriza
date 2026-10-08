"""Entrenamiento, calibración, evaluación y persistencia del modelo de inasistencias.

Flujo: features → split temporal → baseline, logística y boosting en entrenamiento → elección
del método de calibración y del modelo principal con el conjunto de calibración → métricas en
prueba (sin tocarlo antes) → ``results/noshow.json`` y artefacto ``joblib`` versionado.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import polars as pl
import sklearn
from shared.disclaimer import DISCLAIMER

from noshow import MODEL_FORMAT_VERSION
from noshow.data import (
    FEATURE_TABLES,
    RunData,
    load_fairness_attributes,
    load_run,
    load_truth_for_evaluation,
)
from noshow.features import (
    EXCLUDED_FEATURES,
    FORBIDDEN_FEATURES,
    GROUP,
    LABEL,
    build_features,
    model_columns,
    usable_optional,
)
from noshow.metrics import evaluate, group_calibration, paired_brier_bootstrap
from noshow.models import (
    SpecialtyRateBaseline,
    build_gradient_boosting,
    build_logistic,
    calibrate,
    choose_calibration_method,
    out_of_fold_calibrated,
)
from noshow.split import TemporalSplit, temporal_split

LEARNED_MODELS = ("logistic_regression", "gradient_boosting")
SYNTHETIC_CAVEAT = (
    "Con datos sintéticos, estas métricas validan el pipeline (que aprende la estructura que el "
    "generador puso), no el desempeño en pacientes reales."
)


@dataclass(frozen=True)
class TrainConfig:
    """Configuración de un entrenamiento (todo lo que, con los datos, fija el resultado)."""

    seed: int = 42
    test_days: int = 180
    calibration_days: int = 120
    baseline_smoothing: float = 20.0
    calibration_folds: int = 5
    ece_bins: int = 10
    n_boot: int = 1000
    fairness_min_n: int = 200

    def sha256(self) -> str:
        """Huella de la configuración (JSON canónico)."""
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TrainOutput:
    """Resultado del entrenamiento: informe JSON-compatible y artefacto a persistir."""

    results: dict[str, Any]
    bundle: dict[str, Any]


def _xy(frame: pl.DataFrame, columns: list[str]) -> tuple[pl.DataFrame, np.ndarray]:
    return frame.select(columns), frame[LABEL].to_numpy().astype(np.int64)


def _proba(model: Any, X: pl.DataFrame) -> np.ndarray:
    return np.asarray(model.predict_proba(X)[:, 1], dtype=np.float64)


def _logistic_coefficients(model: Any) -> list[dict[str, Any]]:
    names = model.named_steps["pre"].get_feature_names_out()
    coefs = model.named_steps["clf"].coef_[0]
    rows = sorted(zip(names, coefs, strict=True), key=lambda r: -abs(r[1]))
    return [{"feature": str(n), "coefficient": round(float(c), 6)} for n, c in rows]


def train(run: RunData, config: TrainConfig) -> TrainOutput:
    """Entrena y evalúa todos los modelos sobre una corrida ya cargada."""
    feats = build_features(run.appointment, run.catalog_specialty, run.waitlist_entry)
    split = temporal_split(feats, config.test_days, config.calibration_days)
    optional = usable_optional(split.train)
    categorical, numeric = model_columns(optional)
    constant = sorted(c for c in categorical + numeric if split.train[c].n_unique() <= 1)
    categorical = [c for c in categorical if c not in constant]
    numeric = [c for c in numeric if c not in constant]
    columns = categorical + numeric
    X_tr, y_tr = _xy(split.train, columns)
    X_cal, y_cal = _xy(split.calibration, columns)
    X_te, y_te = _xy(split.test, columns)

    baseline = SpecialtyRateBaseline(smoothing=config.baseline_smoothing).fit(X_tr, y_tr)
    raw = {
        "logistic_regression": build_logistic(categorical, numeric, config.seed).fit(X_tr, y_tr),
        "gradient_boosting": build_gradient_boosting(categorical, numeric, config.seed).fit(
            X_tr, y_tr
        ),
    }
    method = choose_calibration_method(y_cal)
    selection: dict[str, float] = {}
    calibrated: dict[str, Any] = {}
    for name, model in raw.items():
        oof = out_of_fold_calibrated(model, X_cal, y_cal, method, config.calibration_folds)
        selection[name] = round(float(np.mean((oof - y_cal) ** 2)), 6)
        calibrated[name] = calibrate(model, X_cal, y_cal, method)
    primary = min(LEARNED_MODELS, key=lambda n: (selection[n], n))

    preds = {"baseline_specialty_rate": _proba(baseline, X_te)}
    for name in LEARNED_MODELS:
        preds[f"{name}_uncalibrated"] = _proba(raw[name], X_te)
        preds[name] = _proba(calibrated[name], X_te)
    test_metrics = {k: evaluate(y_te, v, config.ece_bins) for k, v in preds.items()}

    truth = load_truth_for_evaluation(run.run_dir)
    test_eval = split.test.select("id", GROUP, LABEL).join(truth, on="id", how="left")
    p_true = test_eval["true_noshow_prob"].to_numpy()
    oracle = evaluate(y_te, p_true, config.ece_bins) if not np.isnan(p_true).any() else None

    groups = split.test[GROUP].to_numpy()
    comparison = paired_brier_bootstrap(
        y_te, preds[primary], preds["baseline_specialty_rate"], groups, config.n_boot, config.seed
    )
    beats = comparison["brier_difference"] < 0
    comparison["beats_baseline_brier"] = bool(beats)
    comparison["significant_at_95"] = bool(comparison["ci95_high"] < 0)

    fairness = _fairness(run, split, preds[primary], test_eval, config)
    data_version = run.data_version
    model_version = f"noshow-{config.sha256()[:8]}-{str(data_version['dataset_sha256'])[:8]}"
    feature_policy = {
        "categorical": categorical,
        "numeric": numeric,
        "optional_used": list(optional),
        "constant_in_train_dropped": constant,
        "forbidden": sorted(FORBIDDEN_FEATURES),
        "excluded": dict(sorted(EXCLUDED_FEATURES.items())),
        "feature_tables": sorted(FEATURE_TABLES),
        "history_rule": (
            "prior_attended y prior_no_show cuentan citas del mismo paciente con scheduled_start "
            "estrictamente anterior a la fecha de agendamiento (scheduled_start - lead_days)."
        ),
    }
    versions = {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "polars": pl.__version__,
        "numpy": np.__version__,
    }
    results: dict[str, Any] = {
        "disclaimer": DISCLAIMER,
        "caveat": SYNTHETIC_CAVEAT,
        "model_version": model_version,
        "model_format_version": MODEL_FORMAT_VERSION,
        "data_version": data_version,
        "config": asdict(config),
        "config_sha256": config.sha256(),
        "split": split.summary(),
        "features": feature_policy,
        "calibration": {
            "method": method,
            "rule": "isotonic si la clase minoritaria del conjunto de calibración tiene >= 1000 "
            "casos; si no, sigmoid",
            "calibration_events": int(y_cal.sum()),
        },
        "selection": {
            "criterion": "Brier fuera de pliegue (KFold contiguo) del modelo calibrado en el "
            "conjunto de calibración; el conjunto de prueba no participa",
            "brier_out_of_fold": selection,
            "primary": primary,
        },
        "test_metrics": test_metrics,
        "oracle_reference": {
            "description": "Probabilidad verdadera del generador (verdad sintética, solo "
            "evaluación): techo de lo alcanzable.",
            "metrics": oracle,
        },
        "primary_vs_baseline": comparison,
        "fairness": fairness,
        "logistic_coefficients": _logistic_coefficients(raw["logistic_regression"]),
        "versions": versions,
    }
    bundle = {
        "model_version": model_version,
        "model_format_version": MODEL_FORMAT_VERSION,
        "primary": primary,
        "models": {**calibrated, "baseline_specialty_rate": baseline},
        "columns": {"categorical": categorical, "numeric": numeric},
        "data_version": data_version,
        "config": asdict(config),
        "split": {
            "calibration_start": split.calibration_start.isoformat(),
            "test_start": split.test_start.isoformat(),
        },
        "calibration_method": method,
        "versions": versions,
    }
    return TrainOutput(results=results, bundle=bundle)


def _fairness(
    run: RunData,
    split: TemporalSplit,
    p_primary: np.ndarray,
    test_eval: pl.DataFrame,
    config: TrainConfig,
) -> dict[str, Any]:
    """Calibración por grupo del modelo principal en prueba (atributos no usados por el modelo)."""
    attrs = load_fairness_attributes(run.run_dir)
    frame = (
        split.test.select("id", GROUP, LABEL, "care_type")
        .with_columns(pl.Series("p", p_primary))
        .join(test_eval.select("id", "true_noshow_prob"), on="id", how="left")
        .join(attrs, on=GROUP, how="left")
    )
    out: dict[str, Any] = {
        "description": "Probabilidad media predicha por el modelo principal frente a la tasa "
        "observada y a la probabilidad verdadera media, por grupo, en el conjunto de prueba. "
        "Las variables de grupo no entran al modelo.",
        "min_n": config.fairness_min_n,
    }
    for column in ("age_group", "insurance", "care_type", "health_service_code", "commune_code"):
        rows = group_calibration(frame, column, "p", config.fairness_min_n, "true_noshow_prob")
        entry: dict[str, Any] = {"groups": rows}
        if rows:
            entry["max_abs_gap_vs_truth"] = max(abs(r["gap_vs_truth"]) for r in rows)
        if column == "commune_code":
            entry["n_groups_total"] = int(frame[column].n_unique())
            entry["note"] = (
                "En el sintético la comuna no tiene efecto propio (solo vía servicio), así que "
                "este análisis no puede detectar daño por comuna aunque exista en la realidad."
            )
        out[column] = entry
    return out


def save(output: TrainOutput, models_dir: Path, results_path: Path) -> Path:
    """Escribe el artefacto ``joblib`` y su ``metadata.json`` y el informe ``results``."""
    run_id = str(output.bundle["data_version"]["run_id"])
    target = models_dir / run_id
    target.mkdir(parents=True, exist_ok=True)
    artifact = target / "noshow_model.joblib"
    joblib.dump(output.bundle, artifact)
    metadata = {k: v for k, v in output.bundle.items() if k != "models"}
    metadata["disclaimer"] = DISCLAIMER
    (target / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(output.results, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifact


def load_bundle(path: Path) -> dict[str, Any]:
    """Carga un artefacto propio (``joblib`` usa pickle: no cargar archivos de origen ajeno)."""
    bundle: dict[str, Any] = joblib.load(path)
    if bundle.get("model_format_version") != MODEL_FORMAT_VERSION:
        raise ValueError(
            f"formato de modelo {bundle.get('model_format_version')!r} incompatible con "
            f"{MODEL_FORMAT_VERSION!r}; reentrena con `prioriza-noshow train`"
        )
    return bundle


def predict_noshow(bundle: dict[str, Any], features: pl.DataFrame) -> np.ndarray:
    """Probabilidad calibrada de inasistencia del modelo principal (filas de ``build_features``)."""
    cols = bundle["columns"]["categorical"] + bundle["columns"]["numeric"]
    return _proba(bundle["models"][bundle["primary"]], features.select(cols))


def train_from_dir(run_dir: Path, config: TrainConfig) -> TrainOutput:
    """Atajo: carga la corrida y entrena."""
    return train(load_run(run_dir), config)
