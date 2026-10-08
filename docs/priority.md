# Priorización de listas de espera

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Principios

El módulo `priority/` calcula un **puntaje de 0 a 100** para cada paciente en lista de espera. Este puntaje es:

- **Transparente y auditable**: se basa en tres componentes explícitos (prioridad clínica declarada, días de espera, cercanía a plazos GES), cada uno con transformación documentada y peso configurável.
- **Declarativo, no predictivo**: la prioridad clínica es un dato de entrada (definido por un profesional clínico), nunca inferido ni sobreescrito.
- **Sin ML**: usa solo aritmética, transformaciones polinómicas y rampa lineal.
- **Con restricción dura GES**: las garantías vencidas o próximas a vencer van delante del resto, ordenadas por plazo (earliest deadline first). Las entradas p1 van delante de las GES de p2–p4.

Ningún ranking se usa sin revisión humana.

## Fórmula

Las variables se derivan con una fecha `as_of` explícita:

- `wait_days = (as_of − entry_date).days`
- `days_to_ges_deadline = (ges_deadline − as_of).days` (vale `None` si no es GES)

Cada componente produce un valor normalizado `v_i ∈ [0,1]`. El puntaje total es:

**S = Σ_i (100 · w_i / Σ_j w_j) · v_i ∈ [0, 100]**

Se suma en el orden del YAML, se redondea a 6 decimales y se compara usando el entero `round(S·10⁶)`.

| Componente | Transformación | Peso por defecto |
|---|---|---|
| Prioridad clínica | Escalones: p1 = 1,0; p2 = 0,6; p3 = 0,25; p4 = 0,0 | 50 |
| Días de espera | Lineal saturada en 730 días: `min(wait_days, 730) / 730` | 35 |
| Cercanía al plazo GES | Rampa descendente: `clip((60 − days_to_ges_deadline) / 60, 0, 1)`, vale 0 si d ≥ 60 o no es GES, 1 si d ≤ 0 | 15 |

**Invariantes** (con pesos por defecto):

1. **I1**: La espera sola nunca hace que p3 o p4 supere a p1 (diferencias 37,5 y 50 puntos vs. máx. 35 de espera).
2. **I2**: Niveles adyacentes se pueden superar con espera extra: p2 supera a p1 con 418 días más de espera; p3 empata con p2 con 365 días más y lo supera por fecha de ingreso (es más antigua); p4 supera a p3 con 261 días más. Estas equivalencias valen sin cesión a p1 (`yield_to_priorities: []`); con la configuración por defecto un p1 siempre va primero.
3. **I3**: GES aporta máx. 15 puntos (menos que cualquier salto de nivel salvo p3–p4).

## Regla dura GES y cesión a p1

Una entrada entra en nivel estricto si está **vencida** (d < 0) o **por vencer** (0 ≤ d ≤ 14 días):

- `GES_OVERDUE`: vencida.
- `GES_DUE_SOON`: por vencer en ≤ 14 días.
- `NONE`: cualquier otra (incluye no GES).

**Orden total** (sin empates):

```
( −(clinical_priority ∈ yield_to_priorities),  # p1 primero
  d                                             # dentro de p1: EDF (vencidas antes)
  −round(S·10⁶),                               # puntaje (desc.)
  entry_date.toordinal(),                      # fecha (asc.)
  entry_id )                                   # desempate (asc.)
```

**Configuración por defecto:**
- `yield_to_priorities: [p1]`: un p1 cualquiera va antes que cualquier GES de p2–p4.
- `order_within: deadline`: orden por plazo GES (earliest deadline first).
- `due_soon_days: 14`: umbral de días.

Para desactivar la regla completa: `ges_strict.enabled: false` (todos pasan a nivel `NONE`; el plazo influye solo a través de la rampa).

## Ejemplos A–E (as_of = 2025-09-30)

| Entrada | Prioridad | Espera | Estado GES | Puntaje | Orden (defecto) |
|---|---|---|---|---|---|
| A | p1 | 30 días | No GES | 51,44 | 1 |
| B | p2 | 400 días | No GES | 49,18 | 3 |
| C | p4 | 1.500 días | No GES | 35,00 | 5 |
| D | p3 | 120 días | Vencida hace 10 d. | 33,25 | 2 |
| E | p2 | 20 días | Vence en 25 d. | 39,71 | 4 |

**Orden por defecto (con cesión a p1):** A, D, B, E, C

**Orden sin cesión** (`yield_to_priorities: []`): D, A, B, E, C

**Orden sin regla dura** (`ges_strict.enabled: false`): A, B, E, C, D

Notas:
- D va delante de A porque D está vencida (nivel estricto). Con la cesión a p1, A va primero (p1 > p3).
- C nunca supera a A ni B: la espera no anula la prioridad.
- E no entra en nivel estricto porque vence en 25 días > 14 (umbral).

## Campos permitidos y prohibidos

