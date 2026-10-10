# Población sintética

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## 1. Qué es y qué NO es la población

La **población sintética** es un conjunto de registros (`patient`, `waitlist_entry`, `appointment`) **generados proceduralmente** a partir de:
- Datos públicos agregados (conteos por servicio/especialidad, tiempos de espera mediana y promedio, tasas de inasistencia nacionales).
- Supuestos explícitos (distribuciones etarias, de previsión, de prioridad clínica, duración de procedimientos).

**NO es:**
- Una muestra de pacientes reales: no contiene nombres, RUT, sexo, etnia, nacionalidad ni ningún identificador personal.
- Datos de ingreso: se calibra contra la Glosa 06 III-2025 (datos públicos agregados), no se ingiere de bases de pacientes reales.
- Verdad clínica: la prioridad clínica (`clinical_priority`) es un dato **de entrada sintético** que define el usuario. El sistema nunca la infiere.

La población tiene reproducibilidad determinista (mismo seed → mismo dataset) y se versionea por corrida (`synthetic_run.id`, `dataset_digest`).

## 2. Variables por origen

Cada variable tiene un origen: fuente de datos públicos verificados, o **SUPUESTO** (parámetro con justificación explícita en `assumptions.json`).

| Variable | Origen / Tipo | Valor | Justificación | Verificado |
|---|---|---|---|---|
| **Estructura** |
| `health_service_code` | Públicos: `cne_by_service`, `iq_by_service`, `ges_delayed_by_service` | Asignación determinista (Hamilton) | Distribución proporcional a tamaño de lista por servicio (29 SNSS) | ✓ Sí |
| `care_type` | Públicos: `noges_national_by_subtype` | CNE, IQ, GES | Mezcla nacional: 2.994.932 CNE / 417.561 IQ / 80.022 GES retrasadas | ✓ Sí |
| `care_subtype` | Públicos: `noges_national_by_subtype` | Médica (66 %), Dental (20 %), IQ mayor (72,3 %), IQ menor (27,7 %) | Distribución exacta por Hamilton | ✓ Sí (excepto GES: 68 % cobertura sobre 80.022 retrasadas) |
| `specialty` | Públicos: `cne_medical/dental_by_specialty`, `iq_by_specialty` | 80 especialidades CNE, 12 IQ | Distribución por Hamilton + barajado | ✓ Sí |
| **Demográficas** |
| `age_group` | **SUPUESTO** (verified: false) | Pediatría: {0_14: 0,9, 15_19: 0,1, ...}; General: {0_14: 0,06, 15_19: 0,04, 20_44: 0,25, 45_64: 0,33, 65_plus: 0,32} | No hay tabla de edad en Glosa III-2025; pendiente ingesta de edad de la Glosa | ✗ No verificado |
| `insurance` | Públicos: FONASA Cuenta Pública 2025, Tabla N°11 | FONASA A: 2.625.130; B: 5.584.750; C: 2.152.647; D: 3.068.242; Other: 862.688 | Conteos de población inscrita en APS a dic-2023 (verificados). **SUPUESTO**: la lista de espera replica esta composición (proxy) | Conteos ✓; proxy ✗ No verificado |
| **Clínicas** |
| `clinical_priority` | **SUPUESTO** (dato de entrada sintético) | CNE: {p1: 0,05, p2: 0,15, p3: 0,40, p4: 0,40}; IQ: {p1: 0,08, p2: 0,22, p3: 0,40, p4: 0,30}; GES oncológico: {p1: 0,40, p2: 0,40, p3: 0,20, p4: 0} | Distribuciones independientes de espera; el sistema nunca infiere ni sobreescribe prioridad | ✗ No verificado |
| `is_ges` | Públicos: `ges_delayed_by_problem` | 20 problemas mapeados (cataratas, colecistectomía, etc.) | Solo problemas con mapeo a especialidad en `assumptions.json`; cobertura 68 % de las 80.022 retrasadas | ✗ No verificado (pendiente: plazos del Decreto 29) |
| `ges_deadline` | **SUPUESTO**: plazos por problema (30–180 días, per Decreto GES) | Varían: oncológico 30 días, traumatología 90–180 días, etc. | Provisorios; pendiente verificación contra Decreto Supremo 29 (2025) | ✗ No verificado |
| **Administrativas** |
| `commune_code` | Públicos: establecimientos SNSS operativos (345 comunas) | Peso por (comuna, servicio): CESFAM/CGU/CGR ×1, CECOSF ×0,5, PSR ×0,1 | Proxy de población inscrita; solo SNSS operativos | ✗ No verificado (proxy) |
| `establishment_code` | Públicos: establecimientos SNSS | Peso alta complejidad=2, mediana=1, baja=0,5 | Supuesto agregado en la implementación (el plan define solo alta=2, mediana=1) | ✗ No verificado |
| **Espera** |
| `entry_date` | Públicos: media y mediana por (servicio, tipo) | Calculada con lognormal estratificada | Fórmula: `entry_date = as_of - W`, donde `W` ~ LogNormal estratificada | ✓ Sí |
| **Procedimiento** |
| `procedure` | **SUPUESTO** | CNE: "Consulta nueva" por especialidad; IQ: 1–3 procedimientos genéricos | Sin catálogo público desagregado por especialidad e IQ | ✗ No verificado |
| **Historial sintético** |
| `appointment` (pasadas) | **SUPUESTO** | k ~ Poisson(1,5) citas/paciente; lead ~ U{7..90}; fecha ~ U[as_of-730, as_of-1] | Ver sección 5 (inasistencias sintéticas) | ✗ No verificado |

