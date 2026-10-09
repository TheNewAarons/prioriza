# Rendimiento del programador CP-SAT (`scheduler`)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Resultados del benchmark `make bench-scheduler` (`scheduler/bench.py`), tomados de `results/scheduler-benchmark.json` sin modificarlos. Corrida del 2026-10-09, `code_version` `scheduler-0.1.0`, escenario `baseline`, semilla 42. Las técnicas medidas están descritas en [scheduler-formulation.md §8.6](scheduler-formulation.md#86-técnicas-de-rendimiento-p9) y las decisiones del benchmark en [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador).

**Regenerada el 2026-10-09 con la oferta corregida del generador** (versión 0.2.0: cada agenda y pabellón reparte sus sesiones con una fase propia y el día del pabellón rota; antes se concentraban en la semana central y en lunes; formulación §11.2 y `docs/decisions.md` §13). El programador no cambió respecto de la revisión de P8 (frontera evaluada sobre la fase 3a, presupuesto fijo de 3a); cambian las corridas de entrada: mismas entradas y mismos bloques en el horizonte, repartidos en otros días. Cambios frente a la corrida anterior, en la variante `all`:

- **50.000 × 2 semanas vuelve a OPTIMAL**: brecha 0,0853 % → 0,0197 %, tiempo determinista total 25,5 → 15,0 y real 22,8 → 15,1 s.
- **50.000 × 4 semanas sigue FEASIBLE y empeora**: brecha 0,209 % → 0,366 %, tiempo determinista total 72,8 → 97,9 y real 72,0 → 93,8 s.
- **Menos agendadas en todas las celdas salvo 1.000 × 2** (79 en ambas): 114 → 108, 707 → 673, 1.369 → 1.333, 3.577 → 3.338 y 7.243 → 6.935; la voraz `priority` baja igual (113 → 107, 687 → 657, 1.334 → 1.302, 3.438 → 3.218 y 6.916 → 6.651). Una explicación posible, no medida: con la oferta repartida, parte de las sesiones de la semana 0 cae el lunes que inicia el horizonte, a 6 días del `as_of`, por debajo de `min_lead_days` = 7.
- **La ganancia contra la voraz cambia de tamaño**: en 50.000 × 4, +225 GES cumplidas (antes +175) y +284 agendadas (antes +327); en 10.000 × 2 sin sobrecupo la suma de `c_ib` queda **2.169 puntos bajo** la voraz (antes 24).

## 1. Qué se mide y cómo

- **Celdas.** Combinaciones de tamaño de la lista de espera × horizonte del plan: 1.000, 10.000 y 50.000 entradas × 2 y 4 semanas. En cada celda se genera una corrida sintética propia en `data/bench/`, con el `horizon_weeks` del generador igual a las semanas del plan (la misma oferta semanal, repartida en el horizonte; decisión de [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador)), porque con la oferta de 26 semanas del generador las celdas chicas tendrían 0-1 bloques y el benchmark sería trivial (artefacto de la formulación §11.2).
- **Calibración.** La corrida de 1.000 entradas **no pasa la calibración estricta del generador** (`data.calibration_strict_failed`: `C3.iq.mediana` y `C5.nacional.media(mapeados)`, por tamaño de muestra). Se usa igual: el benchmark mide al programador, no la calibración. Las corridas de 10.000 y 50.000 sí la pasan.
- **Límite de tiempo.** `time_limit_s = 120`: presupuesto de tiempo determinista de todo el plan, repartido entre subproblemas según sus pares (mínimo 1 por componente) y entre fases (formulación §8.5); la expansión de frontera recibe otra vez su parte, así que el total puede superarlo. `relative_gap_limit = 0,001` en las fases 3a y 3b. Modo determinista: búsqueda de un solo hilo (`num_workers = 8` solo rige con `deterministic = false`). Configuración por defecto completa en el JSON (`config_defaults`).
- **Máquina** (`machine` del JSON): macOS 27.0.1 arm64, 8 CPU, Python 3.12.13, OR-Tools 9.15.6755, polars 1.44.2.
- **Tiempos.** `solve_wall_s` es el tiempo real de todo `solve` (mediana de `repeats_all = 3` repeticiones de la variante completa; las ablaciones corren una vez). `deterministic_time_plan` es el tiempo determinista que CP-SAT reporta para los subproblemas del plan y `deterministic_time_total` agrega las pasadas de la primera pasada de la frontera que se descartaron (§8.6). El tiempo determinista es la medida principal: el real varía con la carga de la máquina.

