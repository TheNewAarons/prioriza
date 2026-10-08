# Model Card: Modelo de Inasistencias (noshow)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Advertencia: limitaciones del modelo en datos sintéticos

**Con datos sintéticos, estas métricas validan el pipeline de ingesta, características y entrenamiento (que el modelo aprende la estructura que el generador introdujo), pero NO prueban desempeño en pacientes reales.** El modelo solo puede recuperar la estructura que existe en los datos de entrenamiento. En particular:

- La fragilidad latente individual (u_i) es invisible para cualquier modelo; el techo de AUC está en ~0,65 incluso con variables observables.
- El historial sintético no tiene término de espera (vale 0 en el generador), así que el modelo no puede aprender el efecto de la espera que sí tendrán las citas futuras (hallazgo A2).
- El modelo no ve servicio de salud, comuna ni edad (excluidos por equidad), así que no distingue que Arica (22 %) e Iquique (21 %) tienen tasas base más altas ni el efecto de la edad que el generador sí usa. Las brechas resultantes se reportan en la sección Equidad.

## Resumen

El modelo predice la probabilidad de inasistencia (no presentarse a la cita programada o cirugía) por paciente-cita, basándose en historial previo de asistencia, anticipación (días entre agendamiento y cita), especialidad y día de la semana.

**Uso previsto:** Insumo para el sobreagendamiento controlado en `scheduler/`, que ajusta el número de pacientes asignados a cada cupo sabiendo que una fracción no se presentará. El sistema apoya la decisión del planificador, no la toma: todo plan generado requiere revisión humana antes de implementarse.

**Usos fuera de alcance:**
- Excluir o sancionar pacientes con alta probabilidad predicha.
- Inferir características clínicas del paciente (edad, sexo, condición de salud).
- Predecir sobre datos reales sin recalibración en servicio de salud real.
- Tomar decisiones sobre asignación de recursos o cambios de política sin validación institucional.

## Datos

### Corrida

| Parámetro | Valor |
|---|---|
| `run_id` | `32c9e349-74f9-5c85-bf4b-990796b47323` |
| Semilla (`seed`) | 42 |
| Tamaño de la corrida (`size`) | 100.000 entradas en lista de espera (85.083 pacientes; 127.517 citas de historial) |
| Escenario | `baseline` (edad sí, previsión no, especialidad aleatoria con σ=0,3) |
| Fecha de referencia (`as_of`) | 2025-09-30 |
| Hash dataset sintético (`dataset_sha256`) | `6ef9a83e7b146304e59c854e2910fef53dd902a12e46d78c04dcd5cea106b6fe` |
| Versión del generador | 0.1.0 |

### Split temporal

| Bloque | Período | n | Tasa de inasistencia |
|---|---|---|---|
| **Entrenamiento** | 2023-10-01 a 2024-12-02 | 75.181 | 14,76 % |
| **Calibración** | 2024-12-03 a 2025-04-01 | 20.714 | 15,22 % |
| **Prueba** | 2025-04-02 a 2025-09-29 | 31.622 | 14,46 % |

Split temporal en tres bloques disjuntos (no aleatorio): prueba = últimos 180 días, calibración = 120 días previos, entrenamiento = el resto. Los hiperparámetros son fijos (sin búsqueda). El conjunto de calibración se usa para ajustar el calibrador y elegir el modelo principal; el conjunto de prueba no participa en ninguna elección.

## Variables usadas

### Características (features)

| Variable | Tipo | Origen | Descripción |
|---|---|---|---|
| `lead_days` | Numérica | Cita | Días entre agendamiento y la cita programada |
| `prior_attended` | Numérica | Historial | Conteo de citas previas a las que el paciente asistió (al agendar esta cita) |
| `prior_no_show` | Numérica | Historial | Conteo de citas previas en las que el paciente no se presentó (al agendar esta cita) |
| `specialty_code` | Categórica | Especialidad | Código de la especialidad de la cita (ej: `cne_medical:cardiologia`, `iq:cirugia_digestiva`) |
| `care_type` | Categórica | Catálogo | `consultation` (CNE) o `surgery` (IQ) |
| `weekday` | Categórica | Cita | Día de la semana (1–7, lunes a domingo) |

