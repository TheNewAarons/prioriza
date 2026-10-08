"""Reglas de priorización: modelos validados y carga desde YAML.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Las reglas son datos explícitos y auditables. Solo se admiten tres campos de entrada
(``ALLOWED_FIELDS``); cualquier atributo protegido o proxy (``PROHIBITED_FIELDS``) se rechaza
al cargar con un mensaje que explica el motivo.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Final, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from shared.db.enums import ClinicalPriority

SUPPORTED_SCHEMA_VERSIONS: Final = frozenset({1})
ALLOWED_FIELDS: Final = frozenset({"clinical_priority", "wait_days", "days_to_ges_deadline"})
PROHIBITED_FIELDS: Final[Mapping[str, str]] = {
    "sex": "atributo protegido",
    "gender": "atributo protegido",
    "ethnicity": "atributo protegido",
    "nationality": "atributo protegido",
    "commune_code": "proxy territorial/socioeconómico",
    "insurance": "proxy de ingreso",
    "age_group": "atributo protegido; lo clínico va en la prioridad declarada",
    "health_service_code": "proxy territorial; define la cola, no el orden",
    "establishment_code": "proxy territorial; define la cola, no el orden",
    "specialty_code": "proxy de sexo/edad (p. ej. ginecología, próstata)",
    "procedure_code": "proxy de sexo/edad (p. ej. ginecología, próstata)",
    "ges_problem_code": "proxy de sexo/edad (p. ej. ginecología, próstata)",
    "predicted_noshow_prob": "la inasistencia no puede bajar la prioridad",
    "noshow_frailty": "verdad sintética",
    "true_noshow_prob": "verdad sintética",
    "patient_id": "identificador",
}


class RulesError(ValueError):
    """Error de carga o validación de reglas; el mensaje está en español e incluye la ruta."""


class _Frozen(BaseModel):
    """Base de los modelos de reglas: inmutables y sin claves extra."""

    model_config = ConfigDict(frozen=True, extra="forbid")


_Unit = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
_MAX_WEIGHT: Final = 1000

# Términos que no pueden aparecer en una etiqueta: la explicación no puede insinuar que se usó
# un atributo protegido o un proxy (se compara sin mayúsculas ni tildes, por palabra).
PROHIBITED_LABEL_TERMS: Final = (
    "comuna",
    "prevision",
    "fonasa",
    "isapre",
    "edad",
    "sexo",
    "genero",
    "etnia",
    "nacionalidad",
    "migrante",
    "migrant",
    "commune",
    "insurance",
    "age",
    "sex",
    "gender",
    "ethnicity",
    "nationality",
)
_LABEL_RE: Final = re.compile(r"(?<!\w)(?:" + "|".join(PROHIBITED_LABEL_TERMS) + r")(?:e?s)?(?!\w)")


def _fold(text: str) -> str:
    """Minúsculas y sin tildes (NFKD sin marcas combinantes)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _check_label(label: str) -> str:
    match = _LABEL_RE.search(_fold(label))
    if match:
        raise ValueError(
            f"la etiqueta {label!r} menciona '{match.group(0)}', un atributo protegido o proxy "
            "que las reglas no pueden usar"
        )
    return label


_Label = Annotated[str, AfterValidator(_check_label)]


class LinearSaturated(_Frozen):
    """Espera lineal que satura en ``saturation_days``."""

    type: Literal["linear_saturated"]
    saturation_days: int = Field(strict=True, ge=1, le=3650)


class LogSaturated(_Frozen):
    """Espera logarítmica (``log1p``) que satura en ``saturation_days``."""

    type: Literal["log_saturated"]
    saturation_days: int = Field(strict=True, ge=1, le=3650)


class Step(_Frozen):
    """Un escalón: desde ``at_days`` días de espera el valor es ``value``."""

    at_days: int = Field(strict=True, ge=0)
    value: _Unit


class Steps(_Frozen):
    """Escalones sobre los días de espera."""

    type: Literal["steps"]
    steps: list[Step]

    @model_validator(mode="after")
    def _check_steps(self) -> "Steps":
        if not self.steps:
            raise ValueError("steps debe tener al menos un escalón")
        if self.steps[0].at_days != 0:
            raise ValueError("steps: el primer escalón debe tener at_days: 0")
        for prev, cur in zip(self.steps, self.steps[1:], strict=False):
            if cur.at_days <= prev.at_days:
                raise ValueError("los at_days de steps deben ser estrictamente crecientes")
            if cur.value < prev.value:
                raise ValueError("los value de steps no pueden decrecer")
        return self


class RampDown(_Frozen):
    """Rampa descendente sobre los días al plazo GES: 0 si d >= start, 1 si d <= end."""

    type: Literal["ramp_down"]
    start_days: int = Field(strict=True, ge=-365, le=365)
    end_days: int = Field(strict=True, ge=-365, le=365)

    @model_validator(mode="after")
    def _check_order(self) -> "RampDown":
        if self.start_days <= self.end_days:
            raise ValueError("start_days debe ser mayor que end_days")
        return self


