# Diseño de la simulación de políticas (`simulation/`)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

La simulación compara cuatro políticas de agendamiento sobre la misma lista sintética, la misma oferta y las mismas llegadas, durante varios meses, con réplicas de semillas distintas. Mide lo que el programador no puede medir solo: qué pasa cuando los pacientes efectivamente asisten o faltan, se reprograman y salen de la lista.

Principio central: **la asistencia se sortea con la probabilidad verdadera del generador sintético** (`synthetic.noshow_truth.true_noshow_prob`), no con la predicha por `noshow/`. El programador ve solo la predicha (como en la realidad); el mundo responde con la verdadera. Así la ganancia del sobreagendamiento incluye el costo de los errores del modelo.

## 1. Alcance y supuestos

| Tema | Decisión | Motivo |
|---|---|---|
| Estado inicial | Stock de la corrida sintética (`waitlist_entry` en espera al `as_of`, con sus esperas) | Ya calibrado contra la Glosa 06; no hace falta calentamiento |
| Unidad de tiempo | Días; reloj SimPy `t = 0` el primer lunes posterior a `as_of` (`D_0`); los días entre `as_of` y `D_0` (a lo más 7) no tienen llegadas | Las citas, los plazos GES y las esperas son en días |
| Horizonte | 26 semanas de citas (configurable) | "A lo largo de meses"; costo acotado (§9) |
| Tamaño por defecto | 10.000 entradas, seed 42, escenario `baseline` | A ese tamaño el programador resuelve en < 1 s por semana (benchmark P9) |
| Réplicas | 5 réplicas, semillas `[101, 102, 103, 104, 105]` (configurables) | Varían llegadas y asistencia; el stock inicial es fijo |
| Concordancia | Servicio de salud (`match_level = health_service`), como el programador | |
| Egreso por atención | Toda atención (consulta o cirugía) resuelve la entrada | Simplificación: no se modelan controles ni derivación CNE → IQ |
| Abandono / causales administrativas | No se modelan por defecto (`abandon_weekly_rate = 0`) | No hay datos públicos por causal salvo "dos inasistencias" ([data-sources](data-sources.md)); se deja el parámetro para sensibilidad |

## 2. Llegadas

No hay series públicas de ingresos a la lista no GES en las fuentes verificadas (`data-sources.md`). Se usa el mismo supuesto con el que el generador dimensiona la oferta: **estado estacionario por la ley de Little**, `θ_{s,c} = 7·L_{s,c} / W̄_{s,c}` entradas por semana (stock `L` y espera media `W̄` por servicio y tipo, Glosa 06), más los casos GES nuevos anuales de la Superintendencia (`ytd_new_cases / 52`, repartidos por servicio según su stock GES), escalados por `size / L_universo` (`synthetic/capacity.py`, `_cells`).

- **Celdas.** `synthetic.capacity` expone `capacity_cells(t, a, cfg, entries) -> list[Cell]` (hoy `_cells`, privada) con dos campos nuevos: `throughput_per_week` (θ de la celda, entradas/semana) y `ges_throughput_per_week` (la parte GES). Una celda es (servicio, tipo de atención, especialidad). No cambia nada de lo que el generador escribe (digest idéntico).
- **Proceso.** Cada día `d` (a las `d + 0,25`) llegan `N_c ~ Poisson(θ_c / 7)` entradas a cada celda `c`. Cada llegada es GES con probabilidad `ges_θ_c / θ_c`.
- **GES por especialidad.** El generador reparte la tasa GES de cada (servicio, tipo) entre todas sus especialidades según el stock, también las que no tienen problemas GES. La simulación reasigna esa parte solo a las celdas con filas GES en el stock, en proporción a esas filas (la tasa total del grupo no cambia; si el grupo no tiene filas GES, llega como no GES), para que cada llegada GES copie procedimiento y plazo de su propia especialidad.
- **Atributos.** Cada llegada copia una fila del stock de su celda con la misma condición GES (sorteo uniforme con reemplazo; si la celda no tiene filas con esa condición, cualquier fila de la celda): `establishment_code`, `procedure_code`, `duration_min`, `clinical_priority`, `ges_problem`, y del paciente `age_group`, `insurance`, `commune_code`. Se crea un **paciente nuevo** (`patient_id` nuevo, sin historial) con fragilidad nueva `u ~ N(0, σ_u²)` (σ_u del manifiesto). `entry_date = d`; si es GES, `ges_deadline = d + (ges_deadline − entry_date de la fila donante)`.
- Se copia la fila completa para conservar las correlaciones conjuntas del generador. La prioridad clínica sigue siendo un dato de entrada sintético: se copia, nunca se infiere.
- **Sesgo conocido.** Dentro de una celda, la composición del stock no es exactamente la de las llegadas (las entradas que esperan más están sobrerrepresentadas). Como el generador sortea prioridad y atributos independientes de la espera, el sesgo se limita a la mezcla GES (corregida con `ges_θ`) y a la de procedimientos de duración distinta. Se reporta como limitación.

