# Model card: modelo de inasistencias (`noshow`)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Advertencia: qué validan estas métricas

**Con datos sintéticos, estas métricas validan el pipeline (que el modelo aprende la estructura que el generador puso), no el desempeño en pacientes reales.** El modelo solo puede recuperar lo que el generador sintético introdujo. En particular:

- La fragilidad latente de cada paciente (u_i) no es observable. Con ~1,5 citas previas por paciente, el techo práctico de AUC con variables observables es ~0,63-0,65, frente a 0,74 del oráculo (hallazgo A3 de `docs/design/synthetic-noshow-review.md`).
- El historial sintético no tiene término de espera (vale 0 en el generador), así que el modelo no puede aprender el efecto de la espera que sí tendrán las citas futuras (hallazgo A2).
- El modelo no ve servicio de salud, comuna ni edad (excluidos por equidad), así que no distingue que Arica e Iquique tienen tasas base más altas (probabilidad verdadera media de 19,8 % en ambos en el conjunto de prueba, frente a 14,6 % del modelo principal en el total) ni el efecto de la edad que el generador sí usa. Las brechas resultantes están en la sección Equidad.

## Resumen

Estima la probabilidad de que un paciente no se presente a una cita (consulta nueva de especialidad o cirugía), a partir de su historial previo de asistencia, la anticipación del agendamiento, la especialidad, el tipo de atención y el día de la semana.

**Uso previsto:** insumo para el sobreagendamiento controlado en `scheduler/`. Las citas propuestas se puntúan con `build_candidate_features` + `predict_noshow`. El sistema apoya, no decide: todo plan generado requiere revisión humana.

**Fuera de alcance:**
- Excluir, sancionar o postergar pacientes por su probabilidad predicha.
- Inferir características clínicas o personales del paciente.
- Usarlo con datos reales sin reentrenar, recalibrar y auditar la equidad en la institución.

## Datos

| Parámetro | Valor |
|---|---|
| `run_id` | `d7a0c251-9a0f-5d0a-9941-5140560fb5b2` |
| Semilla | 42 |
| Tamaño (`size`) | 100.000 entradas en lista de espera (85.083 pacientes; 127.517 citas de historial) |
| Escenario | `baseline` (efecto de edad, sin efecto de previsión, efecto aleatorio por especialidad) |
| `as_of` | 2025-09-30 |
| `dataset_sha256` | `652dd76d8b71124a897674fb8b90efb84aba02031288ec1d556e31b363184103` |
| Generador | 0.3.0 (`params_sha256` `0bf4b473…`, `targets_sha256` `22f5a727…`) |

### Split temporal

| Bloque | Periodo | n | Tasa de inasistencia |
|---|---|---|---|
| Entrenamiento | 2023-10-01 a 2024-12-02 | 75.181 | 14,76 % |
| Calibración | 2024-12-03 a 2025-04-01 | 20.714 | 15,22 % |
| Prueba | 2025-04-02 a 2025-09-29 | 31.622 | 14,46 % |

Tres bloques disjuntos y consecutivos (sin mezcla aleatoria): prueba = últimos 180 días, calibración = 120 días previos, entrenamiento = el resto. Los hiperparámetros son fijos. El bloque de calibración ajusta el calibrador y elige el modelo principal; el de prueba no participa en ninguna elección.

## Variables usadas

| Variable | Tipo | Descripción |
|---|---|---|
| `specialty_code` | Categórica | Especialidad de la cita |
| `care_type` | Categórica | `consultation` (CNE) o `surgery` (IQ) |
| `weekday` | Categórica | Día de la semana en hora de Santiago (1 = lunes) |
| `lead_days` | Numérica | Días entre el agendamiento y la cita |
| `prior_attended` | Numérica | Citas previas del paciente a las que asistió, conocidas al agendar |
| `prior_no_show` | Numérica | Citas previas del paciente a las que no asistió, conocidas al agendar |

**Historial sin fuga:** los conteos previos solo usan citas con `scheduled_start` estrictamente anterior a la fecha de agendamiento (`scheduled_start - lead_days`). Un test verifica que cambiar el resultado de una cita ocurrida entre el agendamiento y la fecha de otra no cambia las variables de esta última.

