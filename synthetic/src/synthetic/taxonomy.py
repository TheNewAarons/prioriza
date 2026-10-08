"""Códigos de especialidad y constantes de taxonomía compartidas por el generador."""

import re
import unicodedata

from shared.schemas import CareSubtype, CareType

# Grupos de especialidad: cada uno tiene su propia taxonomía (CNE médica, CNE dental, IQ).
GROUP_CNE_MEDICAL = "cne_medical"
GROUP_CNE_DENTAL = "cne_dental"
GROUP_IQ = "iq"

GROUP_TO_CARE: dict[str, tuple[CareType, CareSubtype | None]] = {
    GROUP_CNE_MEDICAL: (CareType.CONSULTATION, CareSubtype.MEDICAL),
    GROUP_CNE_DENTAL: (CareType.CONSULTATION, CareSubtype.DENTAL),
    GROUP_IQ: (CareType.SURGERY, None),
}

# Clases de entrada para el mix de edad y prioridad.
KIND_CNE = "cne"
KIND_IQ = "iq"
KIND_GES = "ges"

_PEDIATRIC_RE = re.compile(r"PEDIATR|INFANTIL|DEL NINO|ADOLESCENTE")


def slugify(text: str) -> str:
    """Convierte un nombre a un slug ASCII en minúscula separado por guiones bajos."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


def specialty_code(group: str, name: str) -> str:
    """Código de especialidad, p. ej. ``cne_medical:oftalmologia`` (máximo 80 caracteres)."""
    code = f"{group}:{slugify(name)}"
    if len(code) > 80:
        raise ValueError(f"código de especialidad demasiado largo: {code}")
    return code


def is_pediatric(name: str) -> bool:
    """Indica si el nombre de la especialidad corresponde a una clase pediátrica."""
    return _PEDIATRIC_RE.search(name.upper()) is not None