## 2. Tamaño del problema por celda

Pares: `pairs_all` = todas las entradas × todos los bloques del horizonte (un modelo sin preprocesar); `pairs_same_queue` = pares de la misma cola (lugar y especialidad); `pairs_compatible` = los que además cumplen duración y aviso mínimo (§4); `pairs_in_model` = los de las entradas candidatas tras el filtro (§8.2), que son las variables `x_ib` del plan. Niveles de sobrecupo: nominales frente a los que conserva la poda. Simetrías: clases de entradas intercambiables (entradas en clases) y de bloques (bloques en clases).

| Celda | Entradas | Bloques CNE / pab. | `pairs_all` | `pairs_same_queue` | `pairs_compatible` | `pairs_in_model` | Subproblemas | Subproblema mayor (pares) | Máx. variables | Sobrecupo nom./cons. | Clases simetría entradas / bloques |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 1.000 | 8 / 1 | 9.000 | 83 | 83 | 81 | 9 | 13 | 13 | 24 / 0 | 0 / 0 |
| 1.000 × 4 sem | 1.000 | 13 / 4 | 17.000 | 122 | 116 | 111 | 17 | 13 | 16 | 39 / 1 | 0 / 0 |
| 10.000 × 2 sem | 10.000 | 54 / 31 | 850.000 | 2.838 | 2.593 | 1.527 | 66 | 91 | 99 | 156 / 30 | 0 / 0 |
| 10.000 × 4 sem | 10.000 | 102 / 67 | 1.690.000 | 4.341 | 4.165 | 3.023 | 94 | 267 | 306 | 300 / 49 | 0 / 0 |
| 50.000 × 2 sem | 50.000 | 260 / 165 | 21.250.000 | 45.453 | 41.551 | 11.795 | 190 | 900 | 1.079 | 732 / 156 | 23 (47) / 8 (16) |
| 50.000 × 4 sem | 50.000 | 522 / 327 | 42.450.000 | 81.016 | 77.999 | 38.359 | 190 | 4.329 | 5.040 | 1.506 / 347 | 62 (126) / 16 (32) |

La frontera de candidatos se expandió en todas las celdas de 10.000 y 50.000 (2, 3, 13 y 35 colas alcanzadas). Tras duplicar el margen siguió alcanzada en 4 colas en 50.000 × 2 (traumatología de pabellón de los servicios 3, 11 y 33 y cirugía cardiovascular del 15) y en 3 en 50.000 × 4 (traumatología de pabellón de los servicios 3 y 33 y oftalmología CNE del 5); en las de 10.000, en ninguna. En las de 1.000 no hizo falta expandir.

## 3. Tiempo, estado y brecha de la variante completa (`optimized/all`)

| Celda | Estado | Brecha | `solve_wall_s` (mediana de 3) | Tiempo determinista plan / total | ¿Dentro del límite? (real / determinista) |
|---|---|---|---|---|---|
| 1.000 × 2 sem | OPTIMAL | 0 | 0,0121 s | 9,00e-08 / 9,00e-08 | sí / sí |
| 1.000 × 4 sem | OPTIMAL | 0 | 0,0166 s | 2,90e-06 / 2,90e-06 | sí / sí |
| 10.000 × 2 sem | OPTIMAL | 0 | 0,162 s | 3,66e-04 / 3,70e-04 | sí / sí |
| 10.000 × 4 sem | OPTIMAL | 1,82e-05 | 0,392 s | 0,0226 / 0,0289 | sí / sí |
| 50.000 × 2 sem | OPTIMAL | 0,0197 % | 15,1 s | 12,8 / 15,0 | sí / sí |
| 50.000 × 4 sem | FEASIBLE | 0,366 % | 93,8 s | 78,9 / 97,9 | sí / sí |

**El tamaño medio (10.000 entradas) se resuelve holgadamente dentro del límite**: 0,162 s (2 semanas) y 0,392 s (4 semanas) reales frente a 120 s, con estado OPTIMAL y brecha 0 o despreciable (1,82e-05). 50.000 × 2 termina OPTIMAL (dentro de `relative_gap_limit`, brecha 0,0197 %); 50.000 × 4 no cierra la brecha dentro del límite y termina FEASIBLE con 0,366 %.

## 4. Comparación con la voraz `priority`