## 3. Fecha de ingreso y tiempos de espera

### Fórmula general

Para cada entrada `i` en un grupo (servicio, tipo):
1. Calcular parámetros lognormal: μ = ln(M), σ = √(2·ln(m/M)) si m > 1,001·M; si no, σ = 0,1 (piso).
   - M = mediana de espera (días), m = media.
   - Si σ < 0,1 se avisa en el informe de calibración.
2. Estratificación: u_i = (π(i) + v_i)/n, donde π es permutación aleatoria de [0, n) y v_i ~ U(0,1).
3. Invocación: W_i = exp(μ + σ·Φ⁻¹(u_i)), recortado a [1, 3650] días, redondeado.
4. `entry_date_i = as_of - W_i`.

**Lognormal inversa:** Φ⁻¹ se vectoriza con AS241 (numpy), sin scipy.

### Garantías GES

- **GES retrasadas:** W = plazo + D, donde D es lognormal ajustada a media y mediana del retraso por problema. Si falta el problema, usa nacional 136/71. Tope 3650 − plazo.
- **GES en plazo:** W ~ U(0, plazo) (SUPUESTO); no hay datos de stock en plazo.

## 4. Inasistencias sintéticas

### Modelo logit

```
logit p_ij = α_{s,c} + γ_spec(j) + β_age[a_i] + β_ins[ins_i] + β_wait·log2(W_ij / M_{s,c}) + β_lead·log2(1 + lead_días/7) + u_i

u_i ~ N(0, σ_u²), σ_u = 0,8
```

- α_{s,c}: intercepto por (servicio, tipo), calibrado por bisección para que E[p] = tasa objetivo.
- γ_spec: efecto aleatorio por especialidad ~ N(0, γ_sd²) (stream propio).
- β_age, β_ins, β_wait, β_lead: parámetros del escenario.
- u_i: fragilidad individual (única correlación entre citas de un paciente).

### Tasas objetivo

| Grupo | Tasa | Fuente | Notas |
|---|---|---|---|
| CNE nacional | 15,65 % | Sepúlveda 2024, Tesis, Repositorio U. de Chile; 1.185.393/7.575.359 citas 2022 | ✓ Verificado |
| CNE Arica (servicio 1) | 22 % | Sepúlveda 2024 | ✓ Verificado |
| CNE Iquique (servicio 2) | 21 % | Sepúlveda 2024 | ✓ Verificado |
| CNE otros (servicios 3–29) | k (escalada) | Supuesto: tasa común k para cuadrar promedio nacional | ✗ No verificado (tabla por servicio no disponible) |
| IQ | 5 % | SUPUESTO (suspensión 6,4–12,9 %, ~50 % por paciente) | ✗ No verificado |

### Escenarios

