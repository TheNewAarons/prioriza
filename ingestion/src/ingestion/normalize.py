"""Normalización de etiquetas y construcción de DataFrames de polars."""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from enum import Enum
from types import MappingProxyType

import polars as pl
from pydantic import BaseModel


def strip_accents(text: str) -> str:
    """Quita tildes y otras marcas diacríticas (NFKD)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold_text(text: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados (para comparar títulos y encabezados)."""
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def normalize_label(raw: str) -> str:
    """Normaliza una etiqueta: sin tildes, MAYÚSCULAS, guiones simples, espacios colapsados.

    Los asteriscos de nota al pie se eliminan. Los guiones tipográficos (rayas largas y
    medias) pasan a ``-``.
    """
    text = strip_accents(raw).upper().replace("*", "")
    text = re.sub("[\u2013\u2014]", "-", text)
    text = re.sub(r"\s*-\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip()


#: Variantes de nombre de especialidad vistas entre trimestres, ya normalizadas (clave) hacia
#: el nombre elegido como canónico (valor). Un nombre nuevo no es error: se reporta como
#: advertencia en la validación.
SPECIALTY_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "BUCO MAXILOFACIAL": "BUCOMAXILOFACIAL",
        "DENTO MAXILO FACIAL": "DENTOMAXILOFACIAL",
        "DENTO-MAXILO-FACIAL": "DENTOMAXILOFACIAL",
        "SOMATO PROTESIS": "SOMATOPROTESIS",
        "SOMATO-PROTESIS": "SOMATOPROTESIS",
        "ENF. TRASMISION SEXUAL": "ENFERMEDADES DE TRANSMISION SEXUAL",
        "ENF. TRANSMISION SEXUAL": "ENFERMEDADES DE TRANSMISION SEXUAL",
    }
)

_WORD_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "ADULTA": "ADULTO",
        "PEDIATRICA": "PEDIATRICO",
        "BUCO-MAXILOFACIAL": "BUCOMAXILOFACIAL",
    }
)
_WORD_PATTERN = re.compile(r"[A-Z]+(?:-[A-Z]+)*")


def normalize_specialty(raw: str) -> str:
    """Normaliza el nombre de una especialidad y aplica los alias conocidos."""
    label = normalize_label(raw)
    label = SPECIALTY_ALIASES.get(label, label)
    # Por límite de palabra, no por espacios: "(FISIATRIA ADULTA)" debe alcanzar a ADULTA.
    label = _WORD_PATTERN.sub(lambda match: _WORD_ALIASES.get(match[0], match[0]), label)
    for key, value in SPECIALTY_ALIASES.items():
        label = label.replace(key, value)
    return label


def to_frame(
    records: Sequence[BaseModel],
    schema: Mapping[str, pl.DataType],
    sort_by: Sequence[str],
) -> pl.DataFrame:
    """Convierte modelos pydantic a un DataFrame con el esquema explícito, ordenado.

    Los enums se escriben con su valor. Las columnas del esquema que el modelo no tenga
    producen un error (el esquema y el modelo deben tener las mismas claves).
    """
    rows = [
        {key: value.value if isinstance(value, Enum) else value for key, value in row.items()}
        for row in (record.model_dump(mode="python") for record in records)
    ]
    frame = pl.DataFrame(rows, schema=dict(schema))
    return frame.sort(list(sort_by), nulls_last=True)