## 3. Oferta semanal

La simulación **no usa los `slot` del generador**: genera oferta para todas las semanas simuladas (más allá del horizonte del generador) y la escala con `capacity_multiplier`. Al diseñarla, además, el generador concentraba las sesiones CNE en una semana y los pabellones en lunes (artefacto §11.2 de la formulación, corregido después en el generador 0.2.0). Genera una oferta estacionaria con los mismos minutos por semana de cada celda (`Cell.minutes_per_week`, que ya incluyen la inasistencia esperada y, en pabellón, recambio y utilización):

- Sesiones por semana de la celda: `r_c = minutes_per_week / session_min` (240 CNE, 360 pabellón) × `capacity_multiplier` (1,0 por defecto; parámetro de sensibilidad). La semana `w` recibe `floor(r_c·(w+1) + φ_c) − floor(r_c·w + φ_c)` sesiones, con una fase `φ_c` distinta por celda (secuencia de Weyl con la razón áurea, en orden de servicio y especialidad). Sin la fase, toda celda con `r_c < 1` no tendría sesiones o las tendría todas en las mismas semanas (una primera implementación con reparto por resto mayor las concentraba en la misma semana, el mismo artefacto §11.2 del generador); con ella cada celda recibe `r_c` sesiones por semana en promedio y el total semanal queda cerca de `Σ r_c`.
- **Granularidad (limitación principal).** Cada sesión atiende una sola celda (servicio × especialidad). A 10.000 entradas hay 1.246 celdas CNE y 26,1 sesiones CNE por semana: en promedio una sesión por celda cada 48 semanas. En las 26 semanas simuladas solo 466 celdas CNE (37 %) reciben alguna sesión, y cubren el 76 % del stock CNE; en pabellón, 219 de 304 celdas y el 90 % del stock. El resto del stock no puede atenderse con ninguna política, y parte de los cupos queda sin uso porque la celda de la sesión tiene menos pacientes en espera que cupos. Es una consecuencia de escalar la red real (2,6 millones de entradas) a una muestra con sesiones indivisibles; pesa más cuanto menor es el tamaño. El JSON la reporta en `supply_coverage`. Sesiones más cortas la reducirían, pero dejarían sin espacio al sobrecupo (`O_b = floor(0,25·C_b)`), así que se mantienen las de 240 min.
- **CNE**: sesión de 240 min con `unit_min = Cell.unit_min`; posiciones lunes-viernes × mañana/tarde (08:30 y 14:00 locales) en ronda continua por celda (la sesión `k` de la celda va a la posición `k mod 10`); una agenda (`resource_id`) por cada 10 sesiones de la semana: `sim:{servicio}:{especialidad}:a{k // 10}`.
- **Pabellón**: bloque de 360 min a las 08:00 locales; días lunes-viernes en ronda continua por servicio (todas las especialidades del servicio comparten la ronda, ordenadas por código); un pabellón por cada 5 bloques del día: `sim:{servicio}:or{j}`.
- `establishment_code` del bloque: hospital del servicio por ronda ponderada con `hospital_complexity_weights` (como el generador). No afecta la compatibilidad con `match_level = health_service`.
- `slot_id = uuid5(run_id, f"sim-slot:{semana}:{índice}")`, determinista e idéntico en todas las políticas y réplicas. Zona horaria `America/Santiago`.

