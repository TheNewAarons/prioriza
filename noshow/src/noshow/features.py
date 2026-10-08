"""Política de variables y construcción de la matriz de features del modelo de inasistencias.

La política es explícita y cerrada: solo entran al modelo las columnas de ``MODEL_FEATURES``.
Las variables descartadas tienen su motivo en ``EXCLUDED_FEATURES`` y se publican en
``results/noshow.json``. Este módulo no lee la verdad sintética (``patient_latent``,
``appointment_truth``) ni atributos protegidos del paciente: recibe solo citas, entradas y el
catálogo de especialidades.
"""

from __future__ import annotations

from typing import Final

import polars as pl

LABEL: Final = "no_show"
TIMESTAMP: Final = "scheduled_start"
GROUP: Final = "patient_id"
LOCAL_TZ: Final = "America/Santiago"
AFTERNOON_FROM_HOUR: Final = 13

CATEGORICAL_FEATURES: Final[tuple[str, ...]] = (
    "specialty_code",
    "care_type",
    "weekday",
    "time_band",
)
NUMERIC_FEATURES: Final[tuple[str, ...]] = (
    "lead_days",
    "prior_attended",
    "prior_no_show",
)
# Permitidas, pero se usan solo si existen en los datos de entrenamiento (ver ``usable_optional``).
OPTIONAL_NUMERIC_FEATURES: Final[tuple[str, ...]] = ("wait_days",)

MODEL_FEATURES: Final[tuple[str, ...]] = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# Atributos protegidos, proxies evidentes, verdad sintética e identificadores: nunca entran.
FORBIDDEN_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "sex",
        "gender",
        "ethnicity",
        "nationality",
        "age_group",
        "insurance",
        "commune_code",
        "health_service_code",
        "establishment_code",
        "noshow_frailty",
        "true_noshow_prob",
        "patient_id",
        "id",
        "entry_id",
        "run_id",
    }
)

EXCLUDED_FEATURES: Final[dict[str, str]] = {
    "sex": "Atributo protegido (CLAUDE.md). No existe en los datos sintéticos.",
    "ethnicity": "Atributo protegido (CLAUDE.md). No existe en los datos sintéticos.",
    "nationality": "Atributo protegido (CLAUDE.md). No existe en los datos sintéticos.",
    "age_group": (
        "No está en la lista de variables permitidas. Aunque el generador la usa, incluirla "
        "concentraría el sobreagendamiento en 15-44 años (hallazgo M3 de la revisión del "
        "generador). Se usa solo para medir equidad."
    ),
    "insurance": (
        "Previsión: proxy evidente de nivel socioeconómico. Se usa solo para medir equidad."
    ),
    "commune_code": (
        "Proxy geográfico de nivel socioeconómico, etnia y nacionalidad. Se usa solo para medir "
        "equidad."
    ),
    "health_service_code": (
        "Determinado por la comuna (V de Cramér = 1 en el sintético): mismo proxy geográfico. "
        "Costo: el modelo no ve que Arica e Iquique tienen tasas más altas."
    ),
    "distance_km": (
        "Permitida si existe, pero no hay coordenadas ni establecimiento en las citas del "
        "historial; usarla exigiría la comuna del paciente, que es un proxy excluido."
    ),
    "wait_days": (
        "Permitida, pero las citas del historial no tienen entrada asociada (entry_id nulo) y el "
        "generador fija el término de espera en 0 (hallazgo A2). Se incluye automáticamente solo "
        "si tiene valores en el periodo de entrenamiento."
    ),
    "duration_min": (
        "En consultas vale siempre 20 min y en cirugías delata el procedimiento (hallazgo B2); "
        "redundante con la especialidad y con un sesgo asimétrico entre tipos de atención."
    ),
    "clinical_priority": (
        "No existe en el historial (sin entrada asociada). Además, el sistema no debe aprender "
        "de la prioridad clínica para decidir sobreagendamiento."
    ),
    "noshow_frailty": "Verdad sintética del generador: prohibida como variable.",
    "true_noshow_prob": "Verdad sintética del generador: prohibida como variable.",
}

OBSERVED_OUTCOMES: Final = ("attended", "no_show")