**Descartada por constante:** `time_band` (mañana/tarde, hora local de Santiago). En el historial sintético todas las citas son a las 12:00 UTC.

### Riesgo de proxy en variables permitidas

La especialidad está en la lista permitida, pero actúa en parte como proxy de edad: las especialidades pediátricas delatan el grupo 0-14 años. V de Cramér en entrenamiento (sin corrección de sesgo):

| Variable | Grupo etario | Previsión | Servicio | Comuna |
|---|---|---|---|---|
| `specialty_code` | 0,317 | 0,046 | 0,055 | 0,090 |
| `care_type` | 0,063 | 0,010 | 0,119 | 0,147 |
| `weekday` | 0,011 | 0,009 | 0,020 | 0,068 |

Con datos reales, ginecología y obstetricia, urología y mama delatarían el sexo. Alternativa no adoptada (cambia la lista de variables permitidas): unificar las variantes pediátricas y adultas de cada especialidad.

## Variables excluidas

| Variable | Motivo |
|---|---|
| `sex`, `ethnicity`, `nationality` | Atributos protegidos (CLAUDE.md). No existen en los datos sintéticos. |
| `age_group` | No está en la lista permitida. Incluirla concentraría el sobreagendamiento en 15-44 años (hallazgo M3). Solo se usa para medir equidad. |
| `insurance` (previsión) | Proxy evidente de nivel socioeconómico. Solo para medir equidad. |
| `commune_code` | Proxy geográfico de nivel socioeconómico, etnia y nacionalidad. Solo para medir equidad. |
| `health_service_code` | Determinado por la comuna (V de Cramér = 1 en el sintético): mismo proxy geográfico. Costo: el modelo no ve las tasas más altas de Arica e Iquique. |
| `distance_km` | Permitida si existe, pero no hay coordenadas ni establecimiento en las citas del historial; calcularla exigiría la comuna del paciente. |
| `wait_days` | Permitida, pero las citas del historial no tienen entrada asociada y el generador fija el término de espera en 0 (A2). Entra automáticamente cuando tenga valores en entrenamiento. |
| `duration_min` | En consultas siempre vale 20 min y en cirugías delata el procedimiento (B2); redundante con la especialidad. |
| `clinical_priority` | No existe en el historial. Además, el sobreagendamiento no debe aprender de la prioridad clínica. |
| `noshow_frailty`, `true_noshow_prob` | Verdad sintética del generador: prohibida. Solo se lee `appointment_truth` para la referencia del oráculo. |

## Costo de las variables excluidas

**Diagnóstico de solo medición.** Ningún modelo de esta sección se guarda en `noshow_model.joblib`, ni lo usa el programador o la simulación, y las variables siguen prohibidas en producción. Su único fin es cuantificar cuánto desempeño se pierde por excluirlas (`results/noshow.json`, clave `diagnostic_excluded`, con `purpose` y `used_by_scheduler: false`).

**Método.** Cada variante agrega a las variables permitidas una o todas las excluidas por equidad (`age_group`, `insurance`, `commune_code`, `health_service_code`) y repite el pipeline del principal sin cambios: mismo split temporal, mismos candidatos e hiperparámetros, misma regla de calibración, misma selección por Brier en el bloque de calibración y misma semilla. Se informa el candidato que esa selección elige, evaluado en prueba. La diferencia de Brier contra el principal lleva un IC 95 % por bootstrap de pacientes (1.000 réplicas, negativa = la variante es mejor). Sexo, etnia y nacionalidad no existen en los datos y nunca entran, ni siquiera aquí; la verdad sintética (`noshow_frailty`, `true_noshow_prob`) solo se usa como referencia, igual que en el resto de la evaluación. Para el boosting, la comuna (338 niveles) supera el máximo de 255 categorías de `HistGradientBoostingClassifier`, así que en esas variantes se agrupan las comunas infrecuentes; la logística usa el mismo one-hot de producción (niveles con menos de 20 casos agrupados).

