# Rendimiento del programador CP-SAT (`scheduler`)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Resultados del benchmark `make bench-scheduler` (`scheduler/bench.py`), tomados de `results/scheduler-benchmark.json` sin modificarlos. Corrida del 2026-10-09, `code_version` `scheduler-0.1.0`, escenario `baseline`, semilla 42. Las técnicas medidas están descritas en [scheduler-formulation.md §8.6](scheduler-formulation.md#86-técnicas-de-rendimiento-p9) y las decisiones del benchmark en [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador).

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
| 1.000 × 4 sem | 1.000 | 13 / 4 | 17.000 | 122 | 122 | 117 | 17 | 13 | 16 | 39 / 1 | 0 / 0 |
| 10.000 × 2 sem | 10.000 | 54 / 31 | 850.000 | 2.838 | 2.726 | 1.608 | 57 | 112 | 128 | 162 / 34 | 0 / 0 |
| 10.000 × 4 sem | 10.000 | 102 / 67 | 1.690.000 | 4.341 | 4.204 | 3.057 | 90 | 267 | 306 | 306 / 50 | 0 / 0 |
| 50.000 × 2 sem | 50.000 | 260 / 165 | 21.250.000 | 45.453 | 44.450 | 13.023 | 183 | 930 | 1.176 | 780 / 175 | 35 (71) / 4 (8) |
| 50.000 × 4 sem | 50.000 | 522 / 327 | 42.450.000 | 81.016 | 80.124 | 37.748 | 188 | 4.443 | 5.216 | 1.566 / 380 | 61 (124) / 32 (70) |

La frontera de candidatos se expandió en todas las celdas de 10.000 y 50.000 (2, 3, 17 y 33 colas alcanzadas). Tras duplicar el margen siguió alcanzada en 3 colas en 50.000 × 2 (traumatología de pabellón de los servicios 3, 11 y 33) y en 2 en 50.000 × 4 (servicios 3 y 33); en las de 10.000, en ninguna. En las de 1.000 no hizo falta expandir.

## 3. Tiempo, estado y brecha de la variante completa (`optimized/all`)

| Celda | Estado | Brecha | `solve_wall_s` (mediana de 3) | Tiempo determinista plan / total | ¿Dentro del límite? (real / determinista) |
|---|---|---|---|---|---|
| 1.000 × 2 sem | OPTIMAL | 0 | 0,0116 s | 9,00e-08 / 9,00e-08 | sí / sí |
| 1.000 × 4 sem | OPTIMAL | 0 | 0,0172 s | 2,90e-06 / 2,90e-06 | sí / sí |
| 10.000 × 2 sem | OPTIMAL | 0 | 0,172 s | 5,46e-04 / 5,50e-04 | sí / sí |
| 10.000 × 4 sem | OPTIMAL | 3,55e-07 | 0,406 s | 0,0263 / 0,0347 | sí / sí |
| 50.000 × 2 sem | OPTIMAL | 0,0277 % | 20,2 s | 18,3 / 21,2 | sí / sí |
| 50.000 × 4 sem | FEASIBLE | 0,182 % | 76,1 s | 68,0 / 78,1 | sí / sí |

**El tamaño medio (10.000 entradas) se resuelve holgadamente dentro del límite**: 0,172 s (2 semanas) y 0,406 s (4 semanas) reales frente a 120 s, con estado OPTIMAL y brecha 0 o despreciable (3,55e-07). La celda mayor (50.000 × 4 semanas) es la única que no cierra la brecha dentro del límite: termina FEASIBLE con 0,182 %.

## 4. Comparación con la voraz `priority`

Deltas de `optimized_vs_priority.delta` (plan completo, con sobrecupo) menos la voraz `priority`. Enteros exactos.

