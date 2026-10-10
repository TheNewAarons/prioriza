# Formulación del programador (CP-SAT)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Este documento especifica el modelo de `scheduler/`: qué entra, qué variables y restricciones tiene, cómo se resuelve, qué se reporta y un ejemplo resuelto a mano. Está escrito para implementarse sin decisiones abiertas; donde hay un valor por defecto, se da con su motivo. Los parámetros se marcan como `config.<nombre>` y se resumen en la [sección 12](#12-configuración).

El sistema apoya, no decide: todo plan se guarda en `schedule_run` con `review_status = pending` y requiere revisión humana.

## 1. Alcance y principios

1. **Unidad de asignación: entrada por bloque.** Un cupo es un `slot` del modelo de datos: una sesión CNE de 240 min (12 consultas de 20 min) o un bloque de pabellón de 360 min. El modelo decide qué entradas van a qué bloque; la hora exacta dentro del bloque se fija después con una regla determinista ([sección 9](#9-postproceso-secuencia-banderas-y-verificación)). Así se eliminan las variables de posición y su simetría.
2. **El puntaje viene de P4 y no se toca.** El objetivo usa el puntaje `S` de `priority.score_entry` y el orden de `priority.rank`, calculados con la misma `as_of` y las mismas reglas (se registra `rules_digest`). El programador nunca recalcula ni modifica la prioridad clínica.
3. **La probabilidad de inasistencia solo habilita sobrecupos.** `p` entra únicamente en la restricción de riesgo del sobreagendamiento. No entra al objetivo y no puede desplazar a nadie: el sobreagendamiento solo agrega pacientes al plan sin sobrecupo ([sección 6.4](#64-el-sobrecupo-solo-agrega)).
4. **GES dura cuando es factible; si no, se informa.** Las garantías vencidas o que vencen dentro del horizonte se cumplen siempre que exista una forma de hacerlo. Las que no se pueden cumplir salen en el informe con su causa. El modelo nunca es infactible por GES.
5. **Atributos de equidad solo como límites.** Grupo etario, previsión y comuna entran solo en los límites de daño por grupo (contrato con P6) y en el informe. Nunca en el objetivo ni en `p`.
6. **Nunca falla en silencio.** Cada fase registra su estado de CP-SAT, valor, cota y brecha. Siempre hay un plan factible: la política `priority` (voraz) es factible en la fase 1 y cada fase recibe como pista una solución que cumple todo lo fijado antes ([sección 8.1](#81-fases-lexicográficas)).

## 2. Entradas

Todas las entradas son `polars.DataFrame` validados al construir la instancia. El núcleo de `scheduler` (`instance`, `prepare`, `cpsat`, `solve`, `plan`, `greedy`, `risk`) no lee la base de datos ni importa `noshow` ni scikit-learn. Los módulos de borde arman estas tablas y guardan el plan: `adapters` (parquet de una corrida sintética, P4 y modelo de inasistencias), `persist` (`schedule_run` y `appointment`) y `cli`. El núcleo nunca los importa.

### 2.1 Instancia

| Campo | Tipo | Contenido |
|---|---|---|
| `as_of` | `date` | Fecha de decisión (la misma del ranking P4). |
| `horizon_start` | `date` | Primer día del horizonte (por defecto `synthetic_run.params.horizon_start`; en la simulación, el lunes de la semana que se planifica). |
| `horizon_weeks` | `int` | `config.horizon_weeks`, por defecto 4. Horizonte `[horizon_start, horizon_end)`, `horizon_end = horizon_start + 7·horizon_weeks` días. |
| `rules_digest`, `rules_version` | `str` | Identidad de las reglas P4 usadas para `S` y el orden. |
| `noshow_model_version` | `str \| None` | Versión del modelo que produjo `p` (`None` si el sobrecupo está apagado). |
| `seed` | `int` | Semilla de CP-SAT (`random_seed`). |

Fechas de bloque: `local_date_b` es la fecha local en `America/Santiago` de `start_at`. `day_b = (local_date_b − horizon_start).days`. `H = 7·horizon_weeks`.

### 2.2 Tablas

**`entries`** (una fila por entrada en espera; solo `status = waiting`):

| Columna | Origen |
|---|---|
| `entry_id`, `patient_id` | `waitlist_entry` |
| `health_service_code`, `establishment_code`, `specialty_code`, `care_type`, `procedure_code` | `waitlist_entry` |
| `duration_min` | `procedure.duration_min` |
| `clinical_priority`, `is_ges`, `ges_deadline`, `entry_date` | `waitlist_entry` (`entry_date` solo para la política `fifo`) |
| `score` | `PriorityScore` de P4, `S ∈ [0, 100]` |
| `rank` | Puesto en su cola según `priority.rank_frame` (partición servicio, especialidad, tipo) |

**`blocks`** (una fila por `slot` con `local_date` dentro del horizonte):

| Columna | Origen |
|---|---|
| `slot_id`, `resource_id`, `resource_kind` | `slot`, `resource.kind` |
| `health_service_code`, `establishment_code` | `resource` |
| `specialty_code`, `start_at`, `duration_min`, `unit_min` | `slot` |
| `prebooked_units` (CNE) / `prebooked_min` (pabellón) | Citas ya existentes en el bloque (`appointment.status = scheduled`), por ejemplo las congeladas de una planificación anterior en la simulación |

**`noshow`** (una fila por par compatible CNE; obligatoria si `config.overbooking.enabled`): `entry_id`, `slot_id`, `p`. Se calcula con `noshow.build_candidate_features` + `noshow.predict_noshow`, con `scheduled_start = start_at` del bloque, `lead_days = (local_date_b − as_of).days` y el historial observado hasta `as_of`. Se recorta a `[0,001; 0,95]` para que los logaritmos estén definidos. Para pares de pabellón es opcional y solo se usa para llenar `appointment.predicted_noshow_prob`.

**`groups`** (una fila por paciente): `patient_id`, `age_group`, `insurance`, `commune_code`. Solo para límites de equidad e informe.

**`busy`** (opcional; una fila por paciente y día): `patient_id`, `local_date` (fecha local en `America/Santiago`, de tipo fecha y no fecha-hora). Días del horizonte en que el paciente ya tiene una cita confirmada, de cualquier bloque, especialidad o lugar: en `make schedule`, las citas `appointment.status = scheduled` con `origin ≠ history` (`adapters.busy_frame`); en la simulación, las citas congeladas de planificaciones anteriores que caen en el horizonte (solo existen con `commit_weeks ≥ 2`). Las `prebooked_*` de `blocks` descuentan la capacidad del bloque; `busy` descuenta el día del paciente (R4, [sección 4](#4-compatibilidad)).

## 3. Conjuntos y parámetros

| Símbolo | Definición |
|---|---|
| `I` | Entradas candidatas (tras el filtro de la [sección 8.2](#82-filtro-de-candidatos)). |
| `B = B^C ∪ B^O` | Bloques CNE (`specialist_agenda`) y de pabellón (`operating_room`). |
| `P` | Pacientes; `I(p)` sus entradas. |
| `Π ⊆ I × B` | Pares compatibles ([sección 4](#4-compatibilidad)). `B(i) = {b : (i,b) ∈ Π}`, `I(b) = {i : (i,b) ∈ Π}`. |
| `s_i` | `round(100·S_i) + 100` ∈ [100, 10100]. El +100 hace que agendar a cualquiera sume al menos 1 punto, de modo que el plan no deja cupos vacíos por un puntaje 0. |
| `u_i` | Unidades CNE de la entrada: `ceil(duration_min_i / unit_min_b)`. En los datos actuales vale 1 siempre. |
| `C_b` | Capacidad CNE residual: `max(0, floor(duration_min_b / unit_min_b) − prebooked_units_b)` (12 en una sesión vacía). Una sesión con `prebooked_units_b > 0` no admite sobrecupo (`O_b = 0`): el riesgo R10/R11 no conoce la `p` de esas citas. |
| `L_b` | Minutos de pabellón planificables: `floor(config.or_max_fill · duration_min_b) − prebooked_min_b` (306 en un bloque vacío). |
| `d_i`, `τ` | Duración del procedimiento y recambio `config.or_turnover_min` (30). |
| `O_b` | Máximo de sobrecupos del bloque CNE: `floor(config.overbooking.max_fraction · C_b)` (3 en un bloque de 12); 0 en pabellón. |
| `p_ib` | Probabilidad de inasistencia de `i` en el bloque `b`. |
| `G` | GES obligadas: `is_ges` y `ges_deadline < horizon_end`. `G^od ⊆ G`: `ges_deadline < horizon_start` (vencidas o que vencen antes de que empiece el horizonte). `G^dl = G \ G^od`. |
| `D_g` | `ges_deadline`. |
| `first_g` | `min{local_date_b : b ∈ B(g)}`: primera fecha en que `g` puede atenderse. |
| `Q1` | Entradas con prioridad en `rules.ges_strict.yield_to_priorities` (por defecto, p1). Vacío si la lista está vacía. |
| `busy(p, t)` | 1 si el paciente `p` ya tiene una cita confirmada el día local `t` (tabla `busy`), 0 si no. |

## 4. Compatibilidad

`(i, b) ∈ Π` si y solo si se cumplen todas:

1. `specialty_code_b = specialty_code_i` (la especialidad determina el tipo de atención; se verifica además `resource_kind` coherente con `care_type`: `specialist_agenda ↔ consultation`, `operating_room ↔ surgery`, y si no se cumple se lanza error porque es un dato corrupto).
2. Mismo lugar según `config.match_level`:
   - `health_service` (por defecto): `health_service_code_b = health_service_code_i`. Es la misma cola de P4 (servicio, especialidad, tipo) y supone derivación dentro de la red del servicio.
   - `establishment`: `establishment_code_b = establishment_code_i`. Más realista para la interconsulta individual, pero en la corrida canónica deja 44.793 pares en vez de 238.338 en 4 semanas; se ofrece como análisis de sensibilidad.
3. Duración: CNE `u_i ≤ C_b`; pabellón `d_i + τ ≤ L_b`.
4. Aviso mínimo: `local_date_b ≥ as_of + lead_i`, con `lead_i = config.ges_min_lead_days` (2) si `i ∈ G` y `config.min_lead_days` (7) si no. El historial sintético tiene avisos de 7 a 90 días; avisos de 2 a 6 días extrapolan el modelo de inasistencias, lo que se declara en el informe.
5. `local_date_b ∈ [horizon_start, horizon_end)`.
6. Día libre: `busy(p_i, local_date_b) = 0`. Equivale a R4 con lado derecho `1 − busy(p, t)`: en un día ocupado el paciente no admite ninguna cita nueva, y en los demás R4 no cambia. Filtrarlo aquí evita variables y hace que la política optimizada y las voraces lo respeten igual. El informe cuenta los pares descartados por esta regla (`summary.pairs_dropped_patient_day_busy`). `first_g` se calcula después de este filtro.

Las entradas con `B(i) = ∅` no entran al modelo; se cuentan por cola en el informe (si la causa es el punto 6, con `patient_day_busy`) y, si son GES obligadas, se reportan con causa ([sección 7](#7-informe-de-ges-no-cumplidas)).

## 5. Variables

| Variable | Dominio | Significado |
|---|---|---|
| `x_ib`, `(i,b) ∈ Π` | {0,1} | La entrada `i` va al bloque `b`. |
| `a_i = Σ_{b∈B(i)} x_ib` | expresión | `i` queda agendada. |
| `v_g`, `g ∈ G` | {0,1} | La garantía `g` no se cumple (holgura). |
| `k_bo`, `b ∈ B^C`, `o ∈ {0..O_b}` | {0,1} | El bloque `b` tiene exactamente `o` sobrecupos (solo en la fase 3b). |
| `w_qb` | entero ≥ 0 | Exposición del grupo `q` en el bloque `b` (solo con límites de equidad activos, [sección 6.5](#65-límites-por-grupo-contrato-con-p6)). |

## 6. Restricciones

### 6.1 Duras siempre

```
(R1) a_i ≤ 1                                        ∀ i ∈ I          a lo más un bloque por entrada
(R2) Σ_{i∈I(b)} u_i·x_ib ≤ C_b + Σ_o o·k_bo           ∀ b ∈ B^C       capacidad CNE (Σ_o o·k_bo = 0 sin sobrecupo)
(R3) Σ_{i∈I(b)} (d_i + τ)·x_ib ≤ L_b                 ∀ b ∈ B^O       minutos de pabellón
(R4) Σ_{i∈I(p)} Σ_{b∈B(i): local_date_b = t} x_ib ≤ 1  ∀ p con |I(p)| ≥ 2, ∀ fecha t   una cita por paciente por día
```

R3 cuenta el recambio después de cada caso, también del último, porque el pabellón debe quedar listo dentro del bloque. `config.or_max_fill = 0,85` replica el supuesto `iq_utilization` del generador: la capacidad se dimensionó suponiendo que en promedio solo el 85 % del bloque se usa; planificar al 100 % daría un rendimiento mayor que el que calibra la ley de Little.

R4 se genera solo para pacientes con más de una entrada (13.657 de 85.083 en la corrida canónica) y solo para fechas en que dos o más de sus entradas tienen bloques. `config.max_per_patient_per_day = 1`. Las citas ya confirmadas (`busy`) entran por la compatibilidad ([sección 4](#4-compatibilidad), punto 6): con ellas el lado derecho de R4 es `1 − busy(p, t)`.

### 6.2 GES (dura si es factible)

```
(R5) Σ_{b∈B(g): local_date_b ≤ D_g} x_gb + v_g ≥ 1     ∀ g ∈ G^dl     dentro de plazo
(R6) a_g + v_g ≥ 1                                    ∀ g ∈ G^od     vencida: agendar en el horizonte
```

Si el conjunto de la suma es vacío, `v_g` se fija en 1 antes de resolver y la causa se registra. Lo mismo vale para `g ∈ G^od` con `as_of ≤ D_g < horizon_start`: vence antes de que empiece el horizonte, así que el plazo legal ya no se puede cumplir (causa `deadline_before_first_block`). Para una `g ∈ G^od` con `D_g < as_of` (vencida antes de la decisión), cumplir la obligación significa agendarla dentro del horizonte; el informe muestra igual su atraso ([sección 7](#7-informe-de-ges-no-cumplidas)). La fase 2 minimiza `Σ v_g` y la fija; las fases siguientes no pueden empeorarla. Así, "dura cuando es factible" queda exacto: el número de garantías incumplidas es el mínimo posible dado lo ya fijado en la fase 1 (cesión a p1).

Una garantía con `v_g = 1` puede igual agendarse fuera de plazo; su atraso se penaliza en el objetivo ([sección 6.6](#66-objetivo)).

Diferencia con P4: el nivel estricto de P4 usa 14 días (`due_soon_days`) para ordenar. El programador obliga a toda GES que vence antes del fin del horizonte, porque dentro del horizonte sí puede verificar si hay cupo antes del plazo.

### 6.3 Sobreagendamiento (solo CNE, fase 3b)

Por defecto el sobrecupo se permite solo en sesiones CNE. En pabellón no hay sobrecupo: un caso extra que se presenta alarga el bloque o desplaza una cirugía, y la inasistencia quirúrgica sintética es baja (intercepto logit ≈ −3,5, p ≈ 3 %). En su lugar, el plan entrega una lista de reemplazo por bloque de pabellón ([sección 9](#9-postproceso-secuencia-banderas-y-verificación)).

Para cada `b ∈ B^C`:

```
(R7) Σ_{o=0}^{O_b} k_bo = 1
(R8) k_b0 ⇒ Σ_i x_ib ≤ C_b            (ya implícito en R2)
(R9) k_bo ⇒ Σ_i x_ib = C_b + o         o ≥ 1
```

El sobrecupo exige `u_i = 1` para todo `i ∈ I(b)`; si algún candidato del bloque tiene `u_i > 1`, se fija `k_b0 = 1`.

**Riesgo.** Con `n = C_b + o` pacientes en el bloque y `K` = número de inasistencias (suma de Bernoulli independientes de parámetros `p_ib`), el bloque se desborda si asisten más de `C_b`, es decir si `K ≤ o − 1`. El límite explícito es:

```
P(K ≤ o − 1) ≤ α        α = config.overbooking.alpha (0,10)
```

Esta probabilidad no es lineal en `x`. Se impone una condición suficiente lineal, exacta para `o = 1`:

- **o = 1.** `P(K = 0) = Π(1 − p_ib)`. Tomando logaritmos, la condición exacta es lineal:
  ```
  (R10) k_b1 ⇒ Σ_i A_ib·x_ib ≥ R1        A_ib = floor(10⁴ · (−ln(1 − p_ib)))
                                         R1   = ceil(10⁴ · ln(1/α))
  ```
- **o ≥ 2.** Cota de Chernoff: para todo `θ > 0`, `P(K ≤ k) ≤ e^{θk} · Π_i (1 − p_i + p_i e^{−θ})`. Con `k = o − 1`:
  ```
  (R11) k_bo ⇒ Σ_i A^θ_ib·x_ib ≥ R^θ_o   A^θ_ib = floor(10⁴ · (−ln(1 − p_ib(1 − e^{−θ}))))
                                        R^θ_o  = ceil(10⁴ · (θ·(o − 1) + ln(1/α)))
  ```
  `θ = θ_bo` se fija antes de resolver para que la cota sea ajustada en un bloque típico: con `p̄_b` = media de `p_ib` sobre `I(b)` y `n = C_b + o`, `e^{−θ} = k(1 − p̄_b) / ((n − k)·p̄_b)`. Si ese valor es ≥ 1 (se esperan menos de `k` inasistencias), `k_bo` se fija en 0.

El redondeo (`floor` a la izquierda, `ceil` a la derecha) hace que la condición entera implique la real; la verificación exacta de la [sección 9](#9-postproceso-secuencia-banderas-y-verificación) lo comprueba. La cota de Chernoff es conservadora (en un bloque de 12 con `p = 0,3` deja pasar `o = 2` solo si el riesgo exacto es bastante menor que `α`), por eso en la práctica casi todo sobrecupo será `o = 1`. Se acepta: es la opción segura y explicable.

Orden de magnitud: con `C = 12` y todos con `p = 0,15`, un sobrecupo tiene riesgo exacto `0,85¹³ = 0,121 > 0,10`; no se permite. Hace falta una sesión con más inasistencia esperada (por ejemplo, media de `p` ≥ 0,163) para que pase. `α` es el parámetro que el simulador debe barrer (`{0,05; 0,10; 0,20}`).

### 6.4 El sobrecupo solo agrega

La fase 3a resuelve el problema sin sobrecupo y deja el conjunto agendado `S0`. La fase 3b agrega:

```
(R12) a_i = 1                                ∀ i ∈ S0
(R13) Σ_{i∈I(b) \ S0} x_ib ≥ Σ_o o·k_bo        ∀ b ∈ B^C
```

R12 garantiza que `p` nunca saca a nadie que habría tenido cupo: el sobreagendamiento solo suma pacientes (puede mover a los de `S0` de bloque). R13 hace que cada sobrecupo lo ocupe alguien que entró gracias al sobreagendamiento; esa persona recibe la bandera `is_overbooked` ([sección 9](#9-postproceso-secuencia-banderas-y-verificación)). Las entradas de `Q1` y `G` agendadas en la fase 3a están en `S0`, así que nunca quedan marcadas como sobrecupo.

### 6.5 Límites por grupo (contrato con P6)

El daño del sobreagendamiento es la **exposición**: estar citado en un bloque con sobrecupo, donde todos los asistentes comparten el riesgo de desborde (espera extra). P6 definirá los límites; mientras no exista, rigen estos valores por defecto, y P6 puede reemplazarlos sin cambiar la formulación:

```yaml
group_limits:
  dimensions: [age_group, insurance, commune_code]
  mode: relative            # relative | absolute
  max_gap_pp: 5.0           # relative: share_q ≤ share_global + 5 pp
  max_share: null           # absolute: share_q ≤ max_share
  min_group_n: 30           # grupos con menos candidatos CNE en el subproblema no se limitan (sí se informan)
```

`share_q` = (agendados de `q` en bloques CNE con sobrecupo) / (agendados de `q` en bloques CNE). Formulación lineal para cada grupo `q` limitado (pares dimensión-valor con al menos `min_group_n` candidatos CNE en el subproblema), con tope `ρ_q`:

```
E_qb = Σ_{i∈I(b)∩q} x_ib                                    agendados de q en b
z_b  = 1 − k_b0                                             b tiene sobrecupo
(R14) w_qb ≥ E_qb − (C_b + O_b)·(1 − z_b),   w_qb ≥ 0       w_qb ≥ E_qb si z_b = 1
(R15) 1000·Σ_b w_qb ≤ round(1000·ρ_q) · Σ_b E_qb
```

Basta la cota inferior de `w_qb` porque R15 solo la acota por arriba. Se crean variables por (grupo, bloque), no por par.

- `mode: absolute`: `ρ_q = max_share`. Una sola pasada.
- `mode: relative`: la brecha relativa no es lineal (el promedio global también es variable). Se resuelve en dos pasadas: la fase 3b corre sin R14-R15 y mide `share_global` y `share_q`; si algún grupo supera `share_global + max_gap_pp`, se repite la fase 3b con `ρ_q = share_global + max_gap_pp/100` para todos los grupos limitados. La segunda pasada puede bajar `share_global`; el informe muestra ambas pasadas y la brecha final, aunque quede por encima del límite relativo (solo el tope absoluto de la segunda pasada está garantizado).

Los límites se aplican por subproblema ([sección 8.3](#83-descomposición)). Eso es más estricto que un límite global y por eso seguro. El informe además reporta, por grupo y en el total: candidatos, agendados, tasa de agendamiento, `share_q`, proporción con bandera de sobrecupo y riesgo exacto medio de los bloques a los que están expuestos. Esto importa porque el modelo de inasistencias sobreestima 65+ (+2,3 pp) y subestima Arica e Iquique ([model card](noshow-model-card.md)): sin límites, el sobrecupo se concentraría en personas mayores.

Los límites no son una variable del puntaje ni de `p`: solo acotan el daño. Si un límite activo deja a alguien sin sobrecupo, el informe lista cuántos límites quedaron activos (holgura cero en R15) por grupo.

### 6.6 Objetivo

Coeficiente por par, todo entero y precalculado:

```
early_ib = round(s_i · e · day_b / H)                         e = config.weights.earliness (0,05)
delay_ib = 100 · w_D · max(0, (local_date_b − max(D_i, first_i)).days)   solo i ∈ G; w_D = config.weights.ges_delay_points_per_day (1,0)
c_ib     = max(1, s_i − early_ib − delay_ib)
```

- **Puntaje (principal).** `Σ c_ib·x_ib` maximiza la suma de puntajes P4 agendados.
- **Anticipación.** Agendar al final del horizonte cuesta hasta `e` = 5 % del puntaje; dentro de lo que cabe, los de mayor puntaje van antes. Con `e < 1` un paciente siempre suma.
- **Atraso GES.** Cada día de atraso evitable respecto del plazo cuesta `w_D` puntos de prioridad. Se mide desde `max(D_i, first_i)`, de modo que el atraso inevitable (antes del primer bloque posible) no castiga agendar a una GES vencida. El `max(1, ·)` evita que el atraso haga preferible no agendar a una GES.
- **Uso equilibrado de recursos (fase 4).** No se pondera contra el puntaje: es un desempate lexicográfico, para que equilibrar nunca deje a un paciente sin cupo. Para cada grupo `Γ` = (subproblema, especialidad, tipo de recurso), con utilización `util_b = 1000·n_b / C_b` (CNE, `n_b` incluye sobrecupos) o `1000·Σ(d_i + τ)x_ib / L_b` (pabellón):
  ```
  BAL = Σ_Γ ( max_{b∈Γ} util_b − min_{b∈Γ} util_b )
  ```
  modelado con `AddMaxEquality` y `AddMinEquality` sobre variables enteras `util_b` (`util_b` se define con `AddDivisionEquality` o, mejor, con la igualdad lineal `C_b·util_b ≤ 1000·n_b < C_b·(util_b + 1)`).
  `config.weights.balance_tolerance` (0,0) permite perder hasta esa fracción del objetivo de la fase 3 a cambio de equilibrio; con 0 es un desempate puro.

## 7. Informe de GES no cumplidas

Cada `g ∈ G` con `v_g = 1` en la solución final sale en `ges_unmet` con un código de causa, la primera que aplique en este orden:

| Código | Condición (determinista) | Momento |
|---|---|---|
| `no_block_in_horizon` | No hay ningún bloque de su especialidad y servicio en el horizonte (antes del filtro de aviso y duración). | Antes de resolver |
| `duration_exceeds_blocks` | Hay bloques, pero `d_g + τ > L_b` en todos. | Antes de resolver |
| `deadline_before_first_block` | `G^dl`: ningún bloque de su especialidad y lugar que quepa cae en o antes de `D_g` (sin mirar el aviso); o `G^od` con `D_g ≥ as_of`: vence antes de que empiece el horizonte. | Antes de resolver |
| `lead_time` | Hay bloques antes del plazo, pero ninguno cumple `ges_min_lead_days`. | Antes de resolver |
| `patient_day_busy` | Hay bloques que cumplirían la obligación con el aviso mínimo (en `G^dl`, hasta `D_g`; en `G^od`, en todo el horizonte), pero el paciente ya tiene una cita confirmada (`busy`) en todos esos días ([sección 4](#4-compatibilidad), punto 6). Puede quedar agendada fuera de plazo en otro día. | Antes de resolver |
| `capacity_taken` | Todos los bloques que la cumplirían están llenos. Se detalla quién los ocupa: p1 cedidos (fase 1), otras GES (y cuántas con plazo anterior o igual) y el resto. | Después de resolver |
| `patient_conflict` | Algún bloque que la cumpliría tiene capacidad libre, pero el paciente tiene otra cita ese día (R4) en todos esos días. | Después de resolver |
| `solver_limit` | Hay capacidad libre sin conflicto y la fase 2 no terminó en `OPTIMAL`: el incumplimiento puede deberse al tiempo límite. Se informa como advertencia. | Después de resolver |
| `decomposition` | Hay capacidad libre sin conflicto, fase 2 en `OPTIMAL`, pero el subproblema se resolvió con el respaldo por especialidad o por semana ([sección 8.3](#83-descomposición)), que no es exacto. | Después de resolver |
| `overbooking_interaction` | Hay capacidad libre sin conflicto, fase 2 en `OPTIMAL`, pero el plan final tiene la fase 3b: moverla rompería R9 o R12-R15 (por ejemplo, sacarla de un bloque con sobrecupo dejaría el bloque con menos pacientes de los que fija `k_bo`). | Después de resolver |

"Lleno" se mide por entrada: el bloque está lleno para `g` si su carga más la de `g` supera `C_b` o `L_b`. Si ninguna causa aplica (fase 2 en `OPTIMAL`, descomposición exacta y sin fase 3b), es un error de implementación: se lanza excepción con los bloques libres (no se informa como causa). Con las políticas voraces ninguna causa posterior a `patient_conflict` es posible: si una GES queda fuera con cupo libre, también es un error.

Cada fila incluye `entry_id`, plazo, días de atraso al primer bloque posible (si existe), si quedó agendada fuera de plazo y en qué fecha, y un texto en español, por ejemplo: *"Plazo GES 2025-10-05; el primer bloque compatible (servicio 15, oftalmología) es el 2025-10-07. Queda agendada el 2025-10-07, 2 días fuera de plazo."*

## 8. Resolución

### 8.1 Fases lexicográficas

Cada fase es un `CpModel` sobre las mismas variables; al terminar se agrega su objetivo como restricción (`≥` o `≤` el mejor valor encontrado) y la solución pasa como pista (`AddHint`) a la siguiente. Si la solución voraz de la fase 0 también cumple todo lo fijado y tiene mejor valor en la fase que empieza, se usa esa como pista.

| Fase | Objetivo | Sobrecupo | Se fija para las siguientes |
|---|---|---|---|
| 0 | Política voraz `priority` ([sección 10](#10-políticas-de-referencia)): pista inicial y cota inferior | No | — |
| 1 | `max Σ_{i∈Q1} a_i` (cesión a p1, igual que `yield_to_priorities` de P4). Se omite si `Q1 = ∅` | No | `Σ_{Q1} a_i ≥ F1*` |
| 2 | `min Σ_{g∈G} v_g` | No | `Σ v_g ≤ F2*` |
| 3a | `max Σ c_ib·x_ib` | No | Conjunto `S0` y valor `Z0` |
| 3b | `max Σ c_ib·x_ib` con R7-R15 | Sí | `Σ c_ib·x_ib ≥ (1 − tol)·Z3` y el conjunto de agendados `S3` |
| 4 | `min BAL` | Según 3b (se fijan los `k_bo`) | — |

La fase 4 fija el conjunto exacto de agendados al cerrar la fase 3b, `S3` (igual a `S0` si no hubo 3b): `a_i = 1` para `i ∈ S3` y `a_i = 0` para el resto. El equilibrio solo cambia en qué bloque va cada uno, nunca quién tiene cupo. Antes solo se fijaba `S0`, y con la 3a terminada por tiempo o por `relative_gap_limit` la fase 4 podía agregar pacientes, que quedaban etiquetados `phase_added = "3b"` sin que la 3b hubiera corrido (hallazgo M-04 de la revisión P17). La pista de la fase 4 es la solución de la 3b (o de la 3a), que cumple las simetrías de la fase, así que fijar `S3` nunca la vuelve infactible.

- Las fases 1 y 2 se resuelven sin sobrecupo: las obligaciones clínicas y legales no dependen de una predicción incierta.
- Si `config.overbooking.enabled = false`, la fase 3b no existe y `Z3 = Z0`.
- Si una fase termina en `FEASIBLE` (sin probar óptimo), se fija el mejor valor encontrado y se registra la brecha. Si termina en `UNKNOWN`, se conserva la solución de la fase anterior (siempre hay una, por la fase 0) y se registra. `INFEASIBLE` o `MODEL_INVALID` solo pueden deberse a un error (todo lo duro tiene holgura o la pista lo satisface): se lanza excepción con el diagnóstico.
- En la fase 1, contar casos favorece procedimientos cortos en pabellón. Se acepta (sigue el orden de P4) y el informe mide la tasa de agendamiento por duración.

Por qué hay fase 1: P4 pone a p1 antes que cualquier GES de p2-p4 (`yield_to_priorities: [p1]`). Si la fase de GES fuera primero, el programador podría sacar a un p1 para cumplir una GES de p4, contradiciendo el orden que el usuario validó.

### 8.2 Filtro de candidatos

Con demanda mucho mayor que la oferta, la mayoría de las entradas no puede entrar. Para cada cola `q` (clave de `match_level` + especialidad):

```
K_q = Σ_{b∈B^C_q} (C_b + O_b)                              CNE
K_q = Σ_{b∈B^O_q} floor(L_b / (min_{i∈q} d_i + τ))          pabellón
I_q = { i ∈ q : rank_i ≤ ceil(m · K_q) } ∪ (G ∩ q)          m = config.candidate_margin (2,0)
```

Se usa el orden de P4 (que ya pone p1 y GES estrictas arriba) y se agregan todas las GES obligadas aunque estén más abajo. El margen cubre conflictos de paciente, sobrecupos y tamaños de procedimiento.

`O_b` en `K_q` es el nominal (`floor(max_fraction·C_b)`) aunque el sobrecupo esté apagado, para que el conjunto de candidatos, y con él las fases 1-3a, no dependa de ese interruptor.

Comprobación de frontera: el filtro pudo haber sido activo en una cola si (a) se agenda alguna entrada del último 10 % de `I_q` (por `rank`, al menos una entrada), o (b) queda capacidad libre en un bloque de la cola que una entrada descartada podría usar sin conflicto de día (R4). La señal (b) cubre colas donde varias entradas del mismo paciente ocupan los primeros puestos y R4 deja usable solo una. Ambas señales se evalúan sobre la solución de la fase 3a (sin sobrecupo, cargas sin sobrecupo), no sobre el plan final: si no, los sobrecupos de 3b podían expandir la frontera y cambiar los candidatos y `S0` solo con el sobrecupo activo (hallazgo de la revisión de P8). Se registra `candidate_frontier_reached` y, si `config.expand_on_frontier` (true), el subproblema se resuelve una vez más con `m` duplicado. El resultado de la segunda corrida es el definitivo y la advertencia queda en el informe.

### 8.3 Descomposición

- **Componentes exactos.** Dos entradas quedan en el mismo subproblema si comparten paciente (R4) o algún bloque compatible. Con `match_level = health_service` cada componente cabe en un servicio de salud; en la corrida canónica ningún paciente tiene entradas en dos servicios, así que hay 29 subproblemas independientes y la descomposición no pierde optimalidad (salvo en los límites de equidad, que pasan a ser por servicio; ver [sección 6.5](#65-límites-por-grupo-contrato-con-p6)). Se calculan como componentes conexas (union-find) y se ordenan por código para que el orden sea determinista.
- **Por especialidad (respaldo).** Si un componente supera `config.max_pairs_per_subproblem` (400.000 pares), se resuelve por especialidad en orden de código. Las citas ya asignadas a un paciente bloquean ese día en las especialidades siguientes (R4 pasa a ser un filtro). Pierde optimalidad, y el orden de especialidades influye; se registra `decomposition: by_specialty` en el informe.
- **Por semana (último respaldo).** Solo si una especialidad de un componente todavía supera `config.max_pairs_per_subproblem`. Las semanas se resuelven en orden; cada una ve solo sus bloques y las entradas aún sin cita, y los días ya ocupados por un paciente quedan bloqueados. Como rompe la anticipación de plazos, la obligación GES (R5/R6) se aplica en una semana solo a las garantías sin bloques que la cumplan en semanas posteriores ("última oportunidad"); antes de eso compiten por puntaje y atraso. Se registra `decomposition: by_week`. En la corrida canónica de 4 semanas no se activa.
- `config.decomposition = specialty` fuerza el respaldo por especialidad aunque el componente sea chico (análisis de sensibilidad).
- En la simulación el horizonte es deslizante: cada semana se planifican `horizon_weeks` y solo se congelan las citas de la primera (`config.commit_weeks = 1`); el resto se replanifica la semana siguiente con `prebooked_*`. El programador no usa `commit_weeks`: lo aplica quien lo llama (la simulación) y solo entra en el digest de la configuración.

### 8.4 Simetrías

1. **Posiciones dentro del bloque:** no existen en el modelo ([sección 1](#1-alcance-y-principios)).
2. **Bloques idénticos:** bloques de la misma especialidad, misma clave de lugar, mismo `start_at`, misma capacidad (`C_b` u `L_b`) y mismos `p_ib` para todo candidato (se cumple si el modelo de inasistencias solo usa día, hora y aviso, que son iguales) son intercambiables. Se ordenan por `resource_id` y se impone carga no creciente: `load_b1 ≥ load_b2 ≥ …` (unidades CNE o minutos). Es válido: cualquier solución se puede permutar entre bloques idénticos sin cambiar el objetivo ni `BAL`.
3. **Entradas idénticas:** misma cola, `s_i`, duración, condición GES y plazo, vector `p_i·`, grupos de equidad, pacientes sin otras entradas. Se ordenan por `rank` y se impone `a_i ≥ a_j` para consecutivas. Son raras porque `S` depende de los días de espera, pero el chequeo es barato.
4. **Clases con y sin `p`.** Las fases sin sobrecupo (1, 2, 3a y la 4 sin 3b) usan clases que ignoran `p`; las fases con sobrecupo (3b y la 4 tras 3b) exigen además igual `p`. Las clases con `p` refinan a las sin `p`, así que la solución de la fase 3a cumple las dos. Así las fases 1-3a no dependen de `p` en absoluto ([sección 15](#15-tests-mínimos-que-la-implementación-debe-incluir), punto 4).
5. Toda pista se lleva antes a la forma canónica (dentro de cada clase, entradas agendadas primero y bloques por carga no creciente), para que las restricciones de simetría no la rechacen.

### 8.5 Parámetros de CP-SAT y tiempo límite

- **Presupuesto global (P18).** `config.time_limit_s = B` (120) es el presupuesto de CP-SAT de todo el plan, primera pasada y expansión de frontera juntas, en unidades de tiempo determinista (en segundos de reloj con `deterministic = false`). En modo determinista no hay ningún tope de reloj. Antes cada componente recibía al menos 1 unidad y cada pasada `B` completo: en la corrida canónica 131 de 159 subproblemas recibían el mínimo, lo asignado sumaba 277,8 unidades y la primera pasada descartada gastó 77,3 más.
  - **Dos libros.** `B` se divide entre las fases 1-3a (52,5 %) y las fases 3b-4 (47,5 %), según las partes por fase de más abajo. Cada libro reparte y arrastra solo su propio tiempo, así que el presupuesto de la 3a (y con él `S0` y la frontera cuando la 3a termina por tiempo) no depende de `p` ni del interruptor de sobrecupo, aunque la 3b de un componente anterior gaste más o menos.
  - **Primera pasada**, con `B1 = config.solver.first_pass_share · B` (0,75; todo `B` si `expand_on_frontier = false`, porque no habrá segunda pasada). Los componentes se resuelven por número de pares ascendente (desempate: el orden de la [sección 8.3](#83-descomposición)). En cada libro, cada componente recibe un mínimo `m = min(config.solver.min_component_budget · parte del libro, 0,2 · saldo inicial del libro / n)` (en la primera pasada, `min(0,05; 0,2·B1/n)` repartido entre los libros) más la parte proporcional a sus pares del saldo del libro que excede los mínimos de los componentes que faltan. Lo que un componente no gasta queda en el saldo y lo usan los siguientes; el último recibe todo lo que queda. Es reproducible porque solo depende del tiempo determinista que informa CP-SAT. El reparto por especialidad o por semana dentro de un componente ([sección 8.3](#83-descomposición)) sigue siendo proporcional a los pares.
  - **Expansión de frontera** ([sección 8.2](#82-filtro-de-candidatos)), con lo que queda de cada libro (`B − gastado`, sin negativos) y el mismo reparto entre los componentes que cambiaron. Si el saldo del libro base no alcanza el mínimo, los componentes que faltan conservan la solución de la primera pasada: sus entradas que solo entraban con el margen duplicado vuelven a `not_candidate`, se listan en `frontier.skipped_components` y el informe agrega la advertencia `frontier_expansion_skipped_budget`. La decisión solo mira el libro base, así que tampoco depende de `p`.
  - **Dentro de un subproblema:** fase 1 10 %, fase 2 10 %, fase 3a 32,5 % (libro base), fase 3b 32,5 % y fase 4 15 % (libro 3b-4). El tiempo que una fase no usa pasa a la siguiente fase de su libro; lo que la 3a no usa vuelve al saldo del libro base de la pasada. Si no hay 3b, su parte pasa a la fase 4; en el modo relativo de equidad, cada pasada de 3b recibe la mitad. Toda fase recibe al menos 0,01.
  - **Informe** (`solver.budget`): `unit` (`deterministic` o `seconds`), `total`, `first_pass` y `frontier` (`allotted` y `spent`, también por libro en `phases_1_3a` y `phases_3b_4`; la frontera además trae `components_skipped`), `spent`, `exhausted`, `phases_ended_by_limit` y `overrun = max(0, spent − B)`. El gasto puede superar `B` porque CP-SAT revisa el límite por lotes y por el mínimo de 0,01 por fase. `exhausted` es verdadero si alguna fase terminó por tiempo (`FEASIBLE` o `UNKNOWN`) o si se omitió algún componente de la expansión; en ese caso el informe agrega la advertencia `time_budget_exhausted`, visible en el panel y en el informe de resultados. El tiempo de reloj se informa aparte (`solver.time`) y no entra en este bloque, que es idéntico entre corridas en modo determinista.
  - Las cifras de la corrida canónica con el presupuesto global (tiempo, estados por fase, componentes omitidos y efecto en el plan con `B` = 60, 120 y 240) se actualizan en P18-G.
- `random_seed = seed`, `relative_gap_limit = 0,001` en las fases 3a y 3b.
- **Reproducibilidad (decisión de implementación, ver `docs/decisions.md` §10 y §11b).** Con `config.solver.deterministic = true` (por defecto) se usa búsqueda secuencial: `num_workers = 1` y `max_deterministic_time` = presupuesto, en unidades de tiempo determinista. El tiempo determinista que informa CP-SAT puede diferir en el último bit entre dos corridas idénticas (medido en una fase que terminó por límite), así que se redondea a 9 decimales antes de usarlo: si no, el arrastre del presupuesto llevaría ese ruido a los límites de las fases y componentes siguientes. Se probó `interleave_search = true` con 8 hilos, que también es determinista según la documentación de OR-Tools 9.15, pero en el subproblema mayor de la corrida canónica llegó a la brecha de 0,1 % después que la búsqueda secuencial (2,4 s frente a 0,35 s) y excedió su límite determinista (2,3 frente a 0,5) porque solo lo revisa entre lotes. Con `deterministic = false` se usan `config.solver.num_workers` (8) hilos y `max_time_in_seconds`, con el mismo reparto en segundos de reloj: respeta el tiempo real, pero el plan puede cambiar entre corridas y el informe lo marca `reproducible: false`. El test de reproducibilidad corre dos veces la misma instancia y compara planes e informe (salvo tiempos de reloj).
- En modo determinista el tiempo real puede exceder `time_limit_s`, porque el tiempo determinista no es tiempo de reloj (en la corrida canónica, la fase 3b gasta de 2 a 4 s reales por segundo determinista). El informe registra ambos.
- Se registran por fase y subproblema: estado, objetivo, mejor cota, brecha, tiempo real y determinista, y número de variables y restricciones.

### 8.6 Técnicas de rendimiento (P9)

Ninguna cambia el valor óptimo de una fase: la poda solo quita variables que ninguna solución usa, la cota del objetivo y las simetrías descartan soluciones factibles pero nunca todas las óptimas, y las pistas solo cambian el punto de partida. Cada una tiene un interruptor en `config.solver` (todos `true` por defecto), que solo sirve para medir su efecto en el benchmark (`make bench-scheduler`, resultados en [scheduler-performance.md](scheduler-performance.md)).

| Técnica | Interruptor | Qué hace |
|---|---|---|
| Compatibilidad previa | — (siempre) | Solo se crea `x_ib` para pares de la misma cola (lugar y especialidad) que cumplen duración, aviso mínimo y horizonte (§4), y solo para candidatos (§8.2). Ningún par imposible llega al modelo. |
| Poda de niveles de sobrecupo | `prune_overbooking_levels` | En cada bloque elegible se descartan, antes de crear `k_bo`, los niveles `o` imposibles: menos de `C_b + o` candidatos, o la suma de los `C_b + o` mayores coeficientes de R10/R11 menor que su lado derecho; si no queda ningún nivel, el bloque deja de ser elegible y, si ningún bloque lo es, la fase 3b no se corre y su presupuesto pasa a la fase 4. Dentro de la fase 3b y la 4 se descartan además los niveles con menos de `o` candidatos fuera de `S0` (R13), sin cambiar la elegibilidad. Ajusta la relajación lineal de 3b, que sin la poda supone `O_b` sobrecupos en todo bloque. Las cotas de `w_qb` (R14) y `util_b` usan el mayor nivel que queda. |
| Cota del objetivo con la pista | `objective_cut` | Cada fase agrega `objetivo ≥ valor de la pista` (`≤` al minimizar). La pista es factible, así que el óptimo no cambia; la búsqueda descarta desde el inicio las soluciones peores. |
| Pistas voraces | `hints` | La voraz `priority` (fase 0) y la solución de la fase anterior, llevadas a forma canónica (§8.4), entran con `AddHint` (§8.1). Apagado, CP-SAT parte sin pista; la pista igual se usa como solución de respaldo si la fase termina en `UNKNOWN` y, si `objective_cut` está activo, su valor sigue acotando el objetivo. |
| Pista voraz con sobrecupo | `overbooking_hint` | La fase 3b parte de la solución de 3a más sobrecupos voraces: por bloque elegible, en orden de fecha, se agrega la entrada sin cita de mayor `c_ib` cuyo paciente está libre ese día, mientras el nivel resultante exista y cumpla R10/R11 y los topes R15 de la pasada. Sin ella, 3b parte con sobrecupo 0. |
| Simetrías | `symmetry_breaking` | Restricciones de §8.4 (bloques y entradas intercambiables). |
| Arranque en caliente de la frontera | `warm_start_frontier` | Al duplicar el margen en colas de frontera (§8.2), cada componente nuevo recibe como pista alternativa la unión de las soluciones de la fase 3a de los componentes de la primera pasada que contiene (los candidatos solo crecen, así que es factible sin sobrecupo). Se usa en cada fase en la que cumple lo fijado y mejora a la pista vigente. |

El tiempo de solver de los componentes de la primera pasada que la expansión reemplaza no aporta al plan, pero se informa (`solver.time.discarded_first_pass`), junto con el de los subproblemas del plan (`solver.time.plan`). Por subproblema, `techniques` registra los niveles de sobrecupo nominales y los que quedan tras la poda, y las clases de simetría encontradas.

## 9. Postproceso: secuencia, banderas y verificación

**Banderas.** En cada bloque CNE con `o_b ≥ 1`, se marcan `is_overbooked = true` las `o_b` entradas agendadas que no están en `S0` con mayor `p_ib` (desempate: menor `s_i`, luego `entry_id`). R13 garantiza que existen.

**Secuencia CNE.** Las entradas sin bandera se ordenan por `rank` de P4 y toman las posiciones `0, 1, …` (hora `start_at + j·unit_min`), desplazadas por las `prebooked_units` que ya ocupan el inicio de la sesión (en pabellón, por `prebooked_min`). La `k`-ésima bandera (orden de `p` decreciente, `k = 0..o_b−1`) comparte la posición `floor((k + 1)·C_b / (o_b + 1))`, para repartir los sobrecupos en la sesión.

**Secuencia en pabellón.** Por `rank` de P4; el caso `k` empieza en `start_at + Σ_{previos} (d + τ)`.

**Lista de reemplazo (pabellón).** Para cada bloque, las primeras `config.or_standby_size` (3) entradas compatibles no agendadas, por `rank`, cuyo `d + τ` cabe en el bloque. Es informativa: no reserva nada.

**Citas.** Cada asignación genera un `appointment` con `origin = scheduler`, `status = scheduled`, `schedule_run_id`, `slot_id`, `entry_id`, `patient_id`, `scheduled_start`, `duration_min`, `lead_days = (local_date_b − as_of).days`, `is_overbooked` y `predicted_noshow_prob = p_ib`. El `schedule_run` guarda `policy = optimized`, el horizonte, la semilla, `params` (configuración completa, digest de reglas, versión del modelo de inasistencias, `code_version`), `solver_status` (el peor estado entre fases y subproblemas), `objective_value` (`Z3` total) y `review_status = pending`.

**Verificación (siempre, antes de devolver el plan).** Se recalculan desde las asignaciones, sin usar el modelo:

1. R1-R4 y las fechas del horizonte y aviso mínimo. R4 incluye los días de `busy`: ninguna cita nueva cae en un día en que el paciente ya tenía una.
2. Para cada bloque con sobrecupo, el riesgo exacto `P(asisten > C_b)` con la distribución binomial de Poisson (programación dinámica, `O(n²)`). Debe ser `≤ α`; si no, es un error de implementación (el redondeo es conservador) y se lanza excepción.
3. Que `S0 ⊆` agendados finales; que en cada subproblema los agendados finales son exactamente `S3` (la fase 4 no cambia quién tiene cupo); que sin fase 3b no hay agendados fuera de `S0`, y que las banderas recaen fuera de `S0`. `phase_added = "3b"` solo se asigna si la fase 3b corrió en el subproblema de la entrada.
4. Que las GES realmente incumplidas (`v_g` recalculado desde las asignaciones) no superan `F2*`, que son exactamente `F2*` si la fase 2 terminó en `OPTIMAL` y la fase 3b no agregó a nadie (con sobrecupo puede haber menos), y que cada GES no cumplida tiene causa.
5. Que el plan no es peor que la política voraz `priority` en orden lexicográfico: `(Σ_{Q1} a_i, −Σ v_g, Σ c_ib·x_ib)` del plan `≥` el de la voraz, comparando el tercer término sin sobrecupo (`Z0`). No se compara solo el puntaje: las fases 1 y 2 pueden sacrificar puntaje para ceder a p1 o cumplir GES. Si falla con todas las fases en `OPTIMAL`, es un error y se lanza excepción, salvo que la pérdida esté solo en el tercer término y la fase 3a haya terminado en `OPTIMAL` por `relative_gap_limit` (brecha mayor que 0): eso es posible sin pistas (P9) y se informa como advertencia. Si alguna fase terminó por tiempo, también se informa la advertencia `worse_than_baseline`.

## 10. Políticas de referencia

Para que la simulación compare políticas con el mismo código de compatibilidad, `scheduler` implementa también las dos políticas base, sin CP-SAT y sin sobrecupo:

- `fifo`: entradas por `(entry_date, entry_id)`.
- `priority`: entradas por el orden de P4: `(rank, cola, entry_id)`. Las colas no comparten bloques, pero sí pacientes (R4); ordenar por `rank` primero hace que las colas avancen a la par.

Para cada entrada en ese orden se elige el primer bloque de `B(i)` por `(local_date_b, start_at, slot_id)` con capacidad residual (R2 sin sobrecupo, R3) y sin otra cita del paciente ese día (R4). Si no hay, queda sin agendar. Usan los mismos filtros de compatibilidad, la misma secuencia y el mismo informe de GES (con `solver_limit` imposible).

## 11. Escalabilidad

### 11.1 Tamaño medido

Corrida canónica (N = 100.000, semilla 42, escenario baseline, `as_of` 2025-09-30, `horizon_start` 2025-10-06), compatibilidad por servicio, medida el 2026-10-08:

| | 4 semanas | 26 semanas |
|---|---|---|
| Entradas en espera | 100.000 | 100.000 |
| Bloques CNE (unidades) | 378 (4.536) | 6.777 (81.324) |
| Bloques de pabellón (minutos) | 652 (234.720) | 4.249 (1.529.640) |
| Pares compatibles sin filtro | 238.338 | 1.965.969 |
| Candidatos tras el filtro (m = 2) | 15.843 | 98.319 |
| Pares tras filtro, aviso y duración | 92.660 (68.995 CNE) | 1.949.413 |
| Subproblema mayor / mediana (pares) | 14.535 / 1.630 | 195.376 / 42.034 |
| GES obligadas (vencidas antes del horizonte) | 3.866 (2.105) | 6.555 (2.105) |
| GES obligadas con algún bloque compatible | 1.857 | 6.517 |

Con 4 semanas, el problema es pequeño para CP-SAT: el subproblema mayor tiene unos 15.000 booleanos `x`. Con 26 semanas el filtro no reduce casi nada (la oferta del horizonte se acerca a la demanda) y el subproblema mayor tiene unos 200.000 pares; sigue bajo el umbral de 400.000, pero el tiempo de la fase 3 puede ser el cuello de botella. Objetivo de rendimiento para la implementación: plan de 4 semanas para N = 100.000 en menos de 120 s. Medido en la [sección 11.3](#113-medición-de-la-implementación-p8-actualizada-en-p9-tras-la-revisión-de-p8-y-con-la-oferta-corregida): 143 s reales en P8, 166 s en P9 y 117,8 s tras la revisión de P8, con la oferta concentrada del generador 0.1.0; con la oferta corregida (más bloques en 4 semanas), 163,5 s. No se cumple. Desde P18, `time_limit_s` es un presupuesto global del plan ([sección 8.5](#85-parámetros-de-cp-sat-y-tiempo-límite)); la medición con ese presupuesto se actualiza en P18-G.

### 11.2 Artefactos de la oferta sintética (corregidos en el generador 0.2.0)

Al medir se encontraron dos patrones del generador (`synthetic/capacity.py`, versión 0.1.0) que no eran del programador pero cambiaban sus resultados:

1. **Las sesiones CNE se concentran a mitad del horizonte.** `_week_slots` pone la sesión `k` de `count` en la semana `floor((k + 0,5)·H / count)`; con `count = 1` (la mayoría de las agendas tienen 1 o 2 sesiones en 26 semanas) cae en la semana 13. Resultado: 22 sesiones en la semana 0, 3.149 en la semana 13 y 378 en las primeras 4 semanas, frente a ~1.043 si se repartieran parejo. Por eso solo 1.857 de las 3.866 GES obligadas tienen algún bloque en 4 semanas.
2. **Los bloques de pabellón se concentran en lunes.** El día es `idx % 5` con `idx` el índice dentro de la semana del recurso; con ~1 bloque por recurso y semana, 3.276 de 4.249 bloques caen en lunes. Afecta a R4 y a la variable de día de la semana del modelo de inasistencias.

**Corrección (2026-10-09, generador 0.2.0).** Cada agenda y pabellón reparte sus sesiones con una fase propia y el día del pabellón rota por recurso: en la corrida canónica quedan 237-296 sesiones CNE y 150-174 bloques de pabellón por semana, y 799-933 bloques por día de lunes a viernes (detalle en `docs/synthetic-data.md` §8, punto 9). El programador sigue sin corregir la oferta: la usa como viene y reporta la capacidad por semana. Las mediciones de la [sección 11.3](#113-medición-de-la-implementación-p8-actualizada-en-p9-tras-la-revisión-de-p8-y-con-la-oferta-corregida) y el benchmark se repitieron con la oferta corregida.

### 11.3 Medición de la implementación (P8, actualizada en P9, tras la revisión de P8 y con la oferta corregida)

Corrida canónica, 4 semanas, configuración por defecto (`deterministic = true`, un hilo, `linearization_level = 2`, `time_limit_s = 120`, técnicas de la [sección 8.6](#86-técnicas-de-rendimiento-p9) activas), medida el 2026-10-09 con `make schedule` sobre la corrida regenerada con el generador 0.2.0 (oferta repartida en semanas y días, [sección 11.2](#112-artefactos-de-la-oferta-sintética-corregidos-en-el-generador-020)); informe completo en `results/schedule_32c9e349-74f9-5c85-bf4b-990796b47323_4w.json`. El horizonte tiene ahora 1.695 bloques (antes 1.030): 1.042 sesiones CNE (12.504 cupos) y 653 bloques de pabellón. El benchmark por tamaño y la ablación de cada técnica están en [scheduler-performance.md](scheduler-performance.md).

| | `fifo` | `priority` | `optimized` |
|---|---|---|---|
| Agendadas (CNE / pabellón) | 13.169 (11.905 / 1.264) | 13.168 (11.906 / 1.262) | 13.616 (12.212 / 1.404) |
| p1 agendados | 844 | 4.146 | 4.150 |
| GES obligadas cumplidas (de 3.866) | 342 | 1.070 | 1.594 |
| GES dentro de plazo | 23 | 92 | 615 |
| Suma de `c_ib` | 52.705.746 | 64.732.928 | 66.454.560 |
| Sobrecupos | 0 | 0 | 343 (riesgo exacto máximo 0,0999 ≤ 0,10) |

Con la oferta concentrada del generador 0.1.0 (antes de la corrección) la optimizada agendaba 5.949 y cumplía 1.211 GES; las cifras no son comparables porque cambió la oferta, no el programador.

- **Tiempo (no se cumple el objetivo de 120 s).** La política optimizada tarda 163,5 s reales; las voraces, 2,2-2,6 s. CP-SAT gasta 155,7 unidades deterministas en los 159 subproblemas del plan y 77,3 más en 41 componentes de la primera pasada que la expansión de frontera (96 colas) reemplazó: 233,0 en total. Esta medición es anterior a P18: el presupuesto era por pasada, así que con expansión el total superaba `time_limit_s`. Con el presupuesto global de la [sección 8.5](#85-parámetros-de-cp-sat-y-tiempo-límite) se actualiza en P18-G. Con la oferta repartida, el problema de 4 semanas es mayor que antes (más bloques en el horizonte y más candidatos).
- **Estados.** Fases 1 (136) y 2 (89) en `OPTIMAL`; 3a 155 `OPTIMAL` y 4 `FEASIBLE` (brecha agregada 2,06 %); 3b 42 `OPTIMAL`, 16 `FEASIBLE` y 21 `UNKNOWN`; fase 4 76 `OPTIMAL`, 6 `FEASIBLE` y 14 `UNKNOWN`. Una fase en `UNKNOWN` conserva su pista (en 3b, la de la voraz con sobrecupo), así que el plan es factible y verificado, pero la brecha agregada de 3b queda sin definir.
- **GES.** De las 2.272 garantías incumplidas, 1.018 no tienen ningún bloque de su especialidad en el horizonte, 602 vencen antes del primer bloque posible y 652 encuentran los cupos tomados. Con la oferta concentrada eran 2.655 incumplidas, 2.009 de ellas sin bloque en el horizonte.
- **Equidad (resultados que se informan tal cual).** Las tasas de agendamiento quedan entre 12,6 % y 13,9 % por grupo etario y previsión en las tres políticas (con la oferta concentrada, el grupo 0-14 quedaba en ~3 % frente a 5-6,6 % del resto). La exposición al sobrecupo (agendados CNE en sesiones con sobrecupo) es 36,5 % en total, 35,2-41,4 % por grupo etario y 35,0-37,4 % por previsión. Todos los grupos quedan dentro de 5 pp del total, pero el 0-14 está en el borde (41,4 %, +4,9 pp): más de 4 de cada 10 niños agendados en CNE comparten sesión con un sobrecupo.
- **Advertencias del informe.** Frontera de candidatos alcanzada en 96 colas y todavía alcanzada en 14 tras duplicar el margen; 139 citas con aviso fuera del rango del historial (7-90 días), cuya `p` extrapola el modelo.

## 12. Configuración

`SchedulerConfig` (pydantic congelado, `extra = forbid`, digest sha256 registrado en `schedule_run.params`):

| Clave | Defecto | Motivo |
|---|---|---|
| `horizon_weeks` | 4 | Pedido del usuario; con 4 semanas el problema es pequeño. |
| `match_level` | `health_service` | Igual a la cola de P4. |
| `min_lead_days` / `ges_min_lead_days` | 7 / 2 | 7 es el mínimo del historial; GES urgentes admiten aviso corto. |
| `or_turnover_min` | 30 | Supuesto `iq_turnover_min` del generador. |
| `or_max_fill` | 0,85 | Supuesto `iq_utilization` del generador. |
| `max_per_patient_per_day` | 1 | Una cita por día y paciente. |
| `overbooking.enabled` | true | Solo CNE. |
| `overbooking.alpha` | 0,10 | Riesgo máximo de desborde por sesión; barrer en simulación. |
| `overbooking.max_fraction` | 0,25 | `O_b = 3` en una sesión de 12. |
| `overbooking.p_clip` | [0,001; 0,95] | Logaritmos definidos. |
| `group_limits` | [Sección 6.5](#65-límites-por-grupo-contrato-con-p6) | Provisional hasta P6. |
| `weights.earliness` | 0,05 | Agendar al final del horizonte cuesta 5 % del puntaje. |
| `weights.ges_delay_points_per_day` | 1,0 | Un día de atraso GES evitable equivale a 1 punto de prioridad. |
| `weights.balance_tolerance` | 0,0 | El equilibrio solo desempata. |
| `candidate_margin` / `expand_on_frontier` | 2,0 / true | Filtro seguro con comprobación. |
| `max_pairs_per_subproblem` | 400.000 | Umbral del respaldo por especialidad. |
| `commit_weeks` | 1 | Horizonte deslizante en la simulación. |
| `or_standby_size` | 3 | Lista de reemplazo por bloque. |
| `time_limit_s` | 120 | Presupuesto global de CP-SAT del plan, primera pasada y expansión de frontera juntas ([sección 8.5](#85-parámetros-de-cp-sat-y-tiempo-límite)); unidades deterministas por defecto. |
| `solver.first_pass_share` | 0,75 | Fracción de `time_limit_s` para la primera pasada; el resto queda para la expansión de frontera (todo va a la primera pasada si `expand_on_frontier = false`). |
| `solver.min_component_budget` | 0,05 | Mínimo por componente y pasada, repartido entre los dos libros (se usa `min(0,05; 0,2·presupuesto de la pasada / componentes)` en cada libro). |
| `decomposition` | `auto` | `specialty` fuerza el respaldo por especialidad ([sección 8.3](#83-descomposición)). |
| `solver.num_workers` / `solver.deterministic` | 8 / true | `deterministic = true` usa un hilo (sección 8.5); los 8 hilos solo se usan con `deterministic = false`. |
| `solver.relative_gap_limit` | 0,001 | Fases 3a y 3b. |
| `solver.hints`, `objective_cut`, `symmetry_breaking`, `prune_overbooking_levels`, `overbooking_hint`, `warm_start_frontier` | true | Técnicas de rendimiento de la [sección 8.6](#86-técnicas-de-rendimiento-p9); apagarlas solo sirve para medirlas. |
| `solver.log_search_progress` | false | Registro de CP-SAT para depurar. |

## 13. Ejemplo resuelto a mano

Una cola CNE (un servicio, una especialidad), `as_of` = 2025-09-30, `horizon_start` = 2025-10-06, `H` = 28 días. Para que quepa a mano se reduce la capacidad y se cambian dos parámetros: `C_b = 2`, `O_b = 1`, `α = 0,25`. Resto por defecto (`e = 0,05`, `w_D = 1`, aviso 7 días y 2 para GES).

**Bloques.** B1 = martes 2025-10-07 08:30 (`day = 1`), B2 = martes 2025-10-14 08:30 (`day = 8`). Ambos cumplen el aviso mínimo para todos.

**Entradas** (puntajes de las entradas A, C, D, E de [priority.md](priority.md), más F; `p` igual en ambos bloques para simplificar):

| Entrada | Prioridad | Espera | GES | S | s = round(100·S)+100 | p |
|---|---|---|---|---|---|---|
| A | p1 | 30 d | No | 51,44 | 5.244 | 0,10 |
| C | p4 | 1.500 d | No | 35,00 | 3.600 | 0,45 |
| D | p3 | 120 d | Vencida hace 10 d (2025-09-20) | 33,25 | 3.425 | 0,08 |
| E | p2 | 20 d | Vence 2025-10-25 | 39,71 | 4.071 | 0,10 |
| F | p4 | 100 d | No | 4,79 | 579 | 0,50 |

Conjuntos: `Q1 = {A}`, `G^od = {D}`, `G^dl = {E}` (plazo dentro del horizonte; B1 y B2 están antes del plazo).

**Coeficientes.** `early = round(s·0,05·day/28)`. Para D, `first_D` = 2025-10-07 y `max(D_D, first_D)` = 2025-10-07, así que el atraso es 0 en B1 y 7 días (700) en B2.

| Entrada | early B1 | early B2 | delay B2 | c B1 | c B2 | c B1 − c B2 |
|---|---|---|---|---|---|---|
| A | 9 | 75 | — | 5.235 | 5.169 | 66 |
| C | 6 | 51 | — | 3.594 | 3.549 | 45 |
| D | 6 | 49 | 700 | 3.419 | 2.676 | 743 |
| E | 7 | 58 | 0 | 4.064 | 4.013 | 51 |
| F | 1 | 8 | — | 578 | 571 | 7 |

**Fase 1.** Solo A es p1 y hay capacidad: `F1* = 1`.

**Fase 2.** D y E caben (4 cupos para 3 obligados): `F2* = 0`.

**Fase 3a (sin sobrecupo).** Caben 4 de 5. A, D y E están forzados por las fases 1 y 2; el cuarto es C (`c ≈ 3.594`) antes que F (578). Para repartir, B1 se da a las dos entradas con mayor diferencia B1 − B2: D (743) y A (66). Plan: B1 = {A, D}, B2 = {C, E}. `Z0 = 5.235 + 3.419 + 3.549 + 4.013 = 16.216`. `S0 = {A, C, D, E}`.

**Fase 3b (sobrecupo).** R12 obliga a mantener A, C, D, E; la única forma de mejorar es agregar a F con un sobrecupo (`o = 1`, 3 pacientes en un bloque). R13: F ocupa el sobrecupo. Riesgo exacto del bloque = probabilidad de que asistan los 3 = `Π(1 − p)`. El bloque con F necesita otros dos de S0:

| Trío con F | Π(1 − p) | ≤ 0,25 |
|---|---|---|
| F, C, A | 0,50·0,55·0,90 = 0,2475 | Sí |
| F, C, E | 0,50·0,55·0,90 = 0,2475 | Sí |
| F, C, D | 0,50·0,55·0,92 = 0,2530 | No |
| F con dos de {A, D, E} | ≥ 0,50·0,90·0,90 = 0,405 | No |

En enteros (R10): `A_C = floor(10⁴·0,597837) = 5.978`, `A_F = 6.931`, `A_E = A_A = 1.053`, `A_D = 833`, `R1 = ceil(10⁴·ln 4) = 13.863`. {F, C, E}: 13.962 ≥ 13.863. {F, C, D}: 13.742 < 13.863. Coincide con la tabla.

Planes candidatos (el bloque de 2 lleva a los otros dos de {A, D, E}):

| B1 | B2 | Objetivo |
|---|---|---|
| A, D | C, E, F | 5.235 + 3.419 + 3.549 + 4.013 + 571 = **16.787** |
| D, E | A, C, F | 3.419 + 4.064 + 5.169 + 3.549 + 571 = 16.772 |
| A, C, F | D, E | 5.235 + 3.594 + 578 + 2.676 + 4.013 = 16.096 |
| C, E, F | A, D | 3.594 + 4.064 + 578 + 5.169 + 2.676 = 16.081 |

Óptimo: B1 = {A, D}, B2 = {C, E, F}, `Z3 = 16.787 ≥ Z0`. B2 tiene `o = 1`.

**Fase 4.** `util_B1 = 1000`, `util_B2 = 1500`, `BAL = 500`. No hay otro plan con el mismo objetivo; no cambia nada.

**Postproceso.** F lleva la bandera de sobrecupo (única agregada en B2). B2: E (rank P4 mayor) a las 08:30, C a las 08:50 y F comparte la posición `floor(1·2/2) = 1`, a las 08:50. B1: A a las 08:30, D a las 08:50. Verificación: riesgo exacto de B2 = 0,2475 ≤ 0,25. D se atiende en el primer bloque posible; E dentro de plazo. Exposición: C, E y F están en un bloque con sobrecupo (3 de 5).

**Variante: límite por grupo.** Supongamos `age_group`: C y F son 65+, A, D y E son 45-64, `mode: relative`, `max_gap_pp = 10`, `min_group_n = 1`. Primera pasada: `share_global = 3/5 = 0,60`, `share_65+ = 2/2 = 1,00` (supera 0,60 + 0,10). Segunda pasada con `ρ = 0,70` para cada grupo: todo sobrecupo exige a C y F juntos en el bloque, lo que da `share_65+ = 1,00 > 0,70`; no hay sobrecupo factible. El plan vuelve al de la fase 3a (`16.216`) y el informe muestra el costo del límite: 571 puntos y F sin cita.

**Variante: GES infactible.** Si el plazo de E fuera 2025-10-05, ningún bloque compatible cae antes del plazo: `v_E = 1` se fija antes de resolver con causa `deadline_before_first_block`. El nuevo plazo también cambia el puntaje P4 de E: vence 5 días después de `as_of`, así que la rampa GES aporta 13,75 en vez de 8,75 (`S_E` = 44,71, `s_E` = 4.571) y E entra al nivel estricto de P4 (rank 2, antes que D). E sigue en el modelo con atraso desde `max(D_E, first_E)` = 2025-10-07: atraso 0 en B1 y 7 días en B2 (`c_E` = 4.571 − 8 = 4.563 y 4.571 − 65 − 700 = 3.806). Con ese costo, B1 pasa a {D, E} (diferencias 743 y 757 frente a 66 de A) y el óptimo es B1 = {D, E}, B2 = {A, C, F} con objetivo 3.419 + 4.563 + 5.169 + 3.549 + 571 = 17.271 (riesgo de B2 = 0,90·0,55·0,50 = 0,2475). El informe dice: *"Plazo GES 2025-10-05; el primer bloque compatible es el 2025-10-07. Queda agendada el 2025-10-07, 2 días fuera de plazo."*

## 14. Interfaz del paquete

```python
from scheduler import SchedulerConfig, SchedulingInstance, solve, greedy_schedule
from scheduler.adapters import instance_from_run  # desde data/synthetic/<run_id>/

instance = SchedulingInstance.from_frames(
    as_of=...,
    horizon_start=...,
    entries=...,
    blocks=...,
    noshow=...,
    groups=...,
    rules_digest=...,
    rules_version=...,
    noshow_model_version=...,
    seed=42,
    busy=...,  # opcional: patient_id, local_date de las citas ya confirmadas en el horizonte
)
plan = solve(instance, SchedulerConfig())  # política optimized; time_limit_s = presupuesto global
base = greedy_schedule(instance, SchedulerConfig(), order="priority")  # o "fifo"
plan.assignments  # DataFrame: entry_id, patient_id, slot_id, specialty_code, resource_kind,
#   scheduled_start, duration_min, lead_days, is_overbooked,
#   predicted_noshow_prob, phase_added ("3a" | "3b"; la política en las voraces),
#   coef (c_ib)
plan.explanations  # una fila por entrada: entry_id, status, detail, text (sección 9)
plan.ges  # una fila por GES obligada: cumplimiento, atraso, causa y texto (sección 7)
plan.standby  # lista de reemplazo por bloque de pabellón
plan.report  # fases, estado, brecha, presupuesto (solver.budget), reproducible, GES, riesgo por
#   bloque, equidad, advertencias (time_budget_exhausted, frontier_expansion_skipped_budget, ...)
plan.solver_status, plan.objective_value, plan.gap
```

CLI: `prioriza-schedule --weeks 4 [--policy all|optimized|priority|fifo] [--no-overbooking] [--alpha] [--time-limit] [--workers] [--no-deterministic] [--decomposition auto|specialty] [--persist]`. `--time-limit` es el presupuesto global (`time_limit_s`). `instance_from_run` arma `busy` con `adapters.busy_frame` (citas `scheduled` que no son historial, en el horizonte). Escribe los planes en `data/schedules/<run_id>/<weeks>w/` (no versionado) y el informe en `results/`. Con `--persist` guarda cada política en `schedule_run` y `appointment` (`review_status = pending`, `origin = scheduler`); no cambia el estado de las entradas en espera, porque el plan aún no está aprobado.

`make schedule` corre la política optimizada y las dos de referencia sobre la corrida canónica y escribe `results/schedule_<run_id>_<horizon_weeks>w.json` con el informe completo, incluidas las métricas en que la política optimizada no mejora.

## 15. Tests mínimos que la implementación debe incluir

1. El ejemplo de la [sección 13](#13-ejemplo-resuelto-a-mano), con sus dos variantes, da exactamente esos planes y objetivos.
2. Propiedad (hypothesis, instancias chicas): el plan verificado cumple R1-R4; el vector lexicográfico del punto 5 de la verificación es `≥` el de `greedy_schedule(order="priority")`; con `Q1` no vacío, ningún p1 queda fuera si cabe sin sobrecupo.
3. Sobrecupo: riesgo exacto `≤ α` en todo bloque con sobrecupo; con `enabled = false` no hay banderas; `S0 ⊆` agendados de la fase 3b.
4. Igualdad de las fases 1-3a con y sin sobrecupo (no dependen de `p`).
5. GES: cada causa de la [sección 7](#7-informe-de-ges-no-cumplidas) tiene un caso que la produce.
6. Reproducibilidad: misma instancia y semilla en modo determinista dan el mismo plan.
7. Límites por grupo: en `absolute`, `share_q ≤ max_share` en cada grupo limitado.
8. Citas previas y agendados fijos (propiedad, hypothesis derandomizado, 40 ejemplos de 1-4 pacientes, hasta 6 entradas y 5 bloques en 3 días, con días ocupados al azar): en `fifo`, `priority` y `optimized` ningún (paciente, día) se repite ni cae en un día de `busy`; en cada subproblema los agendados finales son `S3`; dos corridas dan el mismo plan y el mismo informe salvo tiempos de reloj (incluido `solver.budget`).
9. Causa `patient_day_busy` (entrada sin días libres y GES que pierde sus bloques a tiempo); el ensamblador rechaza una solución con una cita en un día ocupado, con agendados distintos de `S3` o fuera de `S0` sin fase 3b; regresión M-04: con `relative_gap_limit = 1,0` y cupo reordenable, el plan final es `S0` y no hay etiquetas "3b".
10. Presupuesto global: bloque `solver.budget` coherente; lo no gastado pasa a los componentes mayores; el presupuesto de las fases 1-3a no cambia con el sobrecupo; sin saldo, la expansión de frontera conserva la primera pasada y avisa; con presupuesto ínfimo, `exhausted` y la advertencia `time_budget_exhausted`.