Corrida `d7a0c251` (seed 42, n 100.000, escenario `baseline`, `dataset_sha256` `652dd76d…`), conjunto de prueba (31.622 citas):

| Variante | Candidato elegido | AUC | Brier | ECE | Δ Brier vs principal [IC 95 %] | Brecha al oráculo cerrada |
|---|---|---|---|---|---|---|
| Principal (sin excluidas) | logística sin calibrar | 0,6248 | 0,120548 | 0,0064 | | |
| + grupo etario | logística sin calibrar | 0,6326 | 0,120185 | 0,0068 | **−0,000364** [−0,000535; −0,000198] | 3,8 % |
| + previsión | logística calibrada | 0,6244 | 0,120612 | 0,0070 | +0,000063 [−0,000053; +0,000183] | −0,7 % |
| + comuna | logística calibrada | 0,6200 | 0,120953 | 0,0109 | **+0,000405** [+0,000164; +0,000645] | −4,2 % |
| + servicio de salud | logística sin calibrar | 0,6257 | 0,120468 | 0,0077 | −0,000080 [−0,000206; +0,000041] | 0,8 % |
| + las cuatro | logística calibrada | 0,6262 | 0,120522 | 0,0064 | −0,000026 [−0,000302; +0,000268] | 0,3 % |
| Oráculo (verdad sintética) | | 0,7370 | 0,110977 | 0,0037 | | 100 % |

"Brecha al oráculo cerrada" = (Brier principal − Brier variante) / (Brier principal − Brier oráculo).

**Lectura, tal cual:**

- **El costo en desempeño global es pequeño.** La mejor variante (grupo etario) mejora el Brier en 0,00036 (0,3 % del Brier del principal) y el AUC en 0,008 (0,625 → 0,633). La mejora es estadísticamente significativa, pero cierra solo el 3,8 % de la distancia al oráculo. La brecha con el oráculo sigue siendo, casi entera, la fragilidad latente no observable (A3), no las variables excluidas.
- **La previsión no aporta nada.** En el escenario `baseline` el generador no la usa, así que este resultado es una propiedad del sintético, no evidencia de que la previsión no prediga en datos reales.
- **La comuna empeora el modelo** (Brier +0,0004, IC que excluye el 0; AUC −0,005). En el sintético no tiene efecto propio, solo vía servicio, y sus 338 niveles agregan ruido que los hiperparámetros fijos no regularizan. El servicio, que lleva la misma señal geográfica con 29 niveles, mejora poco y sin significancia: solo dos servicios (Arica e Iquique) tienen tasas distintas y aportan pocas citas.
- **Las cuatro juntas mejoran menos que la edad sola.** El ruido de comuna y previsión anula la ganancia de la edad, y la selección elige la logística calibrada, cuya media predicha (0,151) absorbe la tasa más alta del bloque de calibración (ver "Modelos, calibración y selección"). Incluso la logística sin calibrar de esa variante (Brier 0,120561, en `test_metrics_by_candidate`) queda detrás de la variante con solo edad. Con otra regularización o codificación de la comuna la variante conjunta podría rendir más; no se exploró, porque ajustar hiperparámetros para un modelo que no se va a usar gastaría el bloque de prueba sin beneficio.
- **Donde sí hay costo es en la calibración por grupo.** Brecha máxima (predicha − verdad) por dimensión, grupos con n ≥ 200:

| Dimensión | Principal | + grupo etario | + servicio | + las cuatro |
|---|---|---|---|---|
| Grupo etario | 3,21 pp | 0,80 pp | 3,19 pp | 1,00 pp |
| Servicio de salud | 4,94 pp | 5,03 pp | 2,55 pp | 2,27 pp |
| Comuna | 5,11 pp | 5,23 pp | 3,05 pp | 2,66 pp |
| Previsión | 0,23 pp | 0,22 pp | 0,22 pp | 0,87 pp |

  Con la edad, la subestimación de 15-44 años (−3,1 a −3,2 pp) y la sobreestimación de 65+ (+2,3 pp) casi desaparecen (−0,5 y −0,05 pp). Con el servicio, la brecha máxima por servicio (Arica en el principal) baja de 4,9 a 2,5 pp. Es decir, en este sintético las variables excluidas mejorarían la calibración por grupo bastante más que las métricas globales. Agregar las cuatro **empeora** la calibración por previsión (0,23 → 0,87 pp): el modelo aprende diferencias de previsión que el generador no tiene.

