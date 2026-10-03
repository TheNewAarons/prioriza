"""Catálogo de los 29 Servicios de Salud del SNSS y resolución de nombres.

Los códigos son los del DEIS (catálogo de establecimientos de datos.gob.cl). Las Glosas
06 escriben los nombres de forma distinta entre trimestres (mayúsculas, guiones, tildes,
abreviaturas como ``M. Norte`` o ``Valparaíso-SA``); :func:`resolve_health_service` los
unifica.
"""

import re
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

HEALTH_SERVICES: Mapping[int, str] = MappingProxyType(
    {
        1: "Arica y Parinacota",
        2: "Iquique",
        3: "Antofagasta",
        4: "Atacama",
        5: "Coquimbo",
        6: "Valparaíso San Antonio",
        7: "Viña del Mar Quillota",
        8: "Aconcagua",
        9: "Metropolitano Norte",
        10: "Metropolitano Occidente",
        11: "Metropolitano Central",
        12: "Metropolitano Oriente",
        13: "Metropolitano Sur",
        14: "Metropolitano Sur Oriente",
        15: "O'Higgins",
        16: "Maule",
        17: "Ñuble",
        18: "Concepción",
        19: "Talcahuano",
        20: "Biobío",
        21: "Araucanía Sur",
        22: "Los Ríos",
        23: "Osorno",
        24: "Reloncaví",
        25: "Aysén",
        26: "Magallanes",
        28: "Arauco",
        29: "Araucanía Norte",
        33: "Chiloé",
    }
)

#: Nombre usado para filas sin servicio asignable ("SERVICIO DE SALUD N/A").
UNASSIGNED_NAME = "NO INFORMADO"
#: Nombre de la fila especial "Hospital Digital" (sin código de servicio).
HOSPITAL_DIGITAL_NAME = "HOSPITAL DIGITAL"
#: Nombres permitidos con código ``None``.
SPECIAL_HEALTH_SERVICE_NAMES: frozenset[str] = frozenset({UNASSIGNED_NAME, HOSPITAL_DIGITAL_NAME})


class UnknownHealthServiceError(ValueError):
    """El nombre no corresponde a ningún Servicio de Salud conocido."""


def _normalize(raw: str) -> str:
    """Normaliza un nombre: sin tildes, mayúsculas, sin comillas y con espacios colapsados."""
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    for ch in ("'", "\u2019", "`", "?"):
        text = text.replace(ch, "")
    text = re.sub("[-\u2013\u2014]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(SERVICIO DE SALUD|S\.\s?S\.)\s+", "", text)
    text = re.sub(r"^DEL\s+", "", text)
    text = re.sub(r"^M\.\s*", "METROPOLITANO ", text)
    text = re.sub(r"\bSUR\s*ORIENTE\b", "SUR ORIENTE", text)
    return re.sub(r"\s+", " ", text).strip()


_BY_NORMALIZED: dict[str, int] = {_normalize(name): code for code, name in HEALTH_SERVICES.items()}
_ALIASES: dict[str, int] = {
    "VALPARAISO SA": 6,
    "VINA DEL MAR Q": 7,
    "LOS RIOS": 22,
    "TARAPACA": 2,
}
_SPECIAL: dict[str, str] = {
    "HOSPITAL DIGITAL": UNASSIGNED_NAME,
    "N/A": UNASSIGNED_NAME,
}


def resolve_health_service(raw: str) -> tuple[int | None, str]:
    """Resuelve un nombre de servicio a ``(código, nombre canónico)``.

    ``HOSPITAL DIGITAL`` y ``N/A`` (con o sin el prefijo "Servicio de Salud") devuelven
    ``(None, "NO INFORMADO")``. Lanza :class:`UnknownHealthServiceError` si no hay
    coincidencia.
    """
    key = _normalize(raw)
    if key in _SPECIAL:
        return None, _SPECIAL[key]
    code = _BY_NORMALIZED.get(key, _ALIASES.get(key))
    if code is None:
        raise UnknownHealthServiceError(f"Servicio de Salud desconocido: {raw!r}")
    return code, HEALTH_SERVICES[code]
