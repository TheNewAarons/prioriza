# Rendimiento del programador CP-SAT (`scheduler`)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Resultados del benchmark `make bench-scheduler` (`scheduler/bench.py`), tomados de `results/scheduler-benchmark.json` sin modificarlos y coherentes con la sección "Benchmark por tamaño y horizonte" de `docs/results.md`. Corrida del 2026-10-10, `code_version` `scheduler-0.1.0`, escenario `baseline`, semilla 42, sobre las poblaciones del generador 0.3.0 (oferta de duración variable con calentamiento). Las técnicas medidas están descritas en [scheduler-formulation.md §8.6](scheduler-formulation.md#86-técnicas-de-rendimiento-p9) y las decisiones del benchmark en [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador).

**Regenerado tras P18** (presupuesto de tiempo global del plan, citas congeladas y fase 4 con agendados fijos). Las cifras no son comparables una a una con las de versiones anteriores de este documento: cambiaron la oferta (generador 0.3.0) y el reparto del tiempo. Resumen de lo que muestra esta corrida:

- Todas las celdas hasta 50.000 × 2 semanas terminan `OPTIMAL`, dentro de `relative_gap_limit`.
- **50.000 × 4 semanas termina `FEASIBLE`** (brecha 0,496 %) y es la única celda donde el presupuesto se agotó: 27 fases terminaron por el límite de tiempo (advertencia `time_budget_exhausted`). Es un resultado desfavorable y se informa tal cual.
- La política optimizada no es peor que la voraz `priority` en el orden lexicográfico en ninguna celda; en 1.000 entradas es idéntica a ella.
- **No se corrió el barrido del presupuesto `B` = 60, 120 y 240**: todas las celdas usan `B` = 120. Está pendiente (`docs/backlog.md`); no se sabe cuánto cambiaría el plan de 50.000 × 4 con más o menos presupuesto.

## 1. Qué se mide y cómo

- **Celdas.** Combinaciones de tamaño de la lista de espera × horizonte del plan: 1.000, 10.000 y 50.000 entradas × 2 y 4 semanas. En cada celda se genera una corrida sintética propia en `data/bench/`, con el `horizon_weeks` del generador igual a las semanas del plan (la misma oferta semanal, repartida en el horizonte; decisión de [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador)), porque con la oferta de 26 semanas del generador las celdas chicas tendrían 0-1 bloques y el benchmark sería trivial (artefacto de la formulación §11.2).
- **Calibración.** La corrida de 1.000 entradas **no pasa la calibración estricta del generador** (`data.calibration_strict_failed`: `C3.iq.mediana` y `C5.nacional.media(mapeados)`, por tamaño de muestra). Se usa igual: el benchmark mide al programador, no la calibración. Las corridas de 10.000 y 50.000 sí la pasan.
- **Límite de tiempo.** `time_limit_s = 120`: presupuesto de tiempo determinista de **todo el plan** (primera pasada y expansión de frontera juntas), repartido entre subproblemas según sus pares y entre fases (formulación §8.5). `relative_gap_limit = 0,001` en las fases 3a y 3b. Modo determinista: búsqueda de un solo hilo (`num_workers = 8` solo rige con `deterministic = false`). Configuración por defecto completa en el JSON (`config_defaults`). El presupuesto con otros valores de `B` no se midió.
- **Máquina** (`machine` del JSON): macOS 27.0.1 arm64, 8 CPU, Python 3.12.13, OR-Tools 9.15.6755, polars 1.44.2.
- **Tiempos.** `solve_wall_s` es el tiempo real de todo `solve` (mediana de `repeats_all = 3` repeticiones de la variante completa; las ablaciones corren una vez). `deterministic_time_plan` es el tiempo determinista que CP-SAT reporta para los subproblemas del plan y `deterministic_time_total` agrega las pasadas de la primera pasada de la frontera que se descartaron (§8.6); coincide con el gasto de `solver.budget`. El tiempo determinista es la medida principal: el real varía con la carga de la máquina.

## 2. Tamaño del problema por celda

Pares: `pairs_all` = todas las entradas × todos los bloques del horizonte (un modelo sin preprocesar); `pairs_same_queue` = pares de la misma cola (lugar y especialidad); `pairs_compatible` = los que además cumplen duración y aviso mínimo (§4); `pairs_in_model` = los de las entradas candidatas tras el filtro (§8.2), que son las variables `x_ib` del plan. Niveles de sobrecupo: nominales frente a los que conserva la poda. Simetrías: clases de entradas intercambiables (entradas en clases) y de bloques (bloques en clases).