**Por qué igual no se usan.** La decisión es normativa y no depende de que la mejora sea pequeña:

1. **Trato según pertenencia a un grupo.** Con edad o territorio como variables, el sobreagendamiento recaería sobre una persona por ser joven o vivir en Arica, no por su propio historial de asistencia. Concentraría las colisiones en esos grupos (hallazgo M3) y, en datos reales, haría circular la desventaja: más sobrecupo, peor experiencia y más inasistencia en el mismo grupo.
2. **Proxies.** Previsión, comuna y servicio son proxies de nivel socioeconómico, etnia y nacionalidad (CLAUDE.md). Que en el sintético la previsión no prediga nada no lo asegura en datos reales, donde sí podría hacerlo y por esa razón.
3. **El costo es acotado y conocido.** La pérdida global es de 0,3 % del Brier. La de calibración por grupo ya se publica en la sección Equidad y la simulación mide su efecto en el sobreagendamiento. Si una institución quisiera corregir esas brechas, el camino compatible con estas reglas es auditar y ajustar la política de sobrecupo por grupo (por ejemplo, con topes de exposición), no darle esas variables al modelo.

Cómo se protege: `noshow.diagnostic` devuelve solo números (sin estimadores) y no importa `joblib`; `save` rechaza cualquier bundle con modelos o columnas ajenos a producción (`assert_production_bundle`); los tests de `noshow/tests/test_noshow_diagnostic.py` fallan si cambian `MODEL_FEATURES` o `FORBIDDEN_FEATURES`, si un modelo de diagnóstico llega al bundle, si el diagnóstico deja de ser determinista o si el programador o la simulación importan el módulo (directa o transitivamente). El diagnóstico corre por defecto en `prioriza-noshow train` (~20 s extra con n = 100.000; `--no-diagnostic` lo apaga) y no cambia `test_metrics`, `metadata.json` ni las predicciones del bundle.

## Modelos, calibración y selección

- **Baseline:** tasa histórica por especialidad en entrenamiento, contraída hacia la tasa global (m = 20); especialidades no vistas reciben la tasa global.
- **Regresión logística:** one-hot de categóricas; imputación por mediana, `log1p` y estandarización de numéricas; L2 con C = 1.
- **Gradient boosting:** `HistGradientBoostingClassifier` con categóricas nativas, 300 iteraciones, sin early stopping (usaría una validación aleatoria).

**Calibración:** isotónica si la clase minoritaria del bloque de calibración tiene 1.000 casos o más; sigmoide si no. Aquí hubo 3.152 inasistencias, así que se usó isotónica.

**Selección del principal:** menor Brier en el bloque de calibración entre cuatro candidatos. Los modelos sin calibrar no vieron ese bloque al entrenar, así que su Brier ahí es honesto; los calibrados se miden con predicciones fuera de pliegue (5 bloques contiguos).

| Candidato | Brier en calibración |
|---|---|
| Regresión logística, sin calibrar | **0,125951** |
| Regresión logística, calibrada | 0,125987 |
| Gradient boosting, calibrado | 0,126559 |
| Gradient boosting, sin calibrar | 0,126732 |

**Principal: regresión logística sin calibrar.** La calibración isotónica no mejoró a la logística, que ya venía bien calibrada. En prueba también la empeoró levemente (Brier 0,120548 → 0,120621; ECE 0,0064 → 0,0072): la isotónica absorbe la tasa del bloque de calibración (15,22 %), mayor que la de prueba (14,46 %), y sube la media predicha de 0,1459 a 0,1517. Como el proceso sintético es estacionario, esa diferencia es variación muestral, no deriva. Al boosting sí lo mejoró (ECE 0,0176 → 0,0092). Con datos reales, que sí tienen deriva, la selección puede preferir el modelo calibrado con el periodo más reciente; la regla es la misma.