**Regla de historial previo:** `prior_attended` y `prior_no_show` cuentan solo citas del mismo paciente con fecha de cita (`scheduled_start`) **estrictamente anterior** a la fecha de agendamiento (`scheduled_start - lead_days`), para que ninguna variable use información posterior a la decisión.

**Variable constante descartada:** `time_band` (mañana/tarde) era constante en el historial sintético (todas las citas a las 12:00 UTC) y se descartó automáticamente.

## Variables excluidas

| Variable | Motivo |
|---|---|
| `sex` (sexo) | Atributo protegido (CLAUDE.md). No existe en los datos sintéticos. |
| `ethnicity` (etnia) | Atributo protegido (CLAUDE.md). No existe en los datos sintéticos. |
| `nationality` (nacionalidad) | Atributo protegido (CLAUDE.md). No existe en los datos sintéticos. |
| `age_group` (grupo etario) | No está en la lista de variables permitidas. Aunque el generador la usa, incluirla concentraría el sobreagendamiento en 15–44 años (hallazgo M3 de la revisión del generador). Se usa solo para medir equidad. |
| `insurance` (previsión) | Proxy evidente de nivel socioeconómico. Se usa solo para medir equidad. |
| `commune_code` (comuna) | Proxy geográfico de nivel socioeconómico, etnia y nacionalidad. Se usa solo para medir equidad. |
| `health_service_code` (servicio de salud) | Determinado por la comuna (V de Cramér = 1,0 en el sintético): mismo proxy geográfico. Costo: el modelo no ve que Arica e Iquique tienen tasas más altas (~22 % y 21 %). |
| `distance_km` (distancia) | Permitida si existe, pero no hay coordenadas ni establecimiento en las citas del historial; usarla exigiría la comuna del paciente, que es un proxy excluido. |
| `duration_min` (duración) | En consultas vale siempre 20 min y en cirugías delata el procedimiento (hallazgo B2); redundante con la especialidad y con un sesgo asimétrico entre tipos de atención. |
| `wait_days` (días de espera) | Permitida, pero las citas del historial no tienen entrada asociada (`entry_id` nulo) y el generador fija el término de espera en 0 (hallazgo A2 de la revisión). Se incluye automáticamente solo si tiene valores en el período de entrenamiento. |
| `clinical_priority` (prioridad clínica) | No existe en el historial (sin entrada asociada). Además, el sistema no debe aprender de la prioridad clínica para decidir sobreagendamiento. |
| `noshow_frailty`, `true_noshow_prob` (verdad sintética) | Verdad generadora: prohibida como variable de cualquier modelo. |

## Modelos y calibración

### Modelos candidatos

Se evaluaron:
- **Baseline**: tasa histórica por especialidad, suavizada hacia la media global (suavizado m=20).
- **Regresión logística** (modelo principal).
- **Gradient Boosting** (`HistGradientBoostingClassifier`).

### Regla de calibración

**Isotónica si n_minoria >= 1000 en calibración; Sigmoide si no.**

En esta corrida: 3.152 eventos de inasistencia en calibración (clase minoritaria); se aplica calibración isotónica.

### Selección del modelo principal

**Criterio**: Brier fuera de pliegue (5 bloques contiguos) en el conjunto de calibración, con el modelo ya calibrado.

| Modelo | Brier OOF |
|---|---|
| Logistic regression (calibrado) | 0,125976 |
| Gradient boosting (calibrado) | 0,126566 |

**Modelo elegido**: Regresión logística. Coeficientes (top 10 por valor absoluto) en `results/noshow.json`.

### Nota sobre calibración

La calibración isotónica empeoró **levemente** el Brier de la regresión sin calibrar:
- Sin calibrar: Brier = 0,120548
- Calibrada (isotónica): Brier = 0,120621