Con `capacity_multiplier = 1` la capacidad nominal iguala la demanda esperada después de inasistencias (`ρ ≈ 1`): la lista no tiende a vaciarse ni a explotar, y las diferencias entre políticas se notan. Hay dos desviaciones que la simulación revela en vez de esconder: la inasistencia efectiva no es la objetivo (la anticipación real de las citas es 7-11 días, no los 28 de referencia, y el término de espera cambia con la política), y las salidas por dos inasistencias reducen la demanda.

## 4. Ciclo semanal de agendamiento

Cada lunes `D_k` (`k = 0..T−1`, `D_0` = primer lunes posterior a `as_of`), a las `D_k + 0`:

1. **Entradas**: todas las de estado `waiting` (sin cita vigente). Puntaje S y `rank` con `priority.rank_frame(…, as_of=D_k)` (la espera crece cada semana).
2. **Bloques**: oferta de las semanas `[D_k + 7, D_k + 7 + 7·H)`, `H = horizon_weeks = 4`. `prebooked_units/min` con las citas vigentes en esos bloques (solo existen si `commit_weeks > 1`; el programador no sobreagenda sesiones con citas previas).
3. **Probabilidad predicha** (solo política con sobrecupo): `predict_noshow` del modelo entrenado sobre la corrida inicial (`models/<run_id>`), con `build_candidate_features` y un historial = historial sintético + citas simuladas **ya resueltas antes de `D_k`** (sin fuga; `noshow_from_frames` además corta el historial en la medianoche local de `as_of`). Nunca se pasa la probabilidad verdadera ni la fragilidad al programador.
4. **Grupos**: tabla `groups` (edad, previsión, comuna) de los pacientes en espera, para que los límites de exposición al sobrecupo por grupo (P6) rijan también en la simulación.
5. **Plan** según la política (§5) con `SchedulerConfig(horizon_weeks=4, commit_weeks=1, time_limit_s=30, solver=1 hilo determinista)`.
6. **Compromiso**: se confirman solo las citas del plan con `scheduled_start` en las primeras `commit_weeks` semanas (`[D_k + 7, D_k + 14)` con el valor por defecto 1) (horizonte deslizante, formulación §8.3). La entrada pasa a `booked`, con `booked_on = D_k`. El resto del plan se descarta y se replanifica el lunes siguiente.

`as_of = D_k` y `horizon_start = D_k + 7` en `SchedulingInstance.from_frames`; `min_lead_days = 7` del programador hace que toda cita confirmada tenga anticipación de 7 a 11 días.

## 5. Políticas

| Nombre | Llamada | Sobrecupo |
|---|---|---|
| `fifo` | `greedy_schedule(instance, cfg, order="fifo")` | No |
| `priority` | `greedy_schedule(instance, cfg, order="priority")` | No |
| `optimized` | `solve(instance, cfg)` con `overbooking.enabled = False` | No |
| `optimized_overbooking` | `solve(instance, cfg)` con `overbooking.enabled = True` (α = 0,10, límites por grupo por defecto) | Sí, solo CNE, con p predicha |

Las cuatro ven la misma instancia (salvo la tabla `noshow`) y las mismas restricciones duras del programador.

## 6. Asistencia, reprogramación y salida

Cada cita confirmada se resuelve el día de la cita a las `d + 0,5`:

- **Probabilidad verdadera**: `true_noshow_prob(features, frailty, params)` con `params = NoShowParams.from_json(manifiesto["params"]["noshow"])` (interceptos calibrados incluidos), y por cita: `intercept = α_{servicio, tipo}`, `specialty_code`, `age_group`, `insurance`, `wait_days = fecha de la cita − entry_date`, `median_wait_days` del grupo (`with_wait`), `lead_days = fecha de la cita − booked_on`, `frailty` del paciente (`patient_latent` para el stock; sorteada al llegar para los nuevos). Es el único lugar del paquete que llama a la verdad (`simulation/truth.py`).
- **Sorteo**: inasistencia si `U < p`, con `U` presorteado al crear la entrada, uno por intento (`U_{i,1}, U_{i,2}`). Así la misma entrada en el mismo intento usa el mismo número en todas las políticas (números aleatorios comunes), y la comparación es pareada.
- **Asiste** → `resolved` (sale de la lista por atención) en la fecha de la cita.
- **Falta** → `no_show_count += 1`. Si llega a `max_no_shows = 2` sale como `removed_no_show` (causal de egreso "dos inasistencias", Glosa 06); si no, vuelve a `waiting` con su `entry_date` original y espera el lunes siguiente.
- **Sesión CNE con sobrecupo**: todos los que asisten se atienden; si asisten más que `C_b`, el exceso es **desborde** (`overflow_units = max(0, asistentes − C_b)`), daño que se reporta. Pabellón no tiene sobrecupo.
- `abandon_weekly_rate > 0` (sensibilidad, apagado por defecto): cada lunes, antes de planificar, cada entrada `waiting` sale como `abandoned` con esa probabilidad (stream propio).

**Conservación**: en todo momento `stock inicial + llegadas = waiting + booked + resolved + removed_no_show + abandoned`, y cada transición queda en un registro de eventos con su causa (base del test P10-T3).

## 7. Métricas

Por réplica y política. Las series son semanales; los resúmenes, sobre las `T` semanas.

| Métrica | Definición |
|---|---|
| Tamaño de la lista | Entradas en `waiting` + `booked` cada lunes (y por separado `waiting`) |
| Espera de los atendidos | Mediana y p90 de `fecha de atención − entry_date` (días) |
| Espera del stock final | Mediana y p90 de `fin − entry_date` de las entradas que siguen en lista |
| GES incumplidas | Entradas GES cuyo plazo vence durante la simulación (`[D_0, D_0 + 7T)`) y que no se atendieron a más tardar ese día: siguen en lista, se atendieron tarde o salieron por dos inasistencias (una vez por entrada). Aparte: atendidas en plazo, ya vencidas al inicio y vencidas en lista al final |
| Uso de cupos | Sobre los bloques de las semanas con citas confirmables (`[D_0 + 7, D_0 + 7·(T + commit_weeks))`). CNE: `Σ min(asistentes_b, C_b) / Σ C_b`; pabellón: `Σ (duración + recambio de los atendidos) / Σ duración de bloques`; también la ocupación agendada |
| Cupos perdidos por inasistencia | Cupos que se habrían usado si los inasistentes hubieran venido. CNE: `Σ min(inasistentes_b, max(0, C_b − asistentes_b))`; pabellón: minutos (duración + recambio) de los inasistentes |
| Desborde | Sesiones con desborde, unidades de desborde y pacientes afectados (todos los asistentes de esas sesiones) |
| Sin cupo al llegar | Llegadas que en el primer plan después de su llegada no reciben ninguna cita en todo el horizonte del plan (no solo la semana confirmada) |
| Inasistencia | Tasa realizada (verdad) por tipo; en `optimized_overbooking`, p predicha media frente a la realizada en las citas con p |
| Salidas | Por atención, por dos inasistencias (comparable con el 3,04 % de egresos CNE por esa causal, `noshow_e_p2_cne_target`), por abandono |
| Programador | Estados por fase (OPTIMAL/FEASIBLE/UNKNOWN), brecha máxima y tiempo por semana |

**Por grupo** (las dimensiones de P6, `GroupLimitsConfig`: `age_group`, `insurance`, `commune_code`; grupos con al menos 30 entradas): entradas, atendidos, tasa de atención, mediana y p90 de espera de los atendidos, GES incumplidas, inasistencia realizada, salidas por dos inasistencias, exposición al sobrecupo (proporción de citas en sesiones con sobrecupo) y proporción de asistentes en sesiones con desborde. Se reporta la brecha máxima entre grupos de cada dimensión.

