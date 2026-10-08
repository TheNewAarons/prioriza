# Plan de diseño: módulo `priority/` (P4)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Autor: architect (opus), 2026-10-08. Contrato para implementer, test-writer y docs-writer. Las decisiones del usuario están en la sección 8.

Diseñé el módulo a partir de CLAUDE.md, `enums.py`, `models.py`, `schemas.py`, el plan sintético (§1, §9, §10), `synthetic-data.md` y `decisions.md`. Para dimensionarlo usé la corrida canónica en Postgres (`32c9e349…`: 100.000 entradas, `as_of` 2025-09-30, todas `waiting`). No edité archivos.

**Datos que condicionan el diseño (población canónica):**
- **Espera:** mediana de unos 247 días, p90 de unos 690, p99 de unos 1.650 y máximo 3.650.
- **GES:** 6.555 entradas. 1.705 están vencidas, 1.038 vencen en 0 a 14 días y 2.081 en 0 a 30 días.
- **Plazos provisorios:** 30, 45, 60, 90 o 180 días.
- **Prioridad clínica:** la sintética es independiente de la espera (los p1 no GES tienen una mediana de 246 días). Es un artefacto del generador, no del módulo.

## 1. Fórmula del puntaje

Las variables se derivan con un `as_of` explícito:
- `wait_days = (as_of − entry_date).days`. Es un error si es menor que 0 (una entrada no puede tener fecha futura).
- `d = (ges_deadline − as_of).days`. Vale `None` si la entrada no es GES.

Cada componente `i` produce un valor `v_i ∈ [0,1]`. El puntaje total es:

`S = Σ_i (100 · w_i / Σ_j w_j) · v_i ∈ [0, 100]`

- Se suma con `math.fsum` en el orden del YAML.
- El resultado se guarda como `round(S, 6)`, y la comparación usa el entero `round(S·10⁶)`.
- Como los pesos se normalizan, cualquier peso válido produce un puntaje entre 0 y 100. Los pesos por defecto suman 100, así que en ese caso peso efectivo = peso.

| Componente | Transformación | Peso por defecto |
|---|---|---|
| `clinical_priority` | Escalones fijos: p1 = 1,0; p2 = 0,6; p3 = 0,25; p4 = 0,0 | 50 |
| `wait_days` | Lineal saturada: `min(wait_days, 730) / 730` | 35 |
| `days_to_ges_deadline` | Rampa descendente: `clip((60 − d) / 60, 0, 1)`. Vale 0 si d ≥ 60, 1 si d ≤ 0 y 0 si no es GES | 15 |

**Por qué estos valores:**
- **Espera lineal y no logarítmica.** Es más fácil de explicar: 1 punto cada 20,9 días. Tampoco favorece a quien acaba de entrar. Sobre los 730 días el puntaje empata, pero el desempate por `entry_date` mantiene el orden por espera, así que la monotonía se conserva.
- **Prioridad clínica no uniforme.** Las distancias entre niveles son 20, 17,5 y 12,5 puntos. Se eligieron para que se cumplan tres invariantes de la configuración por defecto, que se pueden testear:
  1. **I1.** La espera sola nunca hace que un p3 o p4 supere a un p1. Las distancias p1–p3 (37,5) y p1–p4 (50) son mayores que los 35 puntos máximos de espera.
  2. **I2.** Un nivel adyacente sí se puede superar con espera extra: p2 sobre p1 con 417 días más de espera, p3 sobre p2 con 365 días más, p4 sobre p3 con 261 días más. La espera compensa en parte la prioridad, pero no la anula.
  3. **I3.** El componente GES suave aporta como máximo 15 puntos, menos que cualquier salto de nivel salvo p3–p4. Pesa como un año de espera, no como una prioridad clínica.