| Celda | p1 agendados | GES cumplidas | GES a tiempo | Agendadas (CNE / pab.) | Suma de `c_ib` | ¿No peor lexicográfico? |
|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 1.000 × 4 sem | 0 | 0 | 0 | +1 (+1 / 0) | +537 | sí |
| 10.000 × 2 sem | 0 | +7 | +7 | +20 (+19 / +1) | +53.943 | sí |
| 10.000 × 4 sem | 0 | +9 | +8 | +35 (+28 / +7) | +85.772 | sí |
| 50.000 × 2 sem | +10 | +27 | +38 | +139 (+108 / +31) | +805.551 | sí |
| 50.000 × 4 sem | +7 | +175 | +187 | +328 (+276 / +52) | +1.358.106 | sí |

Comparación sin sobrecupo (`optimized_without_overbooking_vs_priority`, como manda la decisión de comparar en igualdad de condiciones):

| Celda | p1 agendados | GES cumplidas | GES a tiempo | Agendadas (CNE / pab.) | Suma de `c_ib` | ¿No peor lexicográfico? |
|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 1.000 × 4 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 10.000 × 2 sem | 0 | +7 | +7 | +1 (0 / +1) | **−24** | sí |
| 10.000 × 4 sem | 0 | +9 | +8 | +7 (0 / +7) | +15.741 | sí |
| 50.000 × 2 sem | +10 | +27 | +38 | +31 (0 / +31) | +285.524 | sí |
| 50.000 × 4 sem | +7 | +175 | +187 | +52 (0 / +52) | +276.114 | sí |

Se reportan tal cual las diferencias pequeñas o nulas: en 1.000 × 2 el plan optimizado es idéntico a la voraz en todas las métricas, y en 10.000 × 2 sin sobrecupo la suma de `c_ib` queda **24 puntos bajo** la voraz (7,77e-06 en relativo). El orden lexicográfico sigue siendo "no peor" porque prioriza primero p1 agendados, luego GES cumplidas y solo al final el puntaje: en esa celda el optimizador empata en p1 y gana 7 GES cumplidas antes de perder esos 24 puntos. Las ganancias grandes de agendadas con sobrecupo son casi todas CNE (sobreagendamiento); sin sobrecupo solo quedan las de pabellón.

## 5. Ablación (celdas de 50.000)

Cada variante apaga una técnica (§8.6); `none` las apaga todas. Corre una sola vez (sin mediana). En las celdas de 1.000 y en 10.000 × 2 todas las variantes llegan al mismo `sum_coef` que la completa, con todo OPTIMAL. En 10.000 × 4 todas terminan OPTIMAL (dentro de `relative_gap_limit`) pero el `sum_coef` varía en 129 puntos: 5.640.566 en `all`, `without_objective_cut`, `without_symmetry_breaking` y `without_warm_start_frontier`; 5.640.562 sin pistas; 5.640.551 en `none`; 5.640.474 sin pista con sobrecupo y 5.640.437 sin poda de niveles. Con tiempos deterministas menores que 0,05, la ablación solo es informativa en 50.000.

### 50.000 × 2 semanas

| Variante | Estado | Brecha | Tiempo determinista total | `sum_coef` | Agendadas | Advertencias |
|---|---|---|---|---|---|---|
| `all` | OPTIMAL | 0,0277 % | 21,2 | 19.494.283 | 3.577 | 0 |
| `none` | UNKNOWN | 0,0568 % | 22,9 | 19.493.519 | 3.577 | 0 |
| `without_hints` | UNKNOWN | 0,0571 % | 16,9 | 19.493.742 | 3.577 | 0 |
| `without_objective_cut` | FEASIBLE | 0,0442 % | 24,2 | 19.493.947 | 3.577 | 0 |
| `without_overbooking_hint` | OPTIMAL | 0,0156 % | 22,4 | 19.494.904 | 3.577 | 0 |
| `without_prune_overbooking_levels` | FEASIBLE | 0,125 % | 29,3 | 19.485.383 | 3.576 | 0 |
| `without_symmetry_breaking` | OPTIMAL | 0,0268 % | 19,8 | 19.494.785 | 3.577 | 0 |
| `without_warm_start_frontier` | OPTIMAL | 0,0247 % | 19,3 | 19.494.817 | 3.577 | 0 |

### 50.000 × 4 semanas