## Métricas en prueba

| Modelo | AUC | Brier | Log loss | ECE | Media predicha | Observada |
|---|---|---|---|---|---|---|
| Baseline (especialidad) | 0,6022 | 0,12151 | 0,4035 | 0,0087 | 0,1474 | 0,1446 |
| Gradient boosting, sin calibrar | 0,6105 | 0,12180 | 0,4052 | 0,0176 | 0,1443 | 0,1446 |
| Gradient boosting, calibrado | 0,6095 | 0,12149 | 0,4037 | 0,0092 | 0,1507 | 0,1446 |
| **Regresión logística, sin calibrar (principal)** | **0,6248** | **0,12055** | **0,4001** | **0,0064** | 0,1459 | 0,1446 |
| Regresión logística, calibrada | 0,6239 | 0,12062 | 0,4003 | 0,0072 | 0,1517 | 0,1446 |
| Oráculo (verdad sintética) | 0,7370 | 0,11098 | 0,3660 | 0,0037 | 0,1459 | 0,1446 |

ECE con 10 bins de igual frecuencia; la curva de calibración completa de cada modelo está en `results/noshow.json` (`test_metrics.*.calibration_curve`).

### Principal frente al baseline

| | Valor |
|---|---|
| Δ Brier (principal − baseline) | −0,000958 |
| IC 95 % | [−0,001254; −0,000652] |
| Remuestreo | Bootstrap de pacientes, 1.000 réplicas |

**El modelo principal supera al baseline en Brier** y el IC 95 % no incluye 0. La mejora es pequeña (~0,8 % del Brier del baseline), coherente con el techo descrito arriba. Se remuestrean pacientes porque sus citas comparten la fragilidad latente.

### Brecha con el oráculo

AUC 0,6248 frente a 0,7370 (−0,112) y Brier 0,12055 frente a 0,11098. Casi toda la brecha es la fragilidad latente no observable; el resto, los efectos de servicio y edad que el modelo no ve por diseño.

## Equidad

Probabilidad media predicha por el modelo principal frente a la tasa observada y a la probabilidad verdadera media, en prueba. Ninguna de estas variables entra al modelo. Solo grupos con n ≥ 200.

### Grupo etario

| Grupo | Predicha | Verdadera | Observada | Brecha (pred − verdad) | n |
|---|---|---|---|---|---|
| 0-14 | 0,1761 | 0,1743 | 0,1784 | +0,0018 | 3.391 |
| 15-19 | 0,1541 | 0,1861 | 0,1672 | −0,0321 | 1.364 |
| 20-44 | 0,1442 | 0,1755 | 0,1707 | −0,0313 | 7.281 |
| 45-64 | 0,1414 | 0,1367 | 0,1373 | +0,0046 | 9.965 |
| 65+ | 0,1399 | 0,1173 | 0,1172 | +0,0227 | 9.621 |

El modelo sobreestima la inasistencia de 65+ en 2,3 pp y subestima la de 15-44 en ~3,2 pp. Consecuencia esperada en el programador: más sobreagendamiento sobre cupos de personas mayores, que sí asisten (más colisiones para ellas), y menos sobre jóvenes. Es el costo de excluir la edad; 0-14 queda bien porque la especialidad pediátrica actúa como proxy (ver Riesgo de proxy).

### Tipo de atención

| Tipo | Predicha | Verdadera | Observada | Brecha | n |
|---|---|---|---|---|---|
| Consulta | 0,1630 | 0,1621 | 0,1602 | +0,0009 | 26.900 |
| Cirugía | 0,0481 | 0,0535 | 0,0557 | −0,0054 | 4.722 |

### Previsión

| Previsión | Predicha | Verdadera | Brecha | n |
|---|---|---|---|---|
| FONASA A | 0,1455 | 0,1432 | +0,0023 | 5.867 |
| FONASA B | 0,1460 | 0,1462 | −0,0002 | 12.378 |
| FONASA C | 0,1465 | 0,1472 | −0,0007 | 4.702 |
| FONASA D | 0,1454 | 0,1470 | −0,0016 | 6.811 |
| Otra | 0,1458 | 0,1449 | +0,0009 | 1.864 |