def build_features(
    appointments: pl.DataFrame,
    specialties: pl.DataFrame,
    entries: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Matriz de features, etiqueta y columnas de control (fecha y paciente) por cita.

    ``appointments`` necesita ``id``, ``patient_id``, ``status``, ``scheduled_start`` (UTC),
    ``lead_days`` y ``specialty_code``; ``specialties``, ``code`` y ``care_type``; ``entries``
    (opcional), ``id`` y ``entry_date``. Solo se devuelven citas con resultado observado.

    El historial previo cuenta solo citas cuyo resultado ya se conocía al momento de agendar
    (``scheduled_start`` anterior a ``scheduled_start - lead_days``, con desigualdad estricta),
    de modo que ninguna variable usa información posterior a la decisión.
    """
    appts = appointments.filter(pl.col("status").is_in(OBSERVED_OUTCOMES)).with_columns(
        pl.col(TIMESTAMP).dt.convert_time_zone("UTC"),
        pl.col("lead_days").cast(pl.Int64),
    )
    appts = appts.with_columns(
        (pl.col(TIMESTAMP) - pl.duration(days=pl.col("lead_days"))).alias("booked_at")
    )
    prior = _prior_history(appts)
    local = pl.col(TIMESTAMP).dt.convert_time_zone(LOCAL_TZ)
    care = specialties.select(
        pl.col("code").alias("specialty_code"), pl.col("care_type").cast(pl.String)
    )
    out = (
        appts.join(prior, on="id", how="left")
        .join(care, on="specialty_code", how="left")
        .with_columns(
            pl.col("prior_attended").fill_null(0),
            pl.col("prior_no_show").fill_null(0),
            local.dt.weekday().cast(pl.String).alias("weekday"),
            pl.when(local.dt.hour() >= AFTERNOON_FROM_HOUR)
            .then(pl.lit("afternoon"))
            .otherwise(pl.lit("morning"))
            .alias("time_band"),
            (pl.col("status") == "no_show").cast(pl.Int8).alias(LABEL),
        )
    )
    out = _with_wait_days(out, entries)
    cols = [
        "id",
        GROUP,
        TIMESTAMP,
        *CATEGORICAL_FEATURES,
        *NUMERIC_FEATURES,
        *OPTIONAL_NUMERIC_FEATURES,
        LABEL,
    ]
    return out.select(cols).with_columns(
        pl.col("lead_days").cast(pl.Float64),
        pl.col("prior_attended").cast(pl.Float64),
        pl.col("prior_no_show").cast(pl.Float64),
        pl.col("specialty_code").cast(pl.String),
        pl.col("care_type").cast(pl.String),
    )


def _prior_history(appts: pl.DataFrame) -> pl.DataFrame:
    """Conteo de asistencias e inasistencias del mismo paciente conocidas al agendar."""
    left = appts.select("id", GROUP, "booked_at")
    right = appts.select(
        pl.col(GROUP), pl.col(TIMESTAMP).alias("prev_start"), pl.col("status").alias("prev_status")
    )
    return (
        left.join(right, on=GROUP, how="inner")
        .filter(pl.col("prev_start") < pl.col("booked_at"))
        .group_by("id")
        .agg(
            (pl.col("prev_status") == "attended").sum().alias("prior_attended"),
            (pl.col("prev_status") == "no_show").sum().alias("prior_no_show"),
        )
    )


def _with_wait_days(appts: pl.DataFrame, entries: pl.DataFrame | None) -> pl.DataFrame:
    """Agrega ``wait_days``: días entre el ingreso a la lista y la cita, si hay entrada asociada."""
    if entries is None or "entry_id" not in appts.columns:
        return appts.with_columns(pl.lit(None, dtype=pl.Float64).alias("wait_days"))
    dates = entries.select(pl.col("id").alias("entry_id"), "entry_date")
    local_day = pl.col(TIMESTAMP).dt.convert_time_zone(LOCAL_TZ).dt.date()
    return (
        appts.join(dates, on="entry_id", how="left")
        .with_columns(
            (local_day - pl.col("entry_date")).dt.total_days().cast(pl.Float64).alias("wait_days")
        )
        .drop("entry_date")
    )


def usable_optional(train: pl.DataFrame) -> tuple[str, ...]:
    """Features opcionales con al menos un valor no nulo en entrenamiento."""
    return tuple(c for c in OPTIONAL_NUMERIC_FEATURES if train[c].null_count() < train.height)


def model_columns(optional: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Columnas categóricas y numéricas que entran al modelo; falla si alguna está prohibida."""
    categorical = list(CATEGORICAL_FEATURES)
    numeric = [*NUMERIC_FEATURES, *optional]
    leaked = FORBIDDEN_FEATURES.intersection(categorical + numeric)
    if leaked:
        raise ValueError(f"variables prohibidas en el modelo: {sorted(leaked)}")
    return categorical, numeric