Deltas de `optimized_vs_priority.delta` (plan completo, con sobrecupo) menos la voraz `priority`. Enteros exactos.

| Celda | p1 agendados | GES cumplidas | GES a tiempo | Agendadas (CNE / pab.) | Suma de `c_ib` | ¿No peor lexicográfico? |
|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 1.000 × 4 sem | 0 | 0 | 0 | +1 (+1 / 0) | +530 | sí |
| 10.000 × 2 sem | +1 | +6 | +6 | +16 (+14 / +2) | +36.109 | sí |
| 10.000 × 4 sem | +1 | +13 | +12 | +31 (+24 / +7) | +60.255 | sí |
| 50.000 × 2 sem | +13 | +43 | +60 | +120 (+88 / +32) | +695.144 | sí |
| 50.000 × 4 sem | +6 | +225 | +240 | +284 (+233 / +51) | +1.324.117 | sí |

Comparación sin sobrecupo (`optimized_without_overbooking_vs_priority`, como manda la decisión de comparar en igualdad de condiciones):

| Celda | p1 agendados | GES cumplidas | GES a tiempo | Agendadas (CNE / pab.) | Suma de `c_ib` | ¿No peor lexicográfico? |
|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 1.000 × 4 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 10.000 × 2 sem | +1 | +6 | +6 | +2 (0 / +2) | **−2.169** | sí |
| 10.000 × 4 sem | +1 | +13 | +12 | +7 (0 / +7) | +394 | sí |
| 50.000 × 2 sem | +13 | +43 | +61 | +32 (0 / +32) | +281.903 | sí |
| 50.000 × 4 sem | +6 | +225 | +240 | +51 (0 / +51) | +396.280 | sí |

Se reportan tal cual las diferencias pequeñas o nulas: en 1.000 × 2 el plan optimizado es idéntico a la voraz en todas las métricas, y en 10.000 × 2 sin sobrecupo la suma de `c_ib` queda **2.169 puntos bajo** la voraz. El orden lexicográfico sigue siendo "no peor" porque prioriza primero p1 agendados, luego GES cumplidas y solo al final el puntaje: en esa celda el optimizador agenda 1 p1 más y gana 6 GES cumplidas a costa de esos 2.169 puntos. Las ganancias grandes de agendadas con sobrecupo son casi todas CNE (sobreagendamiento); sin sobrecupo solo quedan las de pabellón. Las corridas sin sobrecupo terminan OPTIMAL en todas las celdas.

## 5. Ablación (celdas de 50.000)

Cada variante apaga una técnica (§8.6); `none` las apaga todas. Corre una sola vez (sin mediana). En las celdas de 1.000 y en 10.000 × 2 todas las variantes llegan al mismo `sum_coef` que la completa, con todo OPTIMAL. En 10.000 × 4 todas terminan OPTIMAL (dentro de `relative_gap_limit`) pero el `sum_coef` varía en 197 puntos: 5.540.371 en `none`; 5.540.288 sin pista con sobrecupo; 5.540.283 en `all`, `without_objective_cut`, `without_symmetry_breaking` y `without_warm_start_frontier`; 5.540.179 sin poda de niveles y 5.540.174 sin pistas. Con tiempos deterministas menores que 0,05, la ablación solo es informativa en 50.000.

### 50.000 × 2 semanas

| Variante | Estado | Brecha | Tiempo determinista total | `sum_coef` | Agendadas | Advertencias |
|---|---|---|---|---|---|---|
| `all` | OPTIMAL | 0,0197 % | 15,0 | 18.407.534 | 3.338 | 0 |
| `none` | OPTIMAL | 0,0158 % | 19,8 | 18.408.089 | 3.338 | 0 |
| `without_hints` | UNKNOWN | 0,0158 % | 14,7 | 18.408.572 | 3.338 | 0 |
| `without_objective_cut` | OPTIMAL | 0,0204 % | 14,9 | 18.407.593 | 3.338 | 0 |
| `without_overbooking_hint` | OPTIMAL | 0,0187 % | 15,2 | **18.408.805** | 3.338 | 0 |
| `without_prune_overbooking_levels` | OPTIMAL | 0,0149 % | 13,5 | 18.407.858 | 3.338 | 0 |
| `without_symmetry_breaking` | OPTIMAL | 0,0155 % | 15,8 | 18.407.611 | 3.338 | 0 |
| `without_warm_start_frontier` | OPTIMAL | 0,0192 % | 14,2 | 18.407.522 | 3.338 | 0 |