Brechas menores a 0,25 pp. En el escenario `baseline` el generador no usa la previsión, así que este análisis no puede detectar daño por previsión; para eso está el escenario `ses_gradient`.

### Servicio de salud

29 servicios con n ≥ 200. Los de mayor brecha:

| Servicio | Predicha | Verdadera | Observada | Brecha | n |
|---|---|---|---|---|---|
| 1 (Arica) | 0,1482 | 0,1976 | 0,2037 | −0,0494 | 427 |
| 2 (Iquique) | 0,1550 | 0,1979 | 0,2080 | −0,0429 | 678 |

El modelo subestima Arica en 4,9 pp e Iquique en 4,3 pp porque no ve el servicio. En esos servicios se sobreagendaría menos de lo que la inasistencia real justifica, con más cupos perdidos.

### Comuna

44 de 338 comunas llegan a n ≥ 200. Brecha máxima: −0,0511 (comuna 15101, servicio de Arica; predicha 0,1500, verdadera 0,2011, n = 374). El generador no tiene efecto propio de comuna (solo vía servicio), así que las brechas por comuna reproducen las del servicio y este análisis no puede detectar daño por comuna aunque exista en la realidad. Un análisis con poder suficiente necesita estimadores agrupados o con contracción (M3).

## Limitaciones

1. **Techo de AUC (A3).** La señal individual está en u_i y el historial (k ~ Poisson(1,5) en 730 días) aporta poco. No se cambió λ en esta fase.
2. **Espera no aprendible (A2).** Según la revisión del generador (N = 20.000, no esta corrida), un modelo entrenado en el historial y aplicado a citas futuras sobreestima ~2,7 pp en el quintil de menor espera y subestima ~2,6 pp en el de mayor espera. El sobreagendamiento recaería sobre quienes esperan poco. No hay mitigación implementada.
3. **Proceso estacionario (M4).** Sin deriva ni estacionalidad, el split temporal equivale estadísticamente a uno aleatorio y no prueba robustez ante cambios en el tiempo.
4. **Franja horaria constante** en el historial: el modelo no aprende efectos de la hora.
5. **Proxies:** la especialidad delata la edad en pediatría (V = 0,32) y delataría el sexo con datos reales; servicio y comuna delatarían etnia y nacionalidad.
6. **Persistencia con joblib (pickle):** solo cargar artefactos propios.

## Reproducción

```bash
make synth            # carga a PostgreSQL; sin base de datos:
# uv run --package synthetic prioriza-synth generate --size 100000 --seed 42 --no-load
make train-noshow     # = uv run --package noshow prioriza-noshow train --seed 42 --size 100000 --scenario baseline
```

`prioriza-noshow train` usa la única corrida de `data/synthetic/` con esa semilla, tamaño y escenario generada con los supuestos vigentes del generador (`targets_sha256` y `params_sha256`); si hay varias, falla y pide `--run-dir`.

| Ruta | Contenido |
|---|---|
| `models/noshow/<run_id>/noshow_model.joblib` | Bundle con los candidatos (logística y boosting, con y sin calibrar) y el baseline, el nombre del principal y las columnas de entrada. No se versiona en git. |
| `models/noshow/<run_id>/metadata.json` | Versión del modelo (huella de configuración, columnas e hiperparámetros + `dataset_sha256`), versión de datos, límites del split, método de calibración y versiones de librerías. |
| `results/noshow.json` | Métricas, curvas de calibración, selección, equidad, fuerza de proxies, coeficientes de la logística, política de variables y el diagnóstico de solo medición de las variables excluidas (`diagnostic_excluded`). |

Referencias: `docs/decisions.md` §9, `docs/design/synthetic-noshow-review.md`, `noshow/src/noshow/features.py`, `docs/synthetic-data.md` §4.

Modelo `noshow-4f0429cd-652dd76d` (corrida canónica `d7a0c251`, generador 0.3.0).