WaitTransform = Annotated[LinearSaturated | LogSaturated | Steps, Field(discriminator="type")]


class ClinicalPriorityComponent(_Frozen):
    """Componente de prioridad clínica declarada (dato de entrada, nunca inferido)."""

    field: Literal["clinical_priority"]
    label: _Label
    weight: float = Field(strict=True, gt=0, le=_MAX_WEIGHT, allow_inf_nan=False)
    mapping: dict[ClinicalPriority, _Unit]

    @model_validator(mode="after")
    def _check_mapping(self) -> "ClinicalPriorityComponent":
        if set(self.mapping) != set(ClinicalPriority):
            raise ValueError("mapping debe tener exactamente las claves p1, p2, p3 y p4")
        m = self.mapping
        p1, p2, p3, p4 = (m[ClinicalPriority(k)] for k in ("p1", "p2", "p3", "p4"))
        if not p1 >= p2 >= p3 >= p4:
            raise ValueError("mapping debe ser monótono: p1 >= p2 >= p3 >= p4")
        if not p1 > p4:
            raise ValueError("mapping debe distinguir niveles: p1 debe ser mayor que p4")
        return self


class WaitDaysComponent(_Frozen):
    """Componente de días de espera."""

    field: Literal["wait_days"]
    label: _Label
    weight: float = Field(strict=True, ge=0, le=_MAX_WEIGHT, allow_inf_nan=False)
    transform: WaitTransform


class GesDeadlineComponent(_Frozen):
    """Componente de cercanía al plazo GES (suave; 0 si la entrada no es GES)."""

    field: Literal["days_to_ges_deadline"]
    label: _Label
    weight: float = Field(strict=True, ge=0, le=_MAX_WEIGHT, allow_inf_nan=False)
    transform: RampDown


Component = Annotated[
    ClinicalPriorityComponent | WaitDaysComponent | GesDeadlineComponent,
    Field(discriminator="field"),
]


class GesStrictRule(_Frozen):
    """Restricción dura GES: vencidas y por vencer van antes que el resto."""

    enabled: bool = Field(strict=True)
    due_soon_days: int = Field(strict=True, ge=0, le=180)
    order_within: Literal["deadline", "score"] = "deadline"
    yield_to_priorities: list[ClinicalPriority] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_yield(self) -> "GesStrictRule":
        if len(set(self.yield_to_priorities)) != len(self.yield_to_priorities):
            raise ValueError("yield_to_priorities no puede tener valores duplicados")
        order = [ClinicalPriority("p1"), ClinicalPriority("p2"), ClinicalPriority("p3")]
        order.append(ClinicalPriority("p4"))
        if self.yield_to_priorities != order[: len(self.yield_to_priorities)]:
            raise ValueError(
                "yield_to_priorities debe ser vacío o un prefijo contiguo de p1, p2, p3, p4 "
                "([p1], [p1, p2], ...): no puede anteponer una prioridad clínica a otra mejor"
            )
        if not self.enabled and self.yield_to_priorities:
            raise ValueError(
                "yield_to_priorities: la cesión solo aplica con la regla GES activa; "
                "deja la lista vacía"
            )
        return self