**Nivel estricto GES** (es una restricción dura, no un peso). Con `ges_strict.enabled`:
- `GES_OVERDUE` si d < 0.
- `GES_DUE_SOON` si 0 ≤ d ≤ `due_soon_days` (14 por defecto). "Vence hoy" (d = 0) cuenta como por vencer.
- `NONE` en cualquier otro caso.

Con `enabled: false` todas las entradas quedan en `NONE` y el plazo GES solo influye a través de la rampa.

**Orden total** (clave ascendente, sin empates posibles porque `entry_id` es único):

```
( -tier,
  d          si tier > 0 y order_within == "deadline", si no 0,
  -round(S·1e6),
  entry_date.toordinal(),
  entry_id )
```

- Con `order_within: deadline` (por defecto), el orden dentro del nivel estricto es *earliest deadline first*: las más atrasadas primero, luego las que vencen antes, y después el puntaje. Esto deja las vencidas antes que las por vencer y minimiza el atraso máximo (regla de Jackson).
- Con `order_within: score`, el puntaje va antes que el plazo.
- Los desempates no son configurables, para garantizar que el orden sea total.

**Ejemplos** (`as_of` = 2025-09-30, pesos por defecto):

| Entrada | Datos | C | W | G | S |
|---|---|---|---|---|---|
| A | p1, 30 días, no GES | 50 | 1,44 | 0 | **51,44** |
| B | p2, 400 días, no GES | 30 | 19,18 | 0 | **49,18** |
| C | p4, 1.500 días (saturada), no GES | 0 | 35,00 | 0 | **35,00** |
| D | p3, 120 días, GES vencida hace 10 días | 12,5 | 5,75 | 15 | **33,25**, nivel `GES_OVERDUE` |
| E | p2, 20 días, GES vence en 25 días | 30 | 0,96 | 8,75 | **39,71**, nivel `NONE` (25 > 14) |

- Con la regla estricta activa el orden es D, A, B, E, C.
- Con la regla desactivada es A, B, E, C, D. La vencida queda última, y eso muestra por qué el requisito pide una restricción dura.
- A va antes que B porque la diferencia de espera (370 días) no alcanza los 417 que se necesitan.
- C nunca supera a A ni a B: la espera no anula la prioridad clínica.

## 2. Esquema YAML y modelos Pydantic

**`rules.py`.** Todos los modelos son `frozen=True, extra="forbid"` y no aceptan infinito ni NaN.