**Permitidos** (lista blanca):
- `clinical_priority`: prioridad clínica declarada (p1, p2, p3, p4).
- `wait_days`: días desde ingreso a `as_of`.
- `days_to_ges_deadline`: días hasta vencimiento de plazo GES.

**Prohibidos** (lista negra con motivo):
- `sex`, `gender`: atributo protegido.
- `ethnicity`: atributo protegido.
- `nationality`: atributo protegido.
- `commune_code`: proxy territorial/socioeconómico.
- `insurance`: proxy de ingreso.
- `age_group`: atributo protegido; lo clínico va en la prioridad declarada.
- `health_service_code`, `establishment_code`: proxy territorial; definen la cola, no el orden.
- `specialty_code`, `procedure_code`, `ges_problem_code`: proxy de sexo/edad (p. ej. ginecología, próstata).
- `predicted_noshow_prob`: la inasistencia no puede bajar la prioridad.
- `noshow_frailty`, `true_noshow_prob`: verdad sintética.
- `patient_id`: identificador.

**Aclaraciones:**
- Comuna, previsión, grupo etario y servicio de salud se usan **solo para medir equidad** (si el sobreagendamiento perjudica sistemáticamente a algún grupo). Nunca entran en la fórmula del puntaje.
- El tipo de atención (ambulatorio, pabellón) define la cola (partición); no ordena dentro de ella.

## Reglas por defecto

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
  cercanía al plazo GES con rampa de 60 días (15). Las entradas p1 van primero; luego las
  garantías GES vencidas o que vencen en 14 días o menos (restricción dura), ordenadas por plazo.
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
  yield_to_priorities: [p1]
```

**Validación de reglas propias:**

Cargue un archivo YAML con la estructura anterior y valide con:

```python
from pathlib import Path

from priority.rules import load_rules