class RuleSet(_Frozen):
    """Conjunto completo de reglas de priorización."""

    schema_version: int = Field(strict=True)
    rules_id: str
    rules_version: str
    description: str
    components: tuple[Component, ...]
    ges_strict: GesStrictRule

    @model_validator(mode="before")
    @classmethod
    def _check_raw(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        version = data.get("schema_version")
        if version is not None and (
            isinstance(version, bool) or version not in SUPPORTED_SCHEMA_VERSIONS
        ):
            raise ValueError(
                f"schema_version: versión {version!r} no soportada; "
                f"soportadas: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        comps = data.get("components")
        if isinstance(comps, (list, tuple)):
            for i, comp in enumerate(comps):
                name = comp.get("field") if isinstance(comp, dict) else None
                if not isinstance(name, str) or name in ALLOWED_FIELDS:
                    continue
                if name in PROHIBITED_FIELDS:
                    raise ValueError(
                        f"components.{i}.field: el campo '{name}' está prohibido "
                        f"({PROHIBITED_FIELDS[name]})"
                    )
                raise ValueError(
                    f"components.{i}.field: campo desconocido '{name}'; "
                    f"campos permitidos: {sorted(ALLOWED_FIELDS)}"
                )
        return data

    @model_validator(mode="after")
    def _check_components(self) -> "RuleSet":
        names = [c.field for c in self.components]
        dups = sorted({n for n in names if names.count(n) > 1})
        if dups:
            raise ValueError(f"components: campo duplicado en componentes: {dups}")
        if names.count("clinical_priority") != 1:
            raise ValueError("components: debe haber exactamente un componente clinical_priority")
        if self.ges_strict.enabled:
            for i, c in enumerate(self.components):
                if (
                    isinstance(c, GesDeadlineComponent)
                    and c.transform.start_days < self.ges_strict.due_soon_days
                ):
                    raise ValueError(
                        f"components.{i}.transform.start_days: la rampa debe empezar antes del "
                        f"umbral por vencer (start_days >= due_soon_days = "
                        f"{self.ges_strict.due_soon_days})"
                    )
        return self

    @cached_property
    def _digest(self) -> str:
        canon = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def digest(self) -> str:
        """SHA-256 del JSON canónico (claves ordenadas) de las reglas."""
        return self._digest


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader que rechaza claves duplicadas (PyYAML las sobrescribe en silencio)."""

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node | None:
        event = self.peek_event()  # type: ignore[no-untyped-call]
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None:
            raise yaml.composer.ComposerError(
                None,
                None,
                "no se permiten anclas ni alias (&, *) en las reglas",
                event.start_mark,
            )
        return super().compose_node(parent, index)  # type: ignore[arg-type]

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    "no se permiten merge keys (<<) en las reglas",
                    key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=True)
            if isinstance(key, (str, int, float, bool)) and key in seen:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"clave duplicada '{key}'",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_TRANSFORM_TAGS: Final = frozenset({"linear_saturated", "log_saturated", "steps", "ramp_down"})


def _loc(loc: tuple[int | str, ...]) -> str:
    """Ruta legible: omite las etiquetas de uniones discriminadas (tipo de componente/transform)."""
    parts: list[str] = []
    for i, p in enumerate(loc):
        prev = loc[i - 1] if i else None
        if isinstance(p, str) and isinstance(prev, int) and p in ALLOWED_FIELDS:
            continue
        if prev == "transform" and p in _TRANSFORM_TAGS:
            continue
        parts.append(str(p))
    return ".".join(parts)


def _translate(err: Mapping[str, Any]) -> str:
    kind = err["type"]
    ctx = err.get("ctx") or {}
    if kind == "extra_forbidden":
        return "campo no permitido"
    if kind == "missing":
        return "falta el campo obligatorio"
    if kind == "greater_than_equal":
        return f"debe ser mayor o igual que {ctx.get('ge')}"
    if kind == "greater_than":
        return f"debe ser mayor que {ctx.get('gt')}"
    if kind == "less_than_equal":
        return f"debe ser menor o igual que {ctx.get('le')}"
    if kind == "less_than":
        return f"debe ser menor que {ctx.get('lt')}"
    if kind in ("float_type", "int_type", "bool_type"):
        return "tipo no válido; debe ser un número (no booleano ni texto)"
    if kind == "finite_number":
        return "debe ser un número finito (sin NaN ni infinito)"
    if kind == "literal_error":
        return f"valor no válido; permitidos: {ctx.get('expected')}"
    if kind == "enum":
        return f"valor no válido; permitidos: {ctx.get('expected')}"
    if kind == "union_tag_invalid":
        return f"tipo no válido '{ctx.get('tag')}'; permitidos: {ctx.get('expected_tags')}"
    if kind == "union_tag_not_found":
        return f"falta la clave discriminadora '{ctx.get('discriminator')}'"
    if kind == "value_error":
        return str(err["msg"]).removeprefix("Value error, ")
    return str(err["msg"])


def _format_errors(exc: ValidationError, source: str) -> str:
    lines = []
    for err in exc.errors(include_url=False):
        msg = _translate(err)
        path = _loc(err["loc"])
        # Los validadores "before" ya incluyen la ruta en su mensaje.
        lines.append(f"{source}: {path}: {msg}" if path else f"{source}: {msg}")
    return "reglas inválidas:\n" + "\n".join(lines)


def parse_rules(text: str, *, source: str = "<texto>") -> RuleSet:
    """Parsea y valida reglas desde texto YAML; lanza ``RulesError`` en español."""
    try:
        raw = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise RulesError(f"{source}: YAML inválido: {exc}") from exc
    if not isinstance(raw, dict):
        raise RulesError(f"{source}: la raíz del YAML debe ser un mapeo")
    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RulesError(_format_errors(exc, source)) from exc


def load_rules(path: Path) -> RuleSet:
    """Carga reglas desde un archivo YAML."""
    return parse_rules(path.read_text(encoding="utf-8"), source=str(path))


def load_default_rules() -> RuleSet:
    """Carga las reglas por defecto incluidas en el paquete."""
    text = resources.files("priority").joinpath("default_rules.yaml").read_text(encoding="utf-8")
    return parse_rules(text, source="default_rules.yaml")
