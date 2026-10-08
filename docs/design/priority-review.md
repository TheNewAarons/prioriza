# Revisión del módulo `priority/` (reviewer, 2026-10-08)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Decisión de la sesión principal sobre M1: con `ges_strict.enabled: false`, un `yield_to_priorities` no vacío es un error de validación. Estado de cada hallazgo al final.

No encontré ningún hallazgo crítico. Tests, lint y typecheck pasan. Hay 2 hallazgos altos, 4 medios y 5 bajos. La medición sobre la población sintética no muestra sesgo atribuible al puntaje, pero por cómo se generó esa población la prueba es débil.

## Verificaciones

- `uv run pytest priority -q`: 190 tests pasan (72 + 72 + 46).
- `uv run ruff check .`: `All checks passed!`
- `uv run mypy` (strict en shared, priority y scheduler): `Success: no issues found in 23 source files`

## Hallazgos

### Alto

**A1. `yield_to_priorities` permite poner una prioridad clínica por encima de otra mejor** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/rules.py:166-172`)
- **Problema:** solo se validan duplicados. Se acepta `[p4]`, `[p2, p3]` o `[p3]`.
- **Escenario reproducido:**
  - con `[p4]`, el orden queda `b:p4, c:p2, a:p1`;
  - con `[p2, p3]`, queda `c:p2, a:p1, b:p4`.
- **Por qué importa:** un YAML válido cambia el orden de la prioridad clínica declarada, lo que viola "nunca la sobreescribe". También rompe la propiedad 2 del plan. Los tests no lo detectan:
  - `test_better_clinical_priority_never_worsens_rank` solo usa `DEFAULT_LIKE`;
  - `rules_st` (`test_priority_properties.py:268`) genera listas arbitrarias y nunca comprueba la monotonía con ellas.
- **Corrección:** exigir que la lista sea vacía o un prefijo contiguo de p1..p4 (`[p1]`, `[p1, p2]`, …). Agregar la propiedad 2 con `rules_st`.

**A2. La explicación afirma un orden falso cuando la regla cede a p1** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/explain.py:99-102`)
- **Escenario reproducido con las reglas por defecto:** una entrada p2 con GES vencida queda en el puesto 2, detrás de una p1 no GES. Aun así, el texto dice: "Por la regla `ges_strict` (activa) va antes que toda entrada sin nivel estricto."
- La línea 105-108 ("va antes que toda entrada de otra prioridad") también es falsa con `[p1, p2]`, porque p2 no va antes que p1.
- **Por qué importa:** es una afirmación de auditoría incorrecta con la configuración por defecto.
- **Corrección:** si `rule.enabled` y la prioridad no está en `yield_to_priorities`, decir "va antes que toda entrada sin nivel estricto, salvo las de prioridad {yield}". Para el grupo que cede, decir "va antes que toda entrada de prioridad fuera de {lista}".

### Medio

**M1. Ambigüedad entre desactivar la regla y la cesión configurada** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/score.py:214`)
- **Problema:** con `enabled: false` se ignora `yield_to_priorities` sin avisar. El plan §8 no dice que la cesión dependa de `enabled`.
- **Escenario reproducido:** con `enabled: false` y `[p1]`, una p2 de 760 días queda antes que una p1 de 1 día (`['p2', 'p1']`). Con la regla activa, el orden se invierte. Quien desactiva la regla GES pierde sin saberlo la garantía de "p1 primero".
- Además, el `digest` cambia con un valor que no tiene efecto (verificado: `True`), así que dos reglas equivalentes tienen digests distintos.
- **Corrección:** elegir una de dos opciones y documentarla en el plan y en `decisions.md`:
  - separar la cesión de `enabled`;
  - o rechazar en validación `yield_to_priorities` no vacío cuando `enabled: false`.

**M2. Un `status` nulo se acepta como si estuviera en espera** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/adapters.py:45`)
- **Problema:** `null != "waiting"` da null y `filter` descarta esa fila del conjunto `bad`, así que pasa el control.
- **Escenario reproducido:** un DataFrame con `status=[waiting, None]` devuelve 2 entradas.
- **Corrección:** `pl.col("status").is_null() | (pl.col("status").cast(pl.String) != "waiting")`.