**Agregado entre réplicas**: media, desviación estándar, mínimo, máximo e IC 95 % (t de Student, `n = réplicas`) de cada métrica resumen. **Comparaciones pareadas** (misma réplica, números comunes): diferencia `política − fifo`, `política − priority` y, para aislar el sobrecupo, `optimized_overbooking − optimized`, con media, IC 95 % y en cuántas réplicas mejora. La dirección de cada métrica (mayor o menor es mejor) está declarada en `report.DIRECTION`; los conteos de contexto (llegadas, `n`) no tienen dirección. Las diferencias desfavorables se reportan igual que las favorables.

## 8. Salida y CLI

`prioriza-simulate` (Typer) y `make simulate` → `results/simulation.json`:

```
disclaimer, generated_at, code_version, run {id, size, seed, scenario, as_of},
noshow_model_version, truth_source, config {...}, replica_seeds, supply_coverage,
replicas: [{seed, policies: {<política>: {summary, weekly: [...], groups, scheduler}}}],
aggregate: {<política>: {<métrica>: {mean, sd, min, max, ci95_low, ci95_high, n}}},
comparisons: {"<política>_vs_<base>": {<métrica>: {mean_diff, ci95_low, ci95_high, better_in}}},
limitations: [...], timing: {...}
```

`timing` y `generated_at` son las únicas partes que cambian entre corridas con la misma semilla. La CLI genera la corrida sintética (con el horizonte por defecto del generador, 26 semanas, cuya oferta no se usa, para reutilizar la misma corrida con cualquier `--weeks`) y entrena el modelo (en `data/simulation/`, como el benchmark), con opciones `--size`, `--seed`, `--scenario`, `--weeks`, `--replicas`/`--replica-seeds`, `--horizon-weeks`, `--time-limit`, `--policies`, `--capacity-multiplier`, `--abandon-weekly-rate`, `--work-dir`, `--out`.

## 9. Implementación

- **Núcleo puro en memoria**: `World` (stock, pacientes con fragilidad, celdas de llegada y oferta, parámetros de la verdad, medianas, historial, catálogos, modelo) se arma una vez con `world_from_run(run_dir, model_path)`; `simulate(world, policy, config, seed) -> PolicyResult` no lee archivos. Los tests arman mundos chicos a mano.
- **SimPy**: procesos de llegadas (diario), planificador (lunes) y una cita por proceso o un proceso diario que resuelve las citas del día; prioridades por hora del día: planificación `+0`, llegadas `+0,25`, citas `+0,5`.
- **Streams**: `numpy.random.SeedSequence(seed)` con hijos fijos por propósito (llegadas, atributos, fragilidad, asistencia, abandono). Llegadas y asistencia no dependen de la política (números comunes). Un hilo de CP-SAT en modo determinista.
- **Adaptadores**: `scheduler/adapters.py` separa la lógica de `entries_frame` y `noshow_frame` en versiones que reciben DataFrames (`entries_from_frames`, `noshow_from_frames`); las versiones con `run_dir` las envuelven. La simulación usa las de DataFrames.
- **Costo medido**: 10.000 × 26 semanas × 4 políticas con una réplica, 74 s (15-21 s por política); las 5 réplicas, unos 6 min.
- Dependencia nueva: `simpy` en `simulation` (justificada en `docs/decisions.md` §12).

## 10. Limitaciones

- Granularidad de la oferta a tamaños chicos (§3): a 10.000 entradas una cuarta parte del stock CNE no tiene ninguna sesión de su celda en 26 semanas.
- Llegadas por Little en estado estacionario: sin estacionalidad, sin tendencia y con la espera media de un solo corte.
- La oferta replica la del generador (`capacity_multiplier` 1,0, sin margen) y es igual todas las semanas; no hay feriados, suspensiones de pabellón ni ausentismo de especialistas.
- Sin abandono ni otras causales administrativas por defecto; sin controles posteriores ni derivación a cirugía.
- El modelo de inasistencias no se reentrena durante la simulación.
- La verdad de inasistencia es la del generador: las conclusiones valen para ese mundo sintético, no para la red real.
