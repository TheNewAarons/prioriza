"""Modelos candidatos: baseline por especialidad, regresión logística y gradient boosting.

Los dos modelos aprendidos son ``Pipeline`` de scikit-learn con su preprocesamiento, de modo que
el artefacto persistido recibe directamente la matriz de ``features.build_features``. Los
hiperparámetros son fijos (sin búsqueda) para no gastar el conjunto de calibración ni el de
prueba en ajustarlos.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import polars as pl
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, OrdinalEncoder, StandardScaler

CalibrationMethod = Literal["isotonic", "sigmoid"]
ISOTONIC_MIN_EVENTS = 1000


class SpecialtyRateBaseline(ClassifierMixin, BaseEstimator):
    """Tasa histórica de inasistencia por especialidad, contraída hacia la tasa global.

    ``rate_s = (no_show_s + m · global) / (n_s + m)``; especialidades no vistas reciben la tasa
    global. Con ``m`` pequeño equivale a la tasa empírica por especialidad.
    """

    def __init__(self, column: str = "specialty_code", smoothing: float = 20.0) -> None:
        self.column = column
        self.smoothing = smoothing

    def fit(self, X: pl.DataFrame, y: np.ndarray) -> SpecialtyRateBaseline:
        y = np.asarray(y, dtype=np.float64)
        self.classes_ = np.array([0, 1])
        self.global_rate_ = float(y.mean())
        stats = (
            pl.DataFrame({"key": X[self.column], "y": y})
            .group_by("key")
            .agg(pl.col("y").sum().alias("events"), pl.len().alias("n"))
        )
        m = self.smoothing
        self.rates_ = {
            str(k): (float(e) + m * self.global_rate_) / (float(n) + m)
            for k, e, n in stats.iter_rows()
        }
        return self

    def predict_proba(self, X: pl.DataFrame) -> np.ndarray:
        p = np.array(
            [self.rates_.get(str(k), self.global_rate_) for k in X[self.column].to_list()],
            dtype=np.float64,
        )
        return np.column_stack([1.0 - p, p])

    def predict(self, X: pl.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(np.int64)


def build_logistic(categorical: list[str], numeric: list[str], seed: int) -> Pipeline:
    """One-hot de categóricas y log1p + estandarización de numéricas, luego logística L2."""
    pre = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), categorical),
            (
                "num",
                make_pipeline(
                    SimpleImputer(strategy="median", keep_empty_features=True),
                    FunctionTransformer(np.log1p, feature_names_out="one-to-one"),
                    StandardScaler(),
                ),
                numeric,
            ),
        ]
    )
    clf = LogisticRegression(C=1.0, max_iter=2000, random_state=seed)
    return Pipeline([("pre", pre), ("clf", clf)])


def build_gradient_boosting(categorical: list[str], numeric: list[str], seed: int) -> Pipeline:
    """Codificación ordinal de categóricas (desconocidas como faltantes) y boosting por histogramas.

    Sin ``early_stopping``: usaría una validación aleatoria y rompería la disciplina temporal.
    """
    pre = ColumnTransformer(
        [
            (
                "cat",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=np.nan,
                    encoded_missing_value=np.nan,
                ),
                categorical,
            ),
            ("num", "passthrough", numeric),
        ]
    )
    clf = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        l2_regularization=1.0,
        categorical_features=list(range(len(categorical))),
        early_stopping=False,
        random_state=seed,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def choose_calibration_method(y_calibration: np.ndarray) -> CalibrationMethod:
    """Isotónica si la clase minoritaria tiene ``ISOTONIC_MIN_EVENTS`` casos o más; si no, sigmoide.

    La isotónica no supone forma paramétrica pero sobreajusta con pocos eventos; la sigmoide
    (Platt) es más estable con muestras chicas y corrige bien desvíos monótonos simples.
    """
    y = np.asarray(y_calibration)
    minority = int(min(y.sum(), len(y) - y.sum()))
    return "isotonic" if minority >= ISOTONIC_MIN_EVENTS else "sigmoid"


def calibrate(
    model: Any, X: pl.DataFrame, y: np.ndarray, method: CalibrationMethod
) -> CalibratedClassifierCV:
    """Ajusta solo el calibrador sobre el conjunto de calibración (el modelo queda congelado)."""
    return CalibratedClassifierCV(FrozenEstimator(model), method=method).fit(X, y)


def out_of_fold_calibrated(
    model: Any, X: pl.DataFrame, y: np.ndarray, method: CalibrationMethod, folds: int = 5
) -> np.ndarray:
    """Probabilidades calibradas fuera de pliegue en el conjunto de calibración.

    Sirven para elegir el modelo principal sin mirar el conjunto de prueba. Los pliegues son
    bloques contiguos en el tiempo (sin mezcla).
    """
    est = CalibratedClassifierCV(FrozenEstimator(model), method=method)
    proba = cross_val_predict(
        est, X, y, cv=KFold(n_splits=folds, shuffle=False), method="predict_proba"
    )
    return np.asarray(proba[:, 1], dtype=np.float64)