| Variante | Estado | Brecha | Tiempo determinista total | `sum_coef` | Agendadas | Advertencias |
|---|---|---|---|---|---|---|
| `all` | FEASIBLE | 0,182 % | 78,1 | 36.252.936 | 7.244 | 0 |
| `none` | UNKNOWN | — (null) | 92,9 | 36.110.958 | 7.210 | **1** (`worse_than_baseline`) |
| `without_hints` | UNKNOWN | 0,114 % | 70,6 | **36.270.505** | 7.248 | 0 |
| `without_objective_cut` | FEASIBLE | 0,221 % | 57,1 | 36.232.433 | 7.240 | 0 |
| `without_overbooking_hint` | FEASIBLE | 0,688 % | 96,0 | 36.076.324 | 7.204 | 0 |
| `without_prune_overbooking_levels` | FEASIBLE | 0,698 % | 96,9 | 36.183.402 | 7.229 | 0 |
| `without_symmetry_breaking` | FEASIBLE | 0,161 % | 70,3 | 36.254.215 | 7.244 | 0 |
| `without_warm_start_frontier` | FEASIBLE | 0,179 % | 75,1 | 36.253.484 | 7.244 | 0 |

Se reporta tal cual lo que sale al apagar técnicas, en cualquier dirección (las técnicas no cambian el óptimo, pero con brecha positiva o límite de tiempo sí cambian el plan entregado; [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador)):

- **Apagar las pistas mejora la celda mayor**: `without_hints` en 50.000 × 4 logra el mejor `sum_coef` de la tabla (36.270.505, +0,05 % sobre `all`), agenda 7.248 (4 más) y tarda menos (70,6 frente a 78,1 deterministas). En 50.000 × 2 también es la variante más rápida (16,9) aunque con peor objetivo que `all`.
- **La poda de niveles de sobrecupo y la pista voraz con sobrecupo son las que más pesan al apagarse**: sin cualquiera de las dos, la brecha sube a ~0,7 % y el tiempo determinista a ~96-97, con el peor o el segundo peor objetivo.
- **`none` en 50.000 × 4 es la única corrida con advertencia `worse_than_baseline`**: quedó 3 puntos (0,005 %) bajo la voraz en un subproblema con todas las fases OPTIMAL (OPTIMAL con `relative_gap_limit = 0,001` no es óptimo probado; formulación §9.5). Su brecha es `null` porque terminó UNKNOWN sin cota útil.
- Varias variantes con OPTIMAL en 50.000 × 2 superan levemente el `sum_coef` de `all` (`without_overbooking_hint`, `without_symmetry_breaking`, `without_warm_start_frontier`): con brechas positivas distintas, el mejor incumbente encontrado no es único.

## 6. Limitaciones

- **Una sola máquina.** Todos los tiempos son del Mac arm64 de 8 núcleos descrito en la sección 1 (en esta corrida las 3 repeticiones de cada variante completa variaron menos de 0,1 s); el tiempo real varía con la carga (en desarrollo el mismo plan varió entre 63 y 98 s). Por eso la medida principal es el tiempo determinista de CP-SAT.
- **La brecha de la fase 3b mide en parte la cota.** Con restricciones de indicador, la cota lineal de 3b es débil (ver `_gap_by_phase` en `scheduler/plan.py`; la poda de §8.6 la ajusta en parte): una brecha positiva no implica que la solución esté lejos del óptimo.
- **Artefactos de la oferta sintética.** El generador concentra las sesiones CNE a mitad del horizonte y los bloques de pabellón en lunes (formulación §11.2). El benchmark los esquiva generando oferta repartida en el horizonte, pero **no corrige el generador**: esa corrección sigue pendiente antes de la simulación de políticas.
- **La celda de 1.000 no es una población calibrada** (sección 1): sus números miden rendimiento, no representatividad.
- **Datos sintéticos.** Estas cifras validan que el programador escala y que sus técnicas funcionan sobre la estructura del generador; no dicen nada sobre tiempos ni ganancias con datos reales.