| Escenario | Descripción | Parámetros |
|---|---|---|
| **`neutral`** (control obligatorio) | Sin efectos de edad ni previsión; solo espera y anticipación | β_age = 0, β_ins = 0, γ_sd = 0, β_wait = 0,15, β_lead = 0,10 |
| **`baseline`** (por defecto) | Efectos de edad; SIN previsión; especialidad aleatoria | β_age = {0_14: +0,10, 15_19: +0,35, 20_44: +0,30, 45_64: 0, 65_plus: −0,20}; β_ins = 0; γ_sd = 0,3 |
| **`ses_gradient`** (sensibilidad) | Efectos de edad + previsión | Igual que baseline + β_ins = {fonasa_a: +0,2, fonasa_b: +0,1, fonasa_c: 0, fonasa_d: −0,1, other: 0} |

### Historial sintético

- Citas pasadas por paciente: k ~ Poisson(1,5), máx. 6.
- Fecha: U[as_of − 730, as_of − 1] (últimos 2 años).
- Especialidad: de una de sus entradas waitlist.
- Anticipación (lead): U{7..90} días.
- Asistencia: Bernoulli(p) → `attended`/`no_show`.
- **Prohibido como feature:** `patient_latent.noshow_frailty` y `appointment_truth.true_noshow_prob` (verdad sintética separada).

### Equidad

- El generador usa edad (sí); previsión (solo en `ses_gradient`); comuna (solo vía servicio).
- Futuro modelo ML: **no puede usar** comuna ni previsión como features.
- Evaluación: medir calibración y daño (sobreagendamiento con colisión) por comuna, grupo etario y previsión.
- `neutral` es control obligatorio para verificar que la tubería no crea disparidad sola; puede haber disparidad por servicio (Arica, Iquique) se reporta sin fallar.

## 5. Oferta (cupos, sesiones, pabellones)

### Ley de Little

Throughput objetivo: θ_{s,c} = 7·L_{s,c} / m_{s,c} (entradas/semana), donde m es mediana de espera.
- CNE nacional: ~52.900 entradas/semana.
- IQ nacional: ~7.420 entradas/semana.

Escalado para tamaño sintético N:
$$\tilde{\theta} = \theta \cdot \frac{N}{L_U} \cdot \text{capacity\_multiplier} (1,0)$$

### Sesiones y pabellones (generador 0.3.0)

| Tipo | Duración | Horario | Frecuencia | Notas |
|---|---|---|---|---|
| **CNE (consulta)** | 240, 180, 120 o 60 min (una por celda) | Desde 08:30 o 14:00 | Lunes-viernes | 20 min/consulta (SUPUESTO); la sesión de 60 min es un supuesto sin fuente (`verified: false`) |
| **IQ (pabellón)** | 360 min (6 h) | 08:00-14:00 | Lunes-viernes | Bloques; 30 min recambio; utilización 85 % |

**Algoritmo (`session_schedule` en `synthetic/capacity.py`).** Es una función pura y determinista (sin semilla) que usan el generador y la oferta de la simulación (`simulation/supply.py`). Recibe las celdas (servicio, especialidad) con sus minutos por semana `m_c`, las duraciones posibles `D`, las semanas y un multiplicador, y devuelve `(semana, celda, duración)`:

1. **Duración por celda.** Cada celda usa una sola duración: la mayor `d` de `D` tal que `m_c · P ≥ d`, con `P = cne_session_reference_weeks = 26` semanas (SUPUESTO). Si ni la menor cabe entera, usa la menor mientras `m_c · P ≥ min(D)/2`; con menos (menos de 30 min en el periodo en CNE) la celda queda sin oferta (limitación declarada). Las celdas grandes siguen con 240 min y conservan sobrecupo.
2. **Reparto en el tiempo por déficit acumulado dentro de cada grupo (servicio, tipo), con calentamiento.** El reparto se simula desde la semana `−W` hasta `H−1` (con `W = cne_session_reference_weeks = 26`, también en pabellón) y se descartan las sesiones con semana negativa. La semana `w` el grupo puede haber ofrecido a lo más `T(w) = Σ m_c · (w + 1 + W)` (solo celdas con oferta). Mientras `ofrecido + d ≤ T(w)`, se emite una sesión a la celda con mayor `déficit/d` (`déficit = m_c·(w+1+W) − ofrecido_c`; desempate por especialidad) si su déficit llega a `d/2`; si ninguna llega y sobran `max(D)` minutos, a la de mayor déficit positivo. Cota exacta: la oferta acumulada del grupo está en `[T − L, T]` con `L = max(D)`; la de la ventana hasta la semana `w` es esa menos la del calentamiento (también en `[T₀ − L, T₀]`), así que queda a menos de `L` de `rate·(w+1)` por ambos lados. **Defecto de arranque en frío corregido:** sin calentamiento el déficit partía de cero y las primeras semanas casi no tenían sesiones (a N=10.000: 3, 20, 35, 44, 52, 59 sesiones en las semanas 0 a 5 y ~60 después; a N=100.000: 95 y 381 en las semanas 0 y 1 y ~450 después; a N=1.000 con horizonte de 4 semanas, ningún bloque), un artefacto del mismo tipo que el de §8, punto 9.
3. **Pabellón** usa el mismo algoritmo con `D = {360}` (no hay bloques de 180: hay procedimientos de 240 min más 30 de recambio).
4. **Hospital, agenda y día.** Las sesiones de cada servicio se reparten entre sus hospitales con un reparto ponderado determinista (pesos por complejidad). Cada agenda aloja hasta 10 sesiones por semana (lunes-viernes, mañana y tarde) y cada pabellón hasta 5 bloques por semana; el día rota por recurso, de modo que el total por semana y por día de la semana queda parejo (ver §8, punto 9).