### 50.000 × 4 semanas

| Variante | Estado | Brecha | Tiempo determinista total | `sum_coef` | Agendadas | Advertencias |
|---|---|---|---|---|---|---|
| `all` | FEASIBLE | 0,366 % | 97,9 | 34.848.421 | 6.935 | 0 |
| `none` | UNKNOWN | — (null) | 118,6 | 34.655.722 | 6.884 | **1** (`worse_than_baseline`) |
| `without_hints` | UNKNOWN | — (null) | 111,0 | **34.885.292** | 6.944 | 0 |
| `without_objective_cut` | FEASIBLE | 0,387 % | 99,2 | 34.842.298 | 6.934 | 0 |
| `without_overbooking_hint` | FEASIBLE | 0,815 % | 106,4 | 34.691.199 | 6.898 | 0 |
| `without_prune_overbooking_levels` | FEASIBLE | 0,915 % | 118,4 | 34.799.074 | 6.924 | 0 |
| `without_symmetry_breaking` | FEASIBLE | 0,374 % | 104,8 | 34.850.118 | 6.935 | 0 |
| `without_warm_start_frontier` | FEASIBLE | 0,347 % | 99,5 | 34.856.501 | 6.937 | 0 |

Se reporta tal cual lo que sale al apagar técnicas, en cualquier dirección (las técnicas no cambian el óptimo, pero con brecha positiva o límite de tiempo sí cambian el plan entregado; [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador)):

- **Apagar las pistas da el mejor objetivo en la celda mayor, pero sin cota**: `without_hints` en 50.000 × 4 logra el mejor `sum_coef` (34.885.292, +0,11 % sobre `all`) y agenda 9 más (6.944), pero tarda más (111,0 frente a 97,9 deterministas) y termina UNKNOWN sin brecha definida. Dos variantes más superan levemente a `all` en `sum_coef` (sin simetrías y sin arranque en caliente de la frontera); sin arranque en caliente además tarda poco más (99,5) y cierra algo más la brecha (0,347 %).
- **La pista voraz con sobrecupo y la poda de niveles son las que más pesan al apagarse en 50.000 × 4**: sin la pista con sobrecupo, la brecha sube a 0,815 % y se agendan 37 menos (6.898); sin poda, la brecha es 0,915 % (la peor de la tabla) con 118,4 deterministas y 11 agendadas menos.
- **`none` en 50.000 × 4 es la única corrida con advertencia `worse_than_baseline`**: terminó UNKNOWN en 4 subproblemas de la fase 3b y 1 de la fase 4, con el peor objetivo (34.655.722) y 51 agendadas menos que `all`. Su brecha es `null` porque terminó UNKNOWN sin cota útil.
- En 50.000 × 2 todas las variantes agendan 3.338 y seis superan levemente el `sum_coef` de `all` (la mejor, `without_overbooking_hint`, +1.271 puntos); `without_prune_overbooking_levels` es la más rápida (13,5). Con brechas positivas distintas, el mejor incumbente encontrado no es único: en esta celda la ablación no muestra ganancia clara de ninguna técnica.

## 6. Limitaciones

- **Una sola máquina.** Todos los tiempos son del Mac arm64 de 8 núcleos descrito en la sección 1 (en esta corrida las 3 repeticiones de cada variante completa variaron menos de 0,3 s); el tiempo real varía con la carga. Por eso la medida principal es el tiempo determinista de CP-SAT.
- **La brecha de la fase 3b mide en parte la cota.** Con restricciones de indicador, la cota lineal de 3b es débil (ver `_gap_by_phase` en `scheduler/plan.py`; la poda de §8.6 la ajusta en parte): una brecha positiva no implica que la solución esté lejos del óptimo.
- **Oferta sintética.** El generador concentraba las sesiones CNE a mitad del horizonte y los bloques de pabellón en lunes (formulación §11.2); se corrigió en la versión 0.2.0 y este benchmark ya usa la oferta corregida. Las cifras no son comparables una a una con las de versiones anteriores de este documento.
- **La celda de 1.000 no es una población calibrada** (sección 1): sus números miden rendimiento, no representatividad.
- **Datos sintéticos.** Estas cifras validan que el programador escala y que sus técnicas funcionan sobre la estructura del generador; no dicen nada sobre tiempos ni ganancias con datos reales.