rules = load_rules(Path("mi_ruleset.yaml"))  # Lanza RulesError en español si hay problemas
print(f"Reglas OK. Digest: {rules.digest()}")
```

Las funciones clave son:
- `load_rules(path: Path) -> RuleSet`: carga desde archivo.
- `parse_rules(text: str) -> RuleSet`: parsea desde texto.
- `load_default_rules() -> RuleSet`: carga las reglas por defecto.

### Validaciones del YAML

Un YAML se rechaza con `RulesError` (mensaje en español con la ruta del campo) si:
- usa un campo fuera de la lista blanca (si es prohibido, el mensaje da el motivo);
- tiene claves extra, claves duplicadas, merge keys (`<<`), anclas o alias;
- un número viene como texto o booleano, un peso es negativo, NaN, infinito o mayor que 1000, o el peso clínico es 0;
- el mapeo clínico no es monótono (p1 ≥ p2 ≥ p3 ≥ p4 y p1 > p4) o le faltan niveles;
- `yield_to_priorities` no es vacío ni un prefijo contiguo de p1..p4 (no se puede anteponer una prioridad clínica a otra mejor), o no está vacío con la regla GES desactivada (sin nivel estricto no hay a quién ceder);
- la rampa GES empieza después del umbral "por vencer" estando la regla activa;
- una etiqueta (`label`) nombra un atributo prohibido (comuna, previsión, edad, sexo, etnia, nacionalidad, etc.), para que la explicación no pueda declarar que usa algo que no usa.

Además, `explain` falla si las reglas no son las mismas con que se calculó el ranking (se compara el `digest`).

## Explicaciones de ejemplo

Copias literales de explicaciones generadas por el módulo:

### Ejemplo 1: p1 con GES vencida (población canónica, puesto 1)

```
Puesto 1 de 100.000.
Puntaje 100,00/100.
Prioridad clínica declarada: p1 → escalón fijo por prioridad declarada = 1,00 × peso 50 = 50,00
Días de espera: 900 días → lineal saturada en 730 días = 1,00 × peso 35 = 35,00
Cercanía al plazo GES: -870 días → rampa descendente de 60 a 0 días al plazo = 1,00 × peso 15 = 15,00
Más espera no aumenta el puntaje; frente a otra entrada con igual puntaje, desempata la fecha de ingreso.
Nivel estricto: garantía GES vencida (plazo 2023-05-14, 870 días de atraso). Por la regla `ges_strict` (activa) va antes que toda entrada sin nivel estricto.
Prioridad p1: por la regla `ges_strict.yield_to_priorities` va antes que toda entrada de prioridad fuera de p1, incluidas las GES vencidas.
```

### Ejemplo 2: p4 con GES vencida (población canónica, puesto 6.176)

```
Puesto 6.176 de 100.000.
Puntaje 50,00/100.
Prioridad clínica declarada: p4 → escalón fijo por prioridad declarada = 0,00 × peso 50 = 0,00
Días de espera: 2.537 días → lineal saturada en 730 días = 1,00 × peso 35 = 35,00
Cercanía al plazo GES: -2.447 días → rampa descendente de 60 a 0 días al plazo = 1,00 × peso 15 = 15,00
Más espera no aumenta el puntaje; frente a otra entrada con igual puntaje, desempata la fecha de ingreso.
Nivel estricto: garantía GES vencida (plazo 2019-01-18, 2.447 días de atraso). Por la regla `ges_strict` (activa) va antes que toda entrada sin nivel estricto, salvo las de prioridad p1.
```

### Ejemplo 3: p2 con espera saturada, no GES (población canónica, puesto 8.319)

```
Puesto 8.319 de 100.000.
Puntaje 65,00/100.
Prioridad clínica declarada: p2 → escalón fijo por prioridad declarada = 0,60 × peso 50 = 30,00
Días de espera: 3.650 días → lineal saturada en 730 días = 1,00 × peso 35 = 35,00
Cercanía al plazo GES: no aplica = 0,00 × peso 15 = 0,00
Más espera no aumenta el puntaje; frente a otra entrada con igual puntaje, desempata la fecha de ingreso.
Nivel estricto: ninguno.
```

## Medición de sesgo (población sintética)

Medido por reviewer el 2026-10-08 con N = 100.000, semilla 42, escenario baseline, `as_of` 2025-09-30, reglas por defecto y ranking por cola (servicio, especialidad y tipo: 2.216 colas). Métrica: percentil medio dentro de la cola (0 = primero, 1 = último). Para separar el ruido se permutaron las etiquetas de grupo dentro de cada cola 200 veces.

| Grupo | Percentil medio (mín–máx) | Rango observado | Rango esperado por azar (p50 / p95) | p |
|---|---|---|---|---|
| Grupo etario (5) | 0,4993 – 0,5013 | 0,0020 | 0,0058 / 0,0107 | 0,985 |
| Previsión (5) | 0,4986 – 0,5022 | 0,0036 | 0,0057 / 0,0104 | 0,865 |
| Comuna (94 con n ≥ 300) | 0,4761 – 0,5354 | 0,0592 | 0,0629 / 0,0782 | 0,790 |

- **Efecto del puntaje: nulo por construcción.** El cálculo solo recibe prioridad clínica, fecha de ingreso y plazo GES; las diferencias por grupo están dentro del ruido.
- **Efecto de la composición:** el grupo 0-14 tiene la mitad de entradas con nivel estricto que 45-64 (1,5 % frente a 3,0 %) porque tiene menos GES; las comunas difieren en % GES y espera. Esto viene de la ley GES y del generador, no de las reglas.
- **Límite:** en la población sintética la prioridad y la espera son independientes de edad, previsión y comuna. La prueba confirma que el puntaje no usa esos atributos, pero no dice nada del sesgo que habría con datos reales.
- **Proxy de sexo entre colas:** ginecología, obstetricia y mama tiene 9,8 % de entradas con nivel estricto frente a 1,1 % en urología, y 3,1 puntos más de puntaje medio, por la composición GES y oncológica. Dentro de cada cola no hay efecto, pero si el programador reparte capacidad compartida entre colas usando puntaje o nivel, esa diferencia pasaría al reparto. Debe medirse y reportarse en `scheduler/`.

## Limitaciones

1. **Pesos no validados clínicamente**: los valores 50/35/15 y el mapeo p1..p4 son una propuesta de ejemplo, no una norma clínica. Quedan versionados mediante `rules_version` y `rules_digest`.
2. **Plazos GES provisorios**: los valores en la población sintética son ejemplo, no datos verificados contra normas reales (parámetro `verified: false` en el generador).
3. **Independencia de prioridad y espera**: en la población sintética, la prioridad clínica es independiente de los días de espera (los p1 no GES tienen mediana ~246 días, igual que el resto). Es un artefacto del generador, no del módulo; refleja que no hay evidencia de que los p1 clínicamente son los que menos esperan en lista.
4. **Proxy residual vía GES**: la duración del plazo GES depende del problema de salud, que se correlaciona con sexo (p. ej. ginecología, próstata, mama). No se puede eliminar sin ignorar la garantía legal. Como mitigación se miden desigualdades por grupo etario, comuna y previsión y se reportan en auditoría.

## Interfaces principales

```python
from datetime import date

from priority import PriorityInput, explain_ranked, load_default_rules, rank, score_entry
from shared.db.enums import ClinicalPriority

rules = load_default_rules()
as_of = date(2025, 9, 30)  # fecha de referencia siempre explícita
entradas = [
    PriorityInput(
        entry_id="a", clinical_priority=ClinicalPriority.P1, entry_date=date(2025, 8, 31)
    ),
    PriorityInput(
        entry_id="d",
        clinical_priority=ClinicalPriority.P3,
        entry_date=date(2025, 6, 2),
        ges_deadline=date(2025, 9, 20),  # GES vencida hace 10 días
    ),
]

puntaje = score_entry(entradas[0], rules, as_of=as_of)
ranking = rank(entradas, rules, as_of=as_of)
print(explain_ranked(ranking, "d", rules).text)
```

**Rendimiento**: ranking de 100.000 entradas en ~1,5 s.