```python
SUPPORTED_SCHEMA_VERSIONS: Final = frozenset({1})
ALLOWED_FIELDS: Final = frozenset({"clinical_priority", "wait_days", "days_to_ges_deadline"})
PROHIBITED_FIELDS: Final[Mapping[str, str]] = {  # campo -> motivo (para el mensaje)
  "sex"|"gender": "atributo protegido", "ethnicity": "...", "nationality": "...",
  "commune_code": "proxy territorial/socioeconómico", "insurance": "proxy de ingreso",
  "age_group": "atributo protegido; lo clínico va en la prioridad declarada",
  "health_service_code"|"establishment_code": "proxy territorial; define la cola, no el orden",
  "specialty_code"|"procedure_code"|"ges_problem_code": "proxy de sexo/edad (p. ej. ginecología, próstata)",
  "predicted_noshow_prob": "la inasistencia no puede bajar la prioridad",
  "noshow_frailty"|"true_noshow_prob": "verdad sintética", "patient_id": "identificador",
}

class LinearSaturated(_Frozen): type: Literal["linear_saturated"]; saturation_days: int = Field(ge=1, le=3650)
class LogSaturated(_Frozen):    type: Literal["log_saturated"];    saturation_days: int = Field(ge=1, le=3650)
class Step(_Frozen):            at_days: int = Field(ge=0); value: float = Field(ge=0, le=1)
class Steps(_Frozen):           type: Literal["steps"]; steps: list[Step]  # at_days estrictamente crecientes, el primero en 0; values no decrecientes
class RampDown(_Frozen):        type: Literal["ramp_down"]; start_days: int = Field(ge=-365, le=365); end_days: int  # start > end
WaitTransform = Annotated[LinearSaturated | LogSaturated | Steps, Field(discriminator="type")]

class ClinicalPriorityComponent(_Frozen):
    field: Literal["clinical_priority"]; label: str; weight: float = Field(gt=0)
    mapping: dict[ClinicalPriority, float]  # 4 claves exactas, valores en [0,1], p1>=p2>=p3>=p4 y p1>p4
class WaitDaysComponent(_Frozen):
    field: Literal["wait_days"]; label: str; weight: float = Field(ge=0); transform: WaitTransform
class GesDeadlineComponent(_Frozen):
    field: Literal["days_to_ges_deadline"]; label: str; weight: float = Field(ge=0); transform: RampDown
Component = Annotated[ClinicalPriorityComponent | WaitDaysComponent | GesDeadlineComponent,
                      Field(discriminator="field")]

class GesStrictRule(_Frozen):
    enabled: bool; due_soon_days: int = Field(ge=0, le=180)
    order_within: Literal["deadline", "score"] = "deadline"

class RuleSet(_Frozen):
    schema_version: int; rules_id: str; rules_version: str; description: str
    components: tuple[Component, ...]; ges_strict: GesStrictRule
    # model_validator(mode="before"): schema_version soportada; components[*].field en la
    #   lista blanca (si está en PROHIBITED_FIELDS, error con el motivo; si es desconocido,
    #   error que muestra ALLOWED_FIELDS)
    # model_validator(mode="after"): exactamente un componente clinical_priority; campos
    #   sin duplicar; si ges_strict.enabled y existe un componente GES, entonces
    #   transform.start_days >= due_soon_days ("la rampa debe empezar antes del umbral por vencer")
    def digest(self) -> str: ...  # sha256 del JSON canónico (sort_keys); va a schedule_run.params

class RulesError(ValueError): ...  # mensaje en español con la ruta (components.1.weight: ...)
def parse_rules(text: str, *, source: str = "<texto>") -> RuleSet
def load_rules(path: Path) -> RuleSet
def load_default_rules() -> RuleSet          # importlib.resources
```

Cargador YAML:
- Usa una subclase de `yaml.SafeLoader` que **lanza error ante claves duplicadas**, porque PyYAML las sobrescribe en silencio.
- La raíz del YAML debe ser un mapeo.
- `RulesError` traduce al español los tipos de error comunes de Pydantic: `extra_forbidden`, `missing`, `greater_than_equal`, `literal_error`, `union_tag_invalid`.

**Contenido completo de `priority/src/priority/default_rules.yaml`:**

```yaml
# Reglas de priorización por defecto de Prioriza.
# Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
# gestión real sin validación institucional. Los pesos son una propuesta de ejemplo, no una
# norma validada por profesionales.
schema_version: 1
rules_id: prioriza-default
rules_version: "2026.10-1"
description: >
  Prioridad clínica declarada (50), días de espera lineal saturada en 730 días (35) y
  cercanía al plazo GES con rampa de 60 días (15). Las garantías GES vencidas o que vencen
  en 14 días o menos van primero (restricción dura), ordenadas por plazo.
components:
  - field: clinical_priority
    label: Prioridad clínica declarada
    weight: 50
    mapping: {p1: 1.0, p2: 0.6, p3: 0.25, p4: 0.0}
  - field: wait_days
    label: Días de espera
    weight: 35
    transform: {type: linear_saturated, saturation_days: 730}
  - field: days_to_ges_deadline
    label: Cercanía al plazo GES
    weight: 15
    transform: {type: ramp_down, start_days: 60, end_days: 0}
ges_strict:
  enabled: true
  due_soon_days: 14
  order_within: deadline
```

## 3. Interfaces (pensadas para `mypy --strict`)

**`priority/src/priority/inputs.py`** solo importa `shared.db.enums`, sin SQLAlchemy:

```python
@dataclass(frozen=True, slots=True)
class PriorityInput:
    entry_id: str
    clinical_priority: ClinicalPriority
    entry_date: date
    ges_deadline: date | None = None

    # __post_init__: ges_deadline >= entry_date; clinical_priority isinstance ClinicalPriority
    @property
    def is_ges(self) -> bool: ...
```

`PriorityInput` no tiene campos de comuna, previsión, edad ni servicio. Esa es la segunda barrera, porque aunque alguien se saltara la validación del YAML, el cálculo no tendría acceso a esos datos.

**`adapters.py`** importa los modelos ORM y polars:

```python
def from_waitlist_entry(e: WaitlistEntry) -> PriorityInput         # ValueError si status != WAITING
def inputs_from_frame(df: pl.DataFrame) -> list[PriorityInput]
    # df.select(["id","clinical_priority","entry_date","ges_deadline"]) y no lee otras columnas;
    # si existe la columna status, exige que todas valgan "waiting"; error si faltan columnas
def rank_frame(df: pl.DataFrame, rules: RuleSet, *, as_of: date,
               partition_by: Sequence[str] = ("health_service_code","specialty_code","care_type"),
               ) -> dict[tuple[object, ...], Ranking]
```

La partición define la cola en la que compite cada entrada; nunca cambia el puntaje. Por eso se permite usar el servicio de salud aquí.

**`score.py`:**

```python
class StrictTier(IntEnum): NONE = 0; GES_DUE_SOON = 1; GES_OVERDUE = 2

@dataclass(frozen=True, slots=True)
class ComponentContribution:
    field: str; label: str; raw_value: str | int | None; transform_desc: str
    normalized: float; weight: float; effective_weight: float; contribution: float

@dataclass(frozen=True, slots=True)
class PriorityScore:
    entry_id: str; as_of: date; clinical_priority: ClinicalPriority  # eco sin modificar
    wait_days: int; days_to_ges_deadline: int | None; tier: StrictTier
    score: float; components: tuple[ComponentContribution, ...]

def strict_tier(days_to_deadline: int | None, rule: GesStrictRule) -> StrictTier
def score_entry(inp: PriorityInput, rules: RuleSet, *, as_of: date) -> PriorityScore
def sort_key(s: PriorityScore, inp: PriorityInput, rules: RuleSet) -> tuple[int, int, int, int, str]

@dataclass(frozen=True, slots=True)
class RankedEntry: rank: int; score: PriorityScore          # rank empieza en 1

@dataclass(frozen=True, slots=True)
class Ranking:
    as_of: date; rules_id: str; rules_version: str; rules_digest: str
    entries: tuple[RankedEntry, ...]; disclaimer: str
    def get(self, entry_id: str) -> RankedEntry: ...

def rank(inputs: Iterable[PriorityInput], rules: RuleSet, *, as_of: date) -> Ranking
    # ValueError si hay entry_id duplicados
```

`as_of` es un argumento solo por nombre y sin valor por defecto en todas las funciones. Nunca se llama a `date.today()`.

**`explain.py`:**

```python
@dataclass(frozen=True, slots=True)
class Explanation:
    entry_id: str; rank: int | None; total: int | None; score: float
    tier: StrictTier; tier_reason: str | None; lines: tuple[str, ...]
    @property
    def text(self) -> str: ...
def explain(s: PriorityScore, rules: RuleSet, *, rank: int | None = None, total: int | None = None) -> Explanation
def explain_ranked(r: Ranking, entry_id: str, rules: RuleSet) -> Explanation
def explanation_to_dict(e: Explanation) -> dict[str, object]   # para la API
```

- Los números van con coma decimal (formato es-CL).
- El texto de explicación se genera solo cuando se pide. Así `rank()` no arma 100.000 textos.