**Sobrecupo.** El sobrecupo máximo de una sesión es `O_b = floor(0,25·C_b)` con `C_b = duración/unit_min`: una sesión de 60 min (3 cupos) no admite sobrecupo y una de 120 min (6 cupos) admite 1. El cambio de equidad (qué proporción de los cupos CNE queda sin sobrecupo posible) se reporta en `supply_coverage` de la simulación (`seats_without_overbooking_share`).

### Supuestos de capacidad

- Minutos/semana: CNE θ̃ / (1 − t_s) × 20 min; IQ θ̃ / (1 − t_IQ) × (E[dur] + 30) / 0,85.
- `capacity_multiplier = 1,0` (no hay margen de seguridad ni déficit respecto a ley de Little).
- `iq_utilization = 0,85` es un **estándar de política**, no la realidad chilena observada: IPSUSS 2022 (Aguilar y Velasco) informa que se usa cerca de 60 % de las horas habilitadas de pabellón (2017-2019). No se cambia el valor por ahora porque cambiaría la capacidad calibrada (ver `docs/data-sources.md`).
- Duraciones de sesión (`cne_session_lengths_min`, `iq_block_lengths_min`) y periodo de referencia (`cne_session_reference_weeks`): SUPUESTOS, `verified: false`; la duración de 60 min no tiene fuente.
- Zona horaria: America/Santiago (zoneinfo).

## 6. Calibración de la población (C1–C9)

Se ejecuta con N=100.000, seed=42 (corrida canónica). El informe de calibración está en `results/synthetic_calibration_baseline_seed42_n100000.json`.

### Criterios

| ID | Chequeo | Métrica | Tolerancia | Severidad | Resultado |
|---|---|---|---|---|---|
| **C1** | Distribución de (tipo, servicio, especialidad, problema, comuna, edad, previsión) | Total Variation Distance (TVD) por grupo | K/(2n) + 1e-9 | **Estricto** | ✓ 11/11 grupos pasan |
| **C2** | Media y mediana de espera por (servicio, tipo) con n ≥ 30 | Mediana ±max(2 %, 1 día); media ±3 % | — | **Estricto** | ✓ 58 grupos, 0 fuera de tolerancia |
| **C3** | Mezcla nacional CNE e IQ | Media y mediana ±5 % vs 341/242 (CNE) y 394/264 (IQ) | — | **Estricto** | ✓ Obs: CNE 340,5/247; IQ 393,8/271 |
| **C4** | Razón registros/personas por (servicio, tipo) | |razón − objetivo| | ±(0,01 + 1/P) | **Estricto** | ✓ Peor: 0,0049 |
| **C5** | Retraso GES por problema (n ≥ 30) y mezcla de los 20 problemas mapeados | Media y mediana por problema; media de la mezcla mapeada | Como C2 | **Estricto** | ✓ 13 problemas con n ≥ 30; mezcla mapeada 132,96 vs 132,96 |
| **C5 nacional** | Retraso GES nacional vs Glosa (136 / 71 días) | Media y mediana | ±5 % | Blando | ✗ mediana 76 vs 71 (+7 %); media 132,96 vs 136 ✓. El nacional incluye problemas GES no mapeados |
| **C6** | (a) Media de p verdadera por (servicio, tipo) en la muestra: verifica la bisección; (b) media de p con un sorteo independiente de la fragilidad u (no tautológico); (c) tasa realizada del historial global y por servicio | (a) error ≤ 1e-4; (b) ±(3·σ_p/√n + 0,5 pp), grupos con n ≥ 200; (c) ±(3·EE + 0,5 pp) | — | **Estricto** | ✓ (a) error 0; (b) desviación máxima 0,88 pp, 5 grupos omitidos; (c) 14,76 % vs 14,66 % esperado, 29 servicios dentro de banda |
| **C7** | Participación IQ mayor | ±3 pp vs 72,347 % objetivo | — | **Estricto** | ✓ Obs: 72,347 % |
| **C8** | Minutos programados/semana vs objetivo (solo celdas con oferta posible) | Unilateral estricta por (servicio, tipo): oferta ≤ meta y ≥ meta − max(5 %, 1 sesión larga/H) | — | **Estricto** | ✓ Peor desvío 7,38 min (generador 0.3.0) |
| **C9a** | E[p²] en CNE (egresos "dos inasistencias") | 3,0 % ± 1,5 pp | — | **Blando** | ✓ Obs: 3,83 % (dentro de ±1,5 pp) |
| **C9b** | Cobertura GES mapeada | Solo informe | — | **Blando** | ✓ 54.583 / 80.022 = 68,2 % (20 problemas mapeados) |
| **C9c** | Independencia servicio × especialidad | V de Cramér solo informe | — | **Blando** | ✓ V = 0,0307 (bajo; independencia aproximada) |