También empeoraron levemente ECE (0,006438 → 0,007222) y log loss (0,400131 → 0,400252). Causa probable: la isotónica se ajusta en el bloque de calibración, cuya tasa observada (15,22 %) es mayor que la de prueba (14,46 %), y sube la probabilidad media predicha de 0,1459 a 0,1517. Como el proceso sintético es estacionario, esa diferencia de tasas entre bloques es variación muestral, no deriva. Se reporta tal cual: la regla de calibración se fijó antes de mirar el conjunto de prueba y no se cambia a posteriori. La logística ya venía bien calibrada; con datos reales, que sí tienen deriva, conviene recalibrar con el periodo más reciente.

## Métricas en prueba

### Modelos comparados

| Modelo | AUC | Brier | Log Loss | ECE | Predicha (media) | Observada |
|---|---|---|---|---|---|---|
| Baseline (especialidad) | 0,6022 | 0,1215 | 0,4035 | 0,0087 | 0,1474 | 0,1446 |
| Gradient Boosting, sin calibrar | 0,6105 | 0,1218 | 0,4052 | 0,0176 | 0,1443 | 0,1446 |
| Gradient Boosting, calibrado | 0,6095 | 0,1215 | 0,4037 | 0,0092 | 0,1507 | 0,1446 |
| Regresión logística, sin calibrar | 0,6248 | 0,1205 | 0,4001 | 0,0064 | 0,1459 | 0,1446 |
| Regresión logística, calibrada (PRINCIPAL) | 0,6239 | 0,1206 | 0,4003 | 0,0072 | 0,1517 | 0,1446 |
| Oráculo (verdad sintética) | 0,7370 | 0,1110 | 0,3660 | 0,0037 | 0,1459 | 0,1446 |

### Comparación: Modelo principal vs. Baseline

| Métrica | Valor | Rango 95 % |
|---|---|---|
| Δ Brier | −0,000885 | [−0,001189; −0,000577] |
| Significancia (α=0,05) | **Sí (p<0,05)** | — |
| Unidad de remuestreo | Paciente (n=1.000 resamples) | — |

El modelo principal **supera al baseline en Brier** y el IC 95 % no incluye 0. La mejora es pequeña en términos absolutos (0,0009 sobre un Brier de 0,1215, ~0,7 %), coherente con el techo de AUC descrito en Limitaciones. El remuestreo es por paciente porque las citas de un mismo paciente comparten la fragilidad latente.

### Brecha frente al oráculo

| Métrica | Modelo | Oráculo | Brecha |
|---|---|---|---|
| AUC | 0,6239 | 0,7370 | −0,1131 |
| Brier | 0,1206 | 0,1110 | +0,0096 |

La brecha en AUC (0,11 puntos) reflejaría la fragilidad latente no observada (u_i) y el efecto de la espera en el historial, ambos invisibles para el modelo.

## Equidad

### Por grupo etario

| Grupo | Predicha | Verdadera | Observada | Gap (pred−verdad) | n |
|---|---|---|---|---|---|
| 0–14 años | 0,1825 | 0,1743 | 0,1784 | +0,0082 | 3.391 |
| 15–19 años | 0,1597 | 0,1861 | 0,1672 | −0,0264 | 1.364 |
| 20–44 años | 0,1498 | 0,1755 | 0,1707 | −0,0257 | 7.281 |
| 45–64 años | 0,1472 | 0,1367 | 0,1373 | +0,0105 | 9.965 |
| 65+ años | 0,1457 | 0,1173 | 0,1172 | +0,0285 | 9.621 |

**Máxima brecha**: 2,85 pp en 65+ (sobreestimación; el modelo predice 14,57 % cuando la verdad es 11,73 %).

**Impacto en sobreagendamiento**: Excluir `age_group` como feature implica que el modelo no puede ajustar tasas por edad. La brecha en 65+ (+2,85 pp) significa que el sobreagendamiento se concentrará sobre adultos mayores. Inversamente, los grupos 15–44 serán subestimados. Esto es un costo aceptado para evitar que el modelo distorsione automáticamente la demanda por edad.