| Celda | Entradas | Bloques CNE / pab. | `pairs_all` | `pairs_same_queue` | `pairs_compatible` | `pairs_in_model` | Subproblemas | Subproblema mayor (pares) | Máx. variables | Sobrecupo nom./cons. | Clases simetría entradas / bloques |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 1.000 | 12 / 1 | 13.000 | 37 | 34 | 34 | 12 | 7 | 8 | 1 / 0 | 0 (0) / 0 (0) |
| 1.000 × 4 sem | 1.000 | 22 / 3 | 25.000 | 74 | 69 | 67 | 23 | 7 | 8 | 2 / 0 | 0 (0) / 0 (0) |
| 10.000 × 2 sem | 10.000 | 79 / 28 | 1.070.000 | 1.924 | 1.824 | 1.188 | 87 | 60 | 64 | 111 / 17 | 0 (0) / 0 (0) |
| 10.000 × 4 sem | 10.000 | 156 / 62 | 2.180.000 | 3.808 | 3.587 | 2.593 | 144 | 225 | 256 | 232 / 34 | 0 (0) / 0 (0) |
| 50.000 × 2 sem | 50.000 | 305 / 161 | 23.300.000 | 38.084 | 34.212 | 9.882 | 252 | 888 | 1.098 | 663 / 145 | 19 (38) / 0 (0) |
| 50.000 × 4 sem | 50.000 | 594 / 329 | 46.150.000 | 75.952 | 73.105 | 35.288 | 259 | 4.252 | 4.852 | 1.441 / 315 | 56 (113) / 2 (4) |

La frontera de candidatas se expandió en las celdas de 10.000 y 50.000 (colas alcanzadas: 2 en 10.000 × 2, 3 en 10.000 × 4, 11 en 50.000 × 2 y 30 en 50.000 × 4). Tras duplicar el margen siguió alcanzada en 3 colas en 50.000 × 2 (traumatología de pabellón de los servicios 3 y 11 y cirugía cardiovascular del 15) y en 3 en 50.000 × 4 (traumatología de pabellón de los servicios 3 y 33 y oftalmología CNE del 5); en las de 10.000, en ninguna. En las de 1.000 no hizo falta expandir.

## 3. Tiempo, estado y brecha de la variante completa (`optimized/all`)

| Celda | Estado | Brecha | `solve_wall_s` (mediana de 3) | Tiempo determinista plan / total | Presupuesto gastado de 120 | Fases terminadas por el límite | Presupuesto agotado |
|---|---|---|---|---|---|---|---|
| 1.000 × 2 sem | OPTIMAL | 0 | 0,01 s | 0,00 / 0,00 | 0,00 | 0 | no |
| 1.000 × 4 sem | OPTIMAL | 0 | 0,02 s | 0,00 / 0,00 | 0,00 | 0 | no |
| 10.000 × 2 sem | OPTIMAL | 0 | 0,13 s | 0,00 / 0,00 | 0,00 | 0 | no |
| 10.000 × 4 sem | OPTIMAL | 0,0004 % | 0,37 s | 0,03 / 0,03 | 0,03 | 0 | no |
| 50.000 × 2 sem | OPTIMAL | 0,0235 % | 9,04 s | 7,88 / 7,88 | 7,88 | 0 | no |
| 50.000 × 4 sem | FEASIBLE | 0,4960 % | 58,57 s | 42,28 / 56,43 | 56,43 | 27 | sí |

**El tamaño medio (10.000 entradas) se resuelve holgadamente dentro del límite**: 0,13 s (2 semanas) y 0,37 s (4 semanas) reales frente a 120, con estado `OPTIMAL` y brecha nula o despreciable (0,0004 % en 4 semanas). 50.000 × 2 termina `OPTIMAL` (brecha 0,0235 %, dentro de `relative_gap_limit`) con 7,88 unidades deterministas. 50.000 × 4 no cierra la brecha y termina `FEASIBLE` con 0,496 %; es la única celda con presupuesto agotado (27 fases por el límite). El gasto total de esa celda (56,43 de 120) queda por debajo del total pese a que 27 fases terminaron por el límite; una explicación posible, no medida, es que el límite se reparte por fase y por subproblema y una fase puede agotar su parte aunque sobre presupuesto en otras.

## 4. Comparación con la voraz `priority`

Deltas de `optimized_vs_priority.delta` (plan completo, con sobrecupo) menos la voraz `priority`. Enteros exactos.