**Resultado global (seed 42, N=100.000):**
- ✓ 26 chequeos estrictos pasan; 0 fallan.
- ✓ 1 blando: mediana GES nacional (76 vs 71 días, fuera de la tolerancia de ±5 % = ±3,55 días); se informa sin fallar (el nacional incluye problemas no mapeados).
- Celdas (servicio, especialidad) con entradas pero sin sesiones en el horizonte: 319 de 2.216 (generador 0.3.0; con el 0.2.0 eran 613). Son las celdas con menos de media sesión de 60 min en el periodo de referencia. Sus minutos por semana sin oferta posible suman 182 de 121.393 (0,1 %) y no entran en la meta de C8.

### Alcance de los chequeos estrictos

La mayoría de los chequeos estrictos verifica lo que el generador impone por construcción: C1 (márgenes exactos por el método de Hamilton), C2 (la muestra estratificada se reescala para fijar media y mediana), C5 sobre la mezcla mapeada, C6 (a) (la bisección) y C6 (c) (tasa realizada frente a su propia E[p]). Sirven para detectar errores de implementación, no para validar la población contra la realidad. Los contrastes que no salen por construcción son C3 (mezcla nacional CNE e IQ), C6 (b) (sorteo independiente de la fragilidad) y los chequeos blandos nacionales de C5 y C6; de estos, la mediana GES nacional falla (76 vs 71 días) y la tasa del historial CNE queda 0,76 pp sobre el objetivo (16,41 % vs 15,65 %). C8 se recalcula en los tests directamente desde los objetivos y supuestos, sin usar la función del generador (incluida la regla de qué celdas pueden recibir oferta).

## 7. Determinismo, reproducibilidad y versionado

### Streams de números aleatorios

Cada componente usa `np.random.SeedSequence(seed, spawn_key=(stream_id,))` con stream propio (IntEnum):

| Stream | Propósito |
|---|---|
| `ALLOCATION = 1` | Asignación determinista a servicios y especialidades |
| `ATTRS = 2` | Atributos (edad, previsión, prioridad clínica) |
| `WAIT = 3` | Tiempos de espera (lognormal estratificada) |
| `PRIORITY = 4` | (Reservado) |
| `GES = 5` | Asignación de problemas GES |
| `LATENT = 6` | Fragilidad u_i (noshow) |
| `HISTORY = 7` | Historial de citas pasadas |
| `SPEC_EFFECTS = 8` | Efectos aleatorios por especialidad γ_spec |
| `PATIENT_LINK = 9` | Asignación de entradas a pacientes |

### Versionado

```
synthetic_run.id = uuid5(NS, "seed:size:scenario:horizon:as_of:targets_sha:params_sha")
```

Determinista: mismo seed, size, scenario, as_of y configuración → mismo run_id.

### Dataset digest