### Por tipo de atención

| Tipo | Predicha | Verdadera | Observada | Gap | n |
|---|---|---|---|---|---|
| Consulta (CNE) | 0,1679 | 0,1621 | 0,1602 | +0,0058 | 26.900 |
| Cirugía (IQ) | 0,0591 | 0,0535 | 0,0557 | +0,0056 | 4.722 |

**Máxima brecha**: 0,58 pp. Muy bien calibrada.

### Por previsión

| Previsión | Predicha | Verdadera | Gap | n |
|---|---|---|---|---|
| FONASA A | 0,1513 | 0,1432 | +0,0081 | 5.867 |
| FONASA B | 0,1518 | 0,1462 | +0,0056 | 12.378 |
| FONASA C | 0,1524 | 0,1472 | +0,0052 | 4.702 |
| FONASA D | 0,1512 | 0,1470 | +0,0042 | 6.811 |
| Otro | 0,1520 | 0,1449 | +0,0072 | 1.864 |

**Máxima brecha**: 0,81 pp en FONASA A. Las brechas son parejas entre grupos (+0,4 a +0,8 pp): reflejan la sobrepredicción global del modelo calibrado en prueba (0,1517 frente a 0,1446 observado; ver Nota sobre calibración), no un efecto de la previsión. En el escenario `baseline` el generador no usa la previsión (β_ins = 0), así que aquí no se puede detectar daño por previsión; para eso está el escenario `ses_gradient`.

### Por servicio de salud

**29 servicios evaluados** (n ≥ 200 cada uno). Los dos con mayor brecha frente a la verdad:

| Servicio | Predicha | Verdadera | Observada | Gap (pred−verdad) | n |
|---|---|---|---|---|---|
| 1 (Arica) | 0,1534 | 0,1976 | 0,2037 | −0,0442 | 427 |
| 2 (Iquique) | 0,1607 | 0,1979 | 0,2080 | −0,0371 | 678 |

**Máxima brecha**: −4,42 pp en Arica (subestimación; la verdad es 19,76 %, el modelo predice 15,34 %). Iquique: −3,71 pp. Efecto sobre el sobreagendamiento: en Arica e Iquique se sobreagendaría menos de lo que la inasistencia real justificaría, con más cupos perdidos.

**Explicación**: El modelo excluye `health_service_code` por ser proxy de geografia. En datos sintéticos, el servicio está completamente determinado por la comuna (V de Cramér = 1,0). Sin acceso al servicio, el modelo no puede aprender que Arica e Iquique tienen tasas base más altas (~22 % y 21 % vs 15,65 % nacional). Este es un costo aceptado del enfoque de equidad: se prefiere no usar proxies que compensar a posteriori en el plan.

### Por comuna

**338 comunas** en el dataset de prueba; 31.622 citas.

| Métrica | Valor |
|---|---|
| Comunas con n ≥ 200 | 44 / 338 |
| Máxima brecha (gap_vs_truth) | −0,0460 (comuna 15101, servicio de Arica: predicha 0,1551, verdadera 0,2011, n = 374) |
| Análisis | El generador no tiene efecto propio de comuna (solo vía servicio), así que las brechas por comuna reproducen las del servicio. La mayoría de las comunas no llega a n = 200 en prueba; un análisis por comuna con poder suficiente necesita estimadores agrupados o con contracción (hallazgo M3). |

**Nota**: En datos reales, la comuna sí podría tener efecto causal (acceso a transporte, calidad de comunicación, etc.). Este análisis sintético no detectaría ese daño incluso si existiera.

## Limitaciones

### 1. Brecha con el oráculo y techo de AUC

La brecha de AUC frente al oráculo (0,11 puntos) es casi toda explicada por la fragilidad latente individual (u_i ~ N(0, 0,8²)) que ningún modelo con variables observables puede recuperar. Con el historial sintético tan escaso (k ~ Poisson(1,5) citas/paciente en 730 días), incluso agregando todas las variables disponibles se llega a AUC ~0,63–0,65, frente a 0,74 del oráculo. **Es el techo práctico**: no es un fallo del modelo, sino una limitación de los datos.