| Celda | p1 agendados | GES cumplidas | GES a tiempo | Agendadas (CNE / pab.) | Suma de `c_ib` | ¿No peor lexicográfico? |
|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 1.000 × 4 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 10.000 × 2 sem | 0 | +2 | +1 | +12 (+8 / +4) | +34.532 | sí |
| 10.000 × 4 sem | +1 | +13 | +12 | +29 (+24 / +5) | +72.306 | sí |
| 50.000 × 2 sem | +11 | +46 | +54 | +122 (+88 / +34) | +639.240 | sí |
| 50.000 × 4 sem | +5 | +248 | +266 | +263 (+206 / +57) | +1.196.566 | sí |

Comparación sin sobrecupo (`optimized_without_overbooking_vs_priority`, como manda la decisión de comparar en igualdad de condiciones):

| Celda | p1 agendados | GES cumplidas | GES a tiempo | Agendadas (CNE / pab.) | Suma de `c_ib` | ¿No peor lexicográfico? |
|---|---|---|---|---|---|---|
| 1.000 × 2 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 1.000 × 4 sem | 0 | 0 | 0 | 0 (0 / 0) | 0 | sí |
| 10.000 × 2 sem | 0 | +2 | +1 | +4 (0 / +4) | +17.638 | sí |
| 10.000 × 4 sem | +1 | +13 | +12 | +5 (0 / +5) | +10.803 | sí |
| 50.000 × 2 sem | +10 | +45 | +54 | +34 (0 / +34) | +261.062 | sí |
| 50.000 × 4 sem | +5 | +248 | +266 | +57 (0 / +57) | +387.081 | sí |

Se reportan tal cual las diferencias pequeñas o nulas: en las dos celdas de 1.000 entradas el plan optimizado es idéntico a la voraz en todas las métricas, y en 10.000 × 2 sin sobrecupo la ganancia es pequeña (+4 agendadas, +2 GES cumplidas, +17.638 puntos). En ninguna celda la suma de `c_ib` queda bajo la voraz. Las ganancias grandes de agendadas con sobrecupo son casi todas CNE (sobreagendamiento); sin sobrecupo solo quedan las de pabellón. Las corridas sin sobrecupo terminan `OPTIMAL` en todas las celdas.

## 5. Ablación (celdas de 50.000)

Cada variante apaga una técnica (§8.6); `none` las apaga todas. Corre una sola vez (sin mediana). En las celdas de 1.000 y en 10.000 × 2 todas las variantes llegan al mismo `sum_coef` que la completa (95.399, 193.494 y 2.541.410 respectivamente para 1.000 × 2, 1.000 × 4 y 10.000 × 2, y todo `OPTIMAL`). En 10.000 × 4 todas terminan `OPTIMAL` pero el `sum_coef` varía en 2.180 puntos: 5.036.733 en `all` (igual en `without_objective_cut`, `without_symmetry_breaking` y `without_warm_start_frontier`), 5.036.707 sin poda de niveles, 5.036.494 sin pista de sobrecupo, 5.034.605 sin pistas y 5.034.553 en `none`. Con tiempos deterministas de 0,1 o menos, la ablación solo es informativa en 50.000.

### 50.000 × 2 semanas

| Variante | Estado | Brecha | Tiempo determinista total | `sum_coef` | Agendadas | Fases por el límite | Advertencias `worse_than_baseline` |
|---|---|---|---|---|---|---|---|
| `all` | OPTIMAL | 0,0235 % | 7,9 | 16.255.607 | 3.224 | 0 | 0 |
| `none` | OPTIMAL | 0,0102 % | 31,3 | 16.256.223 | 3.224 | 0 | 0 |
| `without_hints` | OPTIMAL | 0,0201 % | 7,1 | 16.255.555 | 3.224 | 0 | 0 |
| `without_objective_cut` | OPTIMAL | 0,0164 % | 7,1 | 16.255.756 | 3.224 | 0 | 0 |
| `without_overbooking_hint` | OPTIMAL | 0,0200 % | 11,2 | 16.255.799 | 3.224 | 0 | 0 |
| `without_prune_overbooking_levels` | OPTIMAL | 0,0219 % | 21,6 | 16.255.976 | 3.224 | 0 | 0 |
| `without_symmetry_breaking` | OPTIMAL | 0,0235 % | 7,8 | 16.255.607 | 3.224 | 0 | 0 |
| `without_warm_start_frontier` | OPTIMAL | 0,0234 % | 7,9 | 16.255.607 | 3.224 | 0 | 0 |

### 50.000 × 4 semanas