**`DISCLAIMER`:** hoy está en `synthetic.io`. Propongo moverlo a `shared/src/shared/disclaimer.py`, dejando que `synthetic` lo re-exporte, para que `priority` no dependa de `synthetic`.

**Rendimiento:** la implementación es en Python puro y no hay una ruta vectorizada paralela, para evitar que dos implementaciones diverjan. Un prototipo que calcula puntaje, nivel y orden para 100.000 entradas tardó 0,14 s. Con las dataclasses de desglose estimo que el total queda por debajo de 1 s, dentro del presupuesto de 2 s.

## 4. Contrato de tests (test-writer, en paralelo con implementer)

**`test_rules.py`:**
- El YAML por defecto carga.
- Error claro en cada uno de estos casos (cada mensaje debe nombrar la ruta y el campo):
  - campo prohibido (`insurance`, `commune_code`, `age_group`, `health_service_code`, `specialty_code`, `predicted_noshow_prob`), con el motivo en el mensaje;
  - campo desconocido, mostrando la lista blanca;
  - peso negativo; peso NaN o infinito; peso 0 en la prioridad clínica;
  - mapeo incompleto o no monótono (p2 > p1, o p1 = p4);
  - `schema_version: 2`;
  - clave extra (`extra="forbid"`) y clave YAML duplicada;
  - rampa con `start_days` < `due_soon_days` estando la regla estricta activa; `start_days` ≤ `end_days`;
  - `steps` con umbrales no crecientes;
  - componente duplicado; sin componente clínico.
- `digest()` es estable ante el reordenamiento de claves.

**`test_score.py`:**
- Cada transformación en sus bordes: 0, 729, 730 y 3.650 días; d = 61, 60, 0, −1 y `None`.
- Nivel estricto en d = −1, 0, 14 y 15. Con la regla desactivada el nivel siempre es `NONE`.
- Los 5 ejemplos (A–E) como test dorado, con los puntajes de §1 (tolerancia 1e-6) y los dos órdenes, con la regla activa y desactivada.
- `entry_date > as_of` lanza `ValueError`.
- La firma de `rank` y `score_entry` no tiene valor por defecto para `as_of` (verificado con `inspect.signature`).
- `clinical_priority` de la salida es igual al de la entrada.

**`test_ranking.py`:**
- Desempates: con igual nivel y puntaje, gana la entrada más antigua; con igual fecha, gana el `entry_id` menor.
- Error por id duplicado.
- `order_within: score` frente a `deadline`.
- Los invariantes I1–I3 con los pesos por defecto.

**Propiedades con hypothesis (`test_properties.py`):**
- Las estrategias generan `PriorityInput` sintéticos con ids `uuid` generados, nunca datos reales.
- Las semillas son fijas con `derandomize=True` o con un perfil.

Propiedades:
1. Con todo lo demás igual, más días de espera nunca empeoran el puesto ni bajan el puntaje.
2. Con todo lo demás igual, mejor prioridad clínica nunca empeora el puesto.
3. Con la regla dura activa, ninguna GES en nivel estricto queda detrás de una entrada `NONE`, y toda `OVERDUE` va antes que toda `DUE_SOON`.
4. Con la regla desactivada existe un contraejemplo explícito (el caso D frente a C).
5. Invariancia al orden de entrada: el resultado de `rank` es idéntico para cualquier permutación de la lista.
6. Independencia de alternativas irrelevantes: agregar o quitar entradas no cambia el puntaje de las demás ni su orden relativo.
7. `0 ≤ S ≤ 100` para cualquier `RuleSet` válido generado.
8. `sum(contribution) == score` (tolerancia 1e-9).

**`test_adapters.py`:**
- `from_waitlist_entry` con un objeto ORM en memoria, sin base de datos.
- `inputs_from_frame` ignora columnas extra como `insurance` y `commune_code`, y falla si falta una columna o si hay `status` distinto de `waiting`.
- `rank_frame` particiona correctamente.