`dataset_digest = sha256(tabla_1 + tabla_2 + ... + tabla_n)`, donde cada tabla es CSV ordenado por id, sin created_at, 6 decimales en floats. Incluye las 7 tablas por corrida y los catálogos (prefijo `catalog_`). Un test fija el digest de N=3.000, seed 42, baseline y lo verifica también en un subproceso con otro `PYTHONHASHSEED`. El informe se nombra `synthetic_calibration_{escenario}_seed{S}_n{N}.json` para que `neutral` y `ses_gradient` no sobrescriban la corrida canónica.

### Reemplazo

`--replace` borra la corrida existente (cascada) y carga la nueva con el mismo run_id, todo en una sola transacción: si algo falla, la corrida anterior queda intacta. Si la corrida ya tiene planes (`schedule_run`), citas del programador o la simulación, o resultados de políticas (`policy_result`), `--replace` aborta e informa cuántas filas hay; para borrarlas igual hay que pasar `--drop-downstream` (así no se pierden en silencio planes en revisión ni resultados, incluidos los negativos). La base exige que cada fila hija pertenezca a la misma corrida que su padre (FK compuestas por `run_id`).

## 8. Desviaciones de la implementación respecto del plan

1. **Reescalado de esperas para grupos pequeños (C2):** La muestra estratificada se reescala (mediana fija, potencia sobre la media) para cumplir C2 incluso con especialidades raras. No documentado en el plan.

2. **C5 nacional GES (estricto vs blando):** Comparación estricta contra mezcla de 20 problemas mapeados (132,96 días observados vs 132,96 objetivo). Comparación blanda contra nacional agregado 136/71 (que incluye problemas no mapeados). Los 20 mapeados cubren 54.583 de 80.022 = 68 %.

3. **C6 objetivo de historial:** el objetivo estricto es la media de p del propio historial (~14,66 %). La comparación con las tasas objetivo es blanda y separada por tipo: CNE 16,41 % vs 15,65 %, IQ 5,32 % vs 5 %; difieren porque el historial usa anticipación U{7..90} sin término de espera.

4. **C1 especialidad|subtipo CNE:** usa la cota K/n en lugar de K/(2n) del plan, porque el total de entradas de cada subtipo depende a su vez de otro reparto de Hamilton (dos redondeos encadenados).

5. **Peso de hospitales de baja complejidad:** 0,5 (agregado en implementación; el plan define solo alta=2, mediana=1).

6. **Escenario neutral:** Anula edad, previsión y especialidad; mantiene β_wait y β_lead (no son atributos protegidos).

7. **Citas del historial:** guardan la especialidad (`appointment.specialty_code`, de una de las entradas del paciente), pero no tienen término de espera (no hay episodios pasados): el efecto de la espera no se puede aprender desde el historial. Ver `docs/design/synthetic-noshow-review.md`.

8. **Celdas sin sesiones:** hay celdas (servicio, especialidad) con entradas pero ninguna sesión en el horizonte. Con el generador 0.2.0 y N=100.000 eran 613 de 2.216; con el 0.3.0 son 319 de 2.216: las celdas con menos de media sesión de 60 min en 26 semanas (el informe de calibración las cuenta y reporta sus minutos por semana, 182 de 121.393 (0,1 %), que no entran en la meta de C8).

9. **Oferta concentrada (corregida en 0.2.0, 2026-10-09):** hasta la versión 0.1.0 todas las agendas y pabellones usaban la misma fase (0,5) para repartir sus sesiones: cada recurso con una sola sesión en 26 semanas caía en la semana 13, y con a lo más un bloque por semana el pabellón operaba solo los lunes. En la corrida canónica (N 100.000, 26 semanas) las sesiones CNE iban de 12 a 3.149 por semana y 3.276 de 4.249 bloques de pabellón caían en lunes (ninguno en viernes). Con la fase por recurso y la rotación del día: 237-296 sesiones CNE por semana, 150-174 bloques de pabellón por semana y 799-933 bloques por día de lunes a viernes. Mismos totales y mismas sesiones por celda; cambian el digest (y `model_version` de `noshow`, que lo incluye) pero no el `run_id`. Test: `synthetic/tests/test_synthetic_supply.py`.
10. **Oferta de duración variable (0.3.0, 2026-10-10):** con sesiones CNE de 240 min fijos, a N=10.000 solo el 37 % de las celdas CNE recibía alguna sesión y el 76 % del stock quedaba en celdas con sesión. La oferta pasa a sesiones de 240/180/120/60 min por celda y repartidas por déficit acumulado (ver §5): las celdas pequeñas reciben sesiones cortas sin inflar los minutos totales. Costo: las sesiones de 60 min no admiten sobrecupo (`O_b = floor(0,25·C_b) = 0`), un cambio de equidad que se reporta. Cambian el digest y el `model_version` de `noshow`; también el `run_id`, porque cambian los supuestos (`params_sha256`). Las cifras de calibración canónicas y los resultados guardados (`schedule_*.json`, `simulation.json`, informes) se regeneraron con la corrida canónica `d7a0c251-9a0f-5d0a-9941-5140560fb5b2`: 26 chequeos estrictos pasan, 0 fallan y falla 1 informativo (mediana GES nacional).