### 2. Espera no aprendible desde el historial

El generador fija el término de espera en 0 para todas las citas del historial (hallazgo A2 de la revisión). Las citas futuras sí dependen de la espera (β_wait = 0,15), pero el modelo entrenado en historial no puede aprender ese efecto. Sesgo predicho al aplicar a citas futuras:
- Por especialidad: brecha de ±2,1 pp en promedio (rango −8,7 a +7,4 pp).
- Por quintil de espera: −2,6 pp en el quintil de mayor espera, +2,7 pp en el de menor espera.

Estas cifras son de la revisión del generador (N = 20.000), no de esta corrida.

**Impacto**: El sobreagendamiento recaerá más sobre pacientes que esperan poco y menos sobre quienes esperan mucho (y en GES). Hoy no hay mitigación implementada; queda pendiente para cuando el historial sintético tenga término de espera.

### 3. Proceso estacionario

El historial sintético no tiene deriva temporal ni estacionalidad (sin parámetro de deriva). Un split temporal equivale estadísticamente a uno aleatorio en un proceso estacionario y no prueba robustez a cambios de política o cambios demográficos en el tiempo real.

### 4. Franja horaria constante

En el historial sintético, todas las citas están a las 12:00 UTC (franja horaria constante). La variable `time_band` se descartó automáticamente. En datos reales, la hora de la cita sí importa; el modelo será insensible a este efecto.

### 5. Persistencia con joblib

El modelo se persiste con joblib, que usa pickle. **Solo se cargan artefactos producidos por el pipeline de Prioriza.** No se carga código externo desde el modelo.

### 6. Proxies en datos reales

Aunque el sintético excluye correctamente sexo, etnia y nacionalidad, en datos reales habría proxies:
- La especialidad delata el sexo (ej: ginecología, urología, mama).
- El servicio y la comuna delatan etnia y nacionalidad (ej: Arica, Iquique, Araucanía).
- Las especialidades pediátricas determinan la edad (correlación alta con edad < 18).

Si el modelo se aplica a datos reales sin recalibración, estos proxies pueden reintroducir sesgos protegidos. Se requiere auditoría de equidad en servicio.

## Reproducción

### Generar población sintética y entrenar modelo

```bash
# Generar población sintética (100.000 pacientes, seed 42, escenario baseline)
make synth
# (carga a PostgreSQL; sin base de datos basta con escribir los parquet:)
# uv run --package synthetic prioriza-synth generate --size 100000 --seed 42 --no-load

# Entrenar modelo de inasistencias
make train-noshow
# Equivalente a:
# uv run --package noshow prioriza-noshow train --seed 42 --size 100000 --scenario baseline
# (--run-dir data/synthetic/<run_id> fija una corrida si hay varias con esos parámetros)
```

### Artefactos generados

| Ruta | Contenido |
|---|---|
| `models/noshow/<run_id>/noshow_model.joblib` | Bundle con los tres modelos (logística y boosting calibrados, baseline), el nombre del principal y las columnas de entrada. No se versiona en git. |
| `models/noshow/<run_id>/metadata.json` | Versión del modelo, versión de datos (run_id, dataset_sha256), configuración, límites del split, método de calibración y versiones de librerías. |
| `results/noshow.json` | Métricas completas, coeficientes, calibración, equidad, split, todas las decisiones. |

### Archivos de referencia

- `docs/decisions.md` § 9: decisiones de diseño del modelo.
- `docs/design/synthetic-noshow-review.md`: revisión técnica por ml-engineer, hallazgos A1–A3, M1–M4, B1–B4.
- `noshow/src/noshow/features.py`: política de variables, lista de excluidas con motivos.
- `docs/synthetic-data.md` § 4: cómo se generan las inasistencias sintéticas, parámetros, escenarios.

---

**Última actualización**: 2026-10-08. **Modelo**: noshow-1124d9b7-6ef9a83e. **Disclaimer**: Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.