**`test_explain.py`:**
- El texto contiene la etiqueta, el valor de entrada, el peso y la contribución de cada componente.
- La razón del nivel estricto menciona el plazo y los días.
- El texto no menciona campos prohibidos.

**Rendimiento:** un test de 100.000 entradas con umbral holgado (menos de 5 s), sin red.

## 5. Contenido para `docs/priority.md` (docs-writer)

- Aviso obligatorio al inicio.
- Principios:
  - el sistema apoya, no decide;
  - la prioridad clínica es un dato de entrada y no se modifica;
  - no hay ML;
  - las reglas son auditables (`rules_digest`).
- La fórmula de §1 con la tabla de componentes, los invariantes I1–I3 y la tabla de equivalencias (cuántos días de espera equivalen a cada salto de nivel).
- La regla estricta GES: definiciones de vencida y por vencer, orden EDF, cómo desactivarla y el ejemplo D con la regla activa y desactivada.
- La lista blanca y la lista negra, con el motivo de cada campo prohibido. Aclarar que comuna, previsión, grupo etario y servicio se usan solo para *medir* equidad.
- El YAML por defecto comentado y cómo validar uno propio.
- Tres explicaciones de ejemplo:
  - **A (puesto 2 de 5):** "Puntaje 51,44/100. Prioridad clínica declarada: p1 → 1,00 × peso 50 = 50,00. Días de espera: 30 → lineal saturada en 730 días = 0,04 × 35 = 1,44. Cercanía al plazo GES: no aplica = 0,00. Nivel estricto: ninguno."
  - **D (puesto 1 de 5):** "Nivel estricto: garantía GES vencida (plazo 2025-09-20, 10 días de atraso). Por la regla `ges_strict` (activa) va antes que toda entrada sin nivel estricto. Puntaje 33,25/100: p3 → 12,50; 120 días → 5,75; plazo vencido → 15,00."
  - **C (puesto 5 de 5):** "Puntaje 35,00/100. Prioridad clínica declarada: p4 → 0,00. Días de espera: 1.500 → saturada (≥ 730) = 35,00. Más espera no aumenta el puntaje; frente a otra entrada saturada con igual puntaje, desempata la fecha de ingreso."
- Limitaciones:
  - los pesos son de ejemplo y no están validados clínicamente;
  - los plazos GES son provisorios (`verified: false`);
  - en la población sintética la prioridad es independiente de la espera.

## 6. Dependencias

- **`pyyaml>=6.0`** (en `priority`): es lo que pide el usuario; `safe_load` es el estándar, y ya está en `uv.lock` como dependencia transitiva (6.0.3).
- **`types-PyYAML`** (grupo dev): sin estos stubs, `mypy --strict` falla con `import-untyped`.
- **`polars`** se declara explícitamente en `priority`. Ya llega a través de `shared`, así que no entra nada nuevo al lock.
- Descarté `ruamel.yaml`: solo aportaría preservar comentarios, y basta con el `SafeLoader` contra claves duplicadas.
- Hay que registrar todo esto en `docs/decisions.md` §7.

## 7. Riesgos y decisiones abiertas