**M3. `explain` no verifica que las reglas sean las del ranking** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/explain.py:72,121-124`)
- **Problema:** `explain_ranked(r, id, rules)` no compara `r.rules_digest` con `rules.digest()`. `zip(..., strict=True)` solo falla si cambia la cantidad de componentes.
- **Escenario:** un ranking hecho con pesos 50/35/15 se explica con un YAML de pesos 60/30/10. Las etiquetas y la descripción del orden salen de las reglas nuevas, en silencio.
- **Corrección:** lanzar `ValueError` si los digests difieren. Otra opción es guardar el digest en `PriorityScore`.

**M4. El rendimiento queda al límite en la ruta real** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/adapters.py:44-50,76-79`)
- **Cifras medidas con 100.000 entradas y 2.216 colas:**

  | Medición | Tiempo |
  |---|---|
  | `rank` puro | 1,29-1,34 s |
  | `rank_frame` en caliente | 1,74-1,82 s |
  | `rank_frame` en la primera corrida | 2,69 s, sobre el presupuesto de 2 s |
  | `inputs_from_frame` por cola, dentro de `rank_frame` | 0,56-0,59 s |

- **Problema:** la mayor parte del costo extra es la conversión y el filtro de `status` repetidos en cada una de las 2.216 colas. El test de rendimiento (`test_priority_explain.py:136`) solo mide `rank`, con un umbral de 5 s.
- **Corrección:** validar `status` y convertir una sola vez antes de particionar (`partition_by` sobre la lista ya convertida). Agregar un test de `rank_frame`.

### Bajo

**B1. La validación de números es laxa** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/rules.py:120,141,150`)
- `weight: true` se acepta como 1.0 y `weight: "35"` como 35.0.
- No hay cota superior: dos pesos de `1e308` producen `OverflowError: intermediate overflow in fsum` al rankear, no un `RulesError` al cargar.
- **Corrección:** `Field(..., strict=True, le=1000)`, o `ConfigDict(strict=True)` en `_Frozen`.

**B2. Las merge keys de YAML esquivan la detección de duplicados** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/rules.py:248-249`)
- `<<: [{enabled: false}, {enabled: true}]` da `enabled=False` sin error.
- `<<: {weight: 0}` junto a `weight: 35` explícito queda en 35 sin aviso.
- No permite usar campos prohibidos: la lista blanca resiste porque el discriminador es `Literal`, y mayúsculas, alias o campos anidados dan error de "campo desconocido" o `extra_forbidden`. Pero sí permite configuraciones engañosas.
- **Corrección:** rechazar `tag:yaml.org,2002:merge` y los alias en el cargador. Las reglas no los necesitan.