## 9. Limitaciones, supuestos de independencia y pendientes

### Limitaciones documentadas

1. **Edad y previsión:** la edad es SUPUESTO (`verified: false`). La previsión usa conteos verificados de la población inscrita en APS (FONASA, Cuenta Pública 2025, Tabla N°11), pero que la lista de espera replique esa composición es un SUPUESTO de proxy. Pendiente: ingerir las tablas de edad y previsión de la Glosa 06.
2. **Plazos GES:** Provisorios del Decreto 29; pendiente verificación en Diario Oficial.
3. **Tasas de inasistencia por servicio:** Solo Arica (22 %) e Iquique (21 %) de Sepúlveda; resto escalado con k común. Tabla completa no disponible (PDF bloqueado).
4. **Procedimientos IQ:** Genéricos; sin catálogo público desagregado.
5. **Inasistencia a cirugía:** Asumida 5 %; la literatura reporta suspensión (6,4–12,9 %), no inasistencia pura.

### Supuestos de independencia (críticos)

- Servicio × especialidad aproximadamente independientes (V de Cramér = 0,0307, bajo).
- Espera **no** modula por especialidad (sin dato).
- Pools CNE/IQ disjuntos (sin solapamiento de pacientes).
- Previsión independiente de edad (SUPUESTO no verificado).

**Nota:** Se reportan todas las limitaciones en el informe de calibración y en `docs/data-sources.md`.

### Pendientes antes de producción

- Extender ingesta con tabla de edad de la Glosa 06 III-2025.
- Obtener tabla de inasistencia por servicio (29 servicios) o solicitar por Ley de Transparencia.
- Verificar plazos GES contra Decreto Supremo 29 (2025) en Diario Oficial.

## 10. Uso

### Ambiente

```bash
make up       # Levanta PostgreSQL + API + dashboard
make migrate  # Ejecuta alembic upgrade head
```

### Generar población sintética

```bash
make synth                       # Por defecto: size=100000, seed=42, scenario=baseline
make synth SIZE=50000 SEED=1234  # Custom: tamaño y semilla
```

Opciones avanzadas:

```bash
uv run --package synthetic prioriza-synth generate \
  --size 100000 \
  --seed 42 \
  --scenario baseline|neutral|ses_gradient \
  --horizon-weeks 26 \
  --as-of 2025-09-30 \
  --load                      # Carga a PostgreSQL \
  --replace                   # Reemplaza si existe (aborta si hay planes o resultados) \
  --drop-downstream           # Con --replace: borra también planes y resultados de la corrida \
  --out data/synthetic \
  --report-dir results
```

### Validación

```bash
uv run --package synthetic prioriza-synth validate \
  --size 100000 \
  --seed 42 \
  --scenario baseline
```

Retorna código de salida 2 si falla calibración estricta.

### Regenerar targets (datos públicos)

```bash
uv run --package synthetic prioriza-synth build-targets \
  --processed-dir data/processed \
  --reference glosa06_2025q3
```

Lee parquets de ingesta y regenera `calibration_targets.json`.

### Estructura de archivos

```
data/
  synthetic/
    <run_id>/
      patient.parquet
      waitlist_entry.parquet
      resource.parquet
      slot.parquet
      appointment.parquet
      patient_latent.parquet
      appointment_truth.parquet
      manifest.json            # config, hashes, informe resumido
results/
  synthetic_calibration_baseline_seed42_n100000.json  # informe completo
```

---

**Última actualización:** 2026-10-10. **Disclaimer:** Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.