1. **Necesito tu decisión: ¿un p1 no GES va antes que una GES vencida?** Con la regla dura pura (la opción por defecto), una cataratas p4 vencida va antes que un p1 urgente no GES. Además, en colas donde la capacidad es menor que el stock de vencidas (1.705), los no GES pueden pasar semanas sin atenderse. Propongo la opción `ges_strict.yield_to_priorities: [p1]`, que agrega delante una clave `−(clinical_priority in yield_to)`. Por defecto la dejaría en `[]`. Pregunta: cuando dijiste "GES vencido nunca detrás de *no urgente*", ¿querías que los p1 sí puedan ir delante? Si es así, uso `[p1]` y la propiedad 3 se ajusta.
2. **Necesito tu decisión: orden dentro del nivel estricto y umbral.** Con EDF, una vencida p4 con 400 días de atraso va antes que un cáncer p1 con 2 días de atraso. La alternativa es `order_within: score`. Sobre el umbral: 14 días deja 1.038 entradas por vencer y 30 días deja 2.081, además de las 1.705 vencidas. Propongo EDF y 14 días porque siguen tu ejemplo.
3. **Proxy residual vía GES (informativo).** La longitud del plazo depende del problema de salud (próstata, cervicouterino y mama tienen 30 a 45 días), así que se correlaciona con el sexo. No se puede quitar sin ignorar la garantía legal. Como mitigación, el problema no es un factor y se reportan diferencias de puesto por grupo etario, comuna y previsión. El sexo no existe en los datos.
4. **Los pesos son normativos (informativo).** Los valores 50/35/15 y el mapeo p1..p4 son una propuesta mía, no una norma clínica. Se documentan como ejemplo y quedan versionados por `rules_version` y `digest`.

## Ejecución

1. **chore (haiku):** agregar `pyyaml` y `types-PyYAML` y mover `DISCLAIMER` a `shared`. En paralelo, **docs-writer (haiku):** escribir la entrada §7 de `decisions.md`.
2. **implementer (sonnet):** implementar `rules.py`, `inputs.py`, `score.py`, `explain.py`, `adapters.py` y `default_rules.yaml`. En paralelo, **test-writer (sonnet):** escribir los tests de §4 contra las firmas de §3.
3. **docs-writer (haiku):** escribir `docs/priority.md`, una vez que el test dorado A–E pase.
4. **reviewer (opus):** revisar el módulo antes del siguiente prompt.

Las decisiones 1 y 2 de §7 hay que resolverlas antes del paso 2. Por defecto, sin respuesta, uso `[]`, `deadline` y 14 días.

Archivos relevantes:
- `/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/pyproject.toml`
- `/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/__init__.py`
- `/Users/aarons/Documents/Projects/FullPy/Prioriza/shared/src/shared/db/models.py`
- `/Users/aarons/Documents/Projects/FullPy/Prioriza/shared/src/shared/db/enums.py`
- `/Users/aarons/Documents/Projects/FullPy/Prioriza/synthetic/src/synthetic/io.py`
- `/Users/aarons/Documents/Projects/FullPy/Prioriza/docs/decisions.md`
## 8. Decisiones del usuario (2026-10-08) — obligatorias

1. **p1 antes que GES vencidas:** `ges_strict.yield_to_priorities: [p1]` en el YAML por defecto. Semántica: se antepone a la clave de orden el término `-(clinical_priority ∈ yield_to_priorities)`. Resultado: primero todas las entradas p1 (y dentro de ellas, las GES vencidas, luego las por vencer, luego el resto, con el mismo orden de §1); después las GES vencidas y por vencer de p2–p4; después el resto. `yield_to_priorities` es una lista de `ClinicalPriority` sin duplicados (puede ser vacía) y queda en el `digest`. El puntaje no cambia.
2. **Orden dentro del nivel estricto y umbral:** `order_within: deadline` (EDF) y `due_soon_days: 14`, como en §1.

Ajustes al contrato de tests (§4):
- Propiedad 3: con la regla dura activa, ninguna GES de nivel estricto queda detrás de una entrada `NONE` **salvo que esa entrada tenga una prioridad en `yield_to_priorities`**; toda `OVERDUE` va antes que toda `DUE_SOON` dentro del mismo grupo de cesión.
- Nueva propiedad: con `yield_to_priorities: [p1]`, ninguna entrada p1 queda detrás de una entrada no p1.
- Test dorado A–E con el YAML por defecto: el orden pasa a ser **A, D, B, E, C** (A es p1). Con `yield_to_priorities: []`: D, A, B, E, C. Con la regla desactivada: A, B, E, C, D.
- YAML inválido: `yield_to_priorities` con duplicados o valores fuera de p1–p4.