**B3. Las etiquetas son texto libre** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/rules.py:119,140,149`)
- `label: "Comuna de residencia"` se acepta en el componente clínico. Ningún dato prohibido entra al texto, porque `PriorityInput` no los tiene, pero la explicación puede mentir sobre qué se usó.
- El test `test_explanation_does_not_mention_prohibited_fields` (`test_priority_explain.py:105-112`) es tautológico: busca identificadores en inglés (`insurance`, `commune_code`) en un texto en español generado con etiquetas fijas, así que nunca puede fallar.
- **Corrección:** validar las etiquetas contra términos prohibidos en español (comuna, previsión, fonasa, edad, sexo, etnia, nacionalidad) o fijarlas por campo. Cambiar el test para usar esos términos y un YAML adversarial.

**B4. Una sola fila inválida tumba todo el ranking** (`/Users/aarons/Documents/Projects/FullPy/Prioriza/priority/src/priority/inputs.py:23-33`)
- `entry_date` no se valida: `None` da `TypeError` en `score.py:146`, y un `datetime` (subclase de `date`) también da `TypeError`.
- Un `ges_deadline` anterior a `entry_date` lanza `ValueError` y aborta el ranking completo de la cola, sin informe de filas. La población canónica tiene 0 casos.
- **Corrección:** validar `type(entry_date) is date`. En los adaptadores, juntar todas las filas inválidas en un solo error.

**B5. Hay tests débiles**
- `test_generated_rules_never_change_clinical_priority` (`test_priority_properties.py:311`) solo comprueba que el campo se copia sin cambios. No puede fallar salvo una reasignación explícita.
- No hay test para los casos de M1 y M2.

### Casos borde sin hallazgo (código, YAML y plan coinciden)
- d = 0 cuenta como por vencer, con rampa en 1,0.
- d = 14 cuenta como por vencer (`<=`).
- `entry_date = as_of` da espera 0.
- `ges_deadline` anterior a `entry_date` lanza error (no es ambiguo; ver B4).
- Empates exactos tras el redondeo se resuelven por fecha y luego por id. El orden es total y determinista.
- Una p1 GES va antes que una p1 no GES dentro del grupo que cede.
- `order_within: score` con cesión ordena por grupo, luego por nivel y luego por puntaje.
- La saturación se desempata por fecha de ingreso.
- Los pesos 0 son válidos fuera del componente clínico.
- `safe_load` (subclase de `SafeLoader`) rechaza claves duplicadas fuera de las merge keys.

## Sesgo medido

Configuración: N = 100.000, semilla 42, escenario baseline, `as_of` 2025-09-30, reglas por defecto, `rank_frame` particionado por servicio, especialidad y tipo (2.216 colas). Se usaron 99.817 entradas en colas de 2 o más. El percentil dentro de la cola va de 0 (primero) a 1 (último). Para separar el ruido, permuté las etiquetas de grupo dentro de cada cola 200 veces con semilla 42.

| Grupo | Percentil medio (mín–máx) | Rango observado | Rango esperado por azar (p50 / p95) | p(sd del azar ≥ sd observada) |
|---|---|---|---|---|
| Grupo etario (5) | 0,4993 (65+) – 0,5013 (15-19) | 0,0020 | 0,0058 / 0,0107 | 0,985 |
| Previsión (5) | 0,4986 (D) – 0,5022 (A) | 0,0036 | 0,0057 / 0,0104 | 0,865 |
| Comuna (94 con n ≥ 300) | 0,4761 (13130) – 0,5354 (09201) | 0,0592 | 0,0629 / 0,0782 | 0,790 |

- **Residuo tras controlar por los insumos** (prioridad, nivel y percentil de espera en la cola; R² = 0,84):
  - por edad, entre −0,0097 (0-14) y +0,0023;
  - por previsión, entre −0,0006 y +0,0016;
  - por comuna, rango de 0,054.
- **Especialidades con sesgo de sexo:**

  | Grupo | n | Percentil en la cola | Puntaje medio | % GES | % con nivel estricto | % p1 | Espera mediana |
  |---|---|---|---|---|---|---|---|
  | Ginecología, obstetricia y mama | 8.599 | 0,500 | 30,53 | 17,3 | 9,8 | 10,9 | 202 |
  | Urología | 8.687 | 0,500 | 27,43 | 3,2 | 1,1 | 5,6 | 247 |
  | Resto | 82.531 | 0,500 | 27,43 | 5,8 | 2,2 | 5,75 | 238 |

**Cómo leerlo:**
- **Lo que causa el puntaje:** cero por construcción. `PriorityInput` solo tiene prioridad, ingreso y plazo, así que dos entradas con los mismos insumos reciben el mismo puntaje. Todas las diferencias por grupo están dentro del ruido de la permutación (p de 0,79 a 0,985).
- **Lo que causa la composición:**
  - El grupo 0-14 tiene la mitad de entradas con nivel estricto que 45-64 (1,5 % frente a 3,0 %), porque tiene menos GES (3,6 % frente a 7,1 %).
  - Las comunas de los extremos difieren en % GES (0,3 % frente a 16,9 %) y en espera mediana.
  - Estas diferencias vienen de la ley GES y del generador, no de las reglas.
- **Límite de la evidencia:** la población sintética genera prioridad y espera de forma independiente de edad, previsión y comuna. Por eso la prueba solo confirma que el puntaje no usa esos atributos. No dice nada sobre el sesgo que tendrían datos reales.
- **Especialidades:** el percentil dentro de la cola vale 0,5 por construcción y no puede detectar sesgo entre especialidades. En ginecología, obstetricia y mama hay 4 a 9 veces más entradas con nivel estricto que en urología, y el puntaje medio es 3,1 puntos mayor, por GES y por la mezcla de prioridades oncológicas. Si `scheduler/` reparte un pabellón compartido entre colas usando puntaje o nivel, esta diferencia (un proxy de sexo) pasará al reparto. Hay que medirlo allí y documentarlo; no es un defecto de `priority/`.

Los scripts de medición están en el directorio scratchpad de la sesión: `bias.py`, `bias2.py`, `edge.py` y `perf.py`.

## Estado de los hallazgos (2026-10-09)

| Hallazgo | Estado |
|---|---|
| A1 cesión que antepone una prioridad peor | Corregido: solo vacío o prefijo contiguo de p1..p4 |
| A2 explicación con orden falso bajo cesión | Corregido: "salvo las de prioridad {lista}" / "fuera de {lista}" |
| M1 cesión con regla desactivada | Corregido: error de validación (decisión de la sesión principal) |
| M2 `status` nulo aceptado | Corregido |
| M3 explicación con reglas distintas | Corregido: se compara el digest |
| M4 rendimiento de `rank_frame` | Corregido: 1,2 s en frío y en caliente (antes 2,7 s en frío) |
| B1 números laxos y overflow | Corregido: números estrictos, pesos ≤ 1000 |
| B2 merge keys y alias | Corregido: rechazados |
| B3 etiquetas engañosas y test tautológico | Corregido: etiquetas validadas; test reemplazado por uno adversarial |
| B4 filas inválidas | Corregido: tipos exigidos y error único con ejemplos |
| B5 tests débiles | Corregido: propiedades sobre RuleSets generados |
| Proxy de sexo entre colas (GES/oncología) | Pendiente para `scheduler/`: medir y reportar si la capacidad compartida se reparte por puntaje o nivel |