| Variante | Estado | Brecha | Tiempo determinista total | `sum_coef` | Agendadas | Fases por el límite | Advertencias `worse_than_baseline` |
|---|---|---|---|---|---|---|---|
| `all` | FEASIBLE | 0,4960 % | 56,4 | 33.392.317 | 6.951 | 27 | 0 |
| `none` | UNKNOWN | — (null) | 54,7 | 33.270.922 | 6.918 | 24 | 0 |
| `without_hints` | UNKNOWN | — (null) | 55,6 | 33.442.269 | 6.962 | 21 | 0 |
| `without_objective_cut` | FEASIBLE | 0,4356 % | 55,1 | 33.412.075 | 6.957 | 26 | 0 |
| `without_overbooking_hint` | FEASIBLE | 0,9432 % | 56,4 | 33.245.105 | 6.914 | 26 | 0 |
| `without_prune_overbooking_levels` | FEASIBLE | 0,9665 % | 56,6 | 33.333.417 | 6.939 | 27 | 0 |
| `without_symmetry_breaking` | FEASIBLE | 0,4687 % | 56,4 | 33.414.947 | 6.956 | 26 | 0 |
| `without_warm_start_frontier` | FEASIBLE | 0,4842 % | 55,9 | 33.396.970 | 6.954 | 26 | 0 |

Se reporta tal cual lo que sale al apagar técnicas, en cualquier dirección (las técnicas no cambian el óptimo, pero con brecha positiva o límite de tiempo sí cambian el plan entregado; [decisions.md §11](decisions.md#11-benchmark-y-rendimiento-del-programador)):

- **Apagar las pistas da el mejor objetivo en la celda mayor, pero sin cota**: `without_hints` en 50.000 × 4 logra el mejor `sum_coef` (33.442.269, +0,15 % sobre `all`) y agenda 11 más (6.962), con un tiempo determinista parecido (55,6 frente a 56,4) pero estado `UNKNOWN` sin brecha definida. Otras tres variantes superan levemente a `all` en `sum_coef`: `without_objective_cut`, `without_symmetry_breaking` y `without_warm_start_frontier`, las tres con brecha algo menor que la de `all` (0,436 %, 0,469 % y 0,484 % frente a 0,496 %).
- **La pista voraz con sobrecupo y la poda de niveles son las que más pesan al apagarse en 50.000 × 4**: sin la pista con sobrecupo, la brecha sube a 0,943 % y se agendan 37 menos (6.914); sin poda, la brecha es 0,966 % (la mayor entre las variantes con cota) y se agendan 12 menos (6.939).
- **`none` en 50.000 × 4** termina `UNKNOWN` en 3 subproblemas de la fase 3b, con el peor objetivo de la tabla (33.270.922) y 33 agendadas menos que `all` (6.918); esta vez no se emitió la advertencia `worse_than_baseline` (0 en todas las variantes).
- En 50.000 × 2 todas las variantes agendan 3.224 y todas terminan `OPTIMAL`. Apagar las técnicas sí cambia el tiempo: `none` gasta 31,3 unidades deterministas frente a 7,9 de `all`, sin poda de niveles 21,6 y sin pista de sobrecupo 11,2; las demás van entre 7,1 y 7,9. Cuatro variantes superan levemente el `sum_coef` de `all` (la mejor, `none`, por +616 puntos) y `without_hints` queda 52 puntos por debajo: las diferencias de objetivo son de un orden despreciable frente al total (16,3 millones), así que en esta celda la ablación muestra ganancia de tiempo de la poda y de la pista de sobrecupo, no de objetivo.

## 6. Limitaciones

- **Una sola máquina.** Todos los tiempos son del Mac arm64 de 8 núcleos descrito en la sección 1; el tiempo real varía con la carga. Por eso la medida principal es el tiempo determinista de CP-SAT.
- **La brecha de la fase 3b mide en parte la cota.** Con restricciones de indicador, la cota lineal de 3b es débil (ver `_gap_by_phase` en `scheduler/plan.py`; la poda de §8.6 la ajusta en parte): una brecha positiva no implica que la solución esté lejos del óptimo.
- **Presupuesto agotado en la celda mayor.** En 50.000 × 4 el plan depende de cuánto tiempo recibe cada fase; el barrido de `B` = 60, 120 y 240 no se ejecutó, así que la sensibilidad al presupuesto es desconocida.
- **Oferta sintética.** Las poblaciones usan la oferta de duración variable del generador 0.3.0 (formulación §11.2 y `docs/synthetic-data.md`). Las cifras no son comparables una a una con las de versiones anteriores de este documento.
- **La celda de 1.000 no es una población calibrada** (sección 1): sus números miden rendimiento, no representatividad.
- **Datos sintéticos.** Estas cifras validan que el programador escala y que sus técnicas funcionan sobre la estructura del generador; no dicen nada sobre tiempos ni ganancias con datos reales.
