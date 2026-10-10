# Informe de resultados de Prioriza

> **Aviso.** Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Qué es este informe

Este informe compara cuatro políticas de atención para la corrida sintética `d7a0c251-9a0f-5d0a-9941-5140560fb5b2`: orden de llegada (línea de base), solo prioridad clínica, programación optimizada respetando la capacidad y los plazos, y programación optimizada con sobrecupo controlado. El sistema apoya la decisión pero no la toma: cada plan se genera bajo demanda y permanece pendiente de revisión humana antes de cualquier uso. Todas las cifras provienen de `results/` sin escritura manual.

Las corridas que alimentan el informe no tienen el mismo tamaño:

| Resultado | Entradas de la corrida | Corrida |
|---|---:|---|
| synthetic_calibration_baseline_seed42_n100000.json | 100.000 | d7a0c251 |
| noshow.json | 100.000 | d7a0c251 |
| schedule_d7a0c251-9a0f-5d0a-9941-5140560fb5b2_4w.json | 100.000 | d7a0c251 |
| scheduler-benchmark.json | 1.000, 10.000, 50.000 | 154f55dd, 1bc88d6d, 233e7843, 794aa29f, 90e4ab50, cd4d5218 |
| simulation.json | 10.000 | d25b3696 |

**Atención.** La simulación corrió con una población de 10.000 entradas y el plan canónico usa 100.000. Las cifras absolutas de la simulación no son comparables con las del plan canónico; solo se comparan entre las políticas de la misma simulación.

## Contexto y fuentes

Al momento de corte de la Glosa 06 (30-09-2025), el sistema público de Chile registraba las entradas en espera, las garantías GES retrasadas y las medianas de espera que muestra la tabla de esta sección. La población de esta corrida es sintética: generada de forma controlada con semilla fija y calibrada a partir de datos públicos agregados para reproducir el tamaño, composición y tiempos de espera observados. Los chequeos de calibración muestran si el simulador replica fielmente estos agregados; cuando alguno falla (especialmente si es informativo y no estricto), indica una limitación en la reproducción que debe interpretarse al examinar los resultados. Fuentes de calibración: `glosa06_2025q3` (30-09-2025), `glosa06_2025q4` (31-12-2025), `glosa06_2026q1` (31-03-2026), `sis_ges_cases_2026q1` (31-03-2026), `minsal_establishments`.
| Lista | Registros | Personas | Espera media (días) | Mediana de espera (días) |
|---|---:|---:|---:|---:|
| Consulta nueva de especialidad | 2.576.371 | 2.134.364 | 341 | 242 |
| Intervención quirúrgica | 417.561 | 365.781 | 394 | 264 |
| Garantías GES retrasadas | 80.022 | sin dato | 136 | 71 |

### Calibración de la población sintética

La población de la corrida `d7a0c251-9a0f-5d0a-9941-5140560fb5b2` (100.000 entradas, semilla 42, escenario `baseline`) se contrastó con los objetivos públicos. Chequeos estrictos que pasan: 26; estrictos que fallan: 0; informativos que fallan: 1; omitidos: 0. Resultado global: pasa.

| Grupo | Chequeos | Pasan | Estrictos que fallan | Informativos que fallan |
|---|---:|---:|---:|---:|
| C1 | 11 | 11 | 0 | 0 |
| C2 | 2 | 2 | 0 | 0 |
| C3 | 4 | 4 | 0 | 0 |
| C4 | 1 | 1 | 0 | 0 |
| C5 | 4 | 3 | 0 | 1 |
| C6 | 6 | 6 | 0 | 0 |
| C7 | 1 | 1 | 0 | 0 |
| C8 | 1 | 1 | 0 | 0 |
| C9 | 3 | 3 | 0 | 0 |

Chequeos que no pasan (se muestran tal cual):

| Chequeo | Severidad | Métrica | Observado | Objetivo | Tolerancia | Detalle |
|---|---|---|---:|---:|---:|---|
| C5.nacional.mediana(total) | soft | mediana de retraso | 76 | 71 | 3,55 | el nacional incluye problemas no mapeados; se informa sin fallar |

Detalle de todos los chequeos:

| Chequeo | Severidad | Métrica | Observado | Objetivo | Tolerancia | Pasa |
|---|---|---|---:|---:|---:|---|
| C1.tipo | strict | tvd | 0,00000625 | 0 | 0,0000150 | sí |
| C1.servicio\|cne | strict | tvd | 0,0000357 | 0 | 0,000180 | sí |
| C1.servicio\|iq | strict | tvd | 0,000242 | 0 | 0,00111 | sí |
| C1.especialidad\|cne_medical | strict | tvd | 0,000148 | 0 | 0,00103 | sí |
| C1.especialidad\|cne_dental | strict | tvd | 0,0000760 | 0 | 0,000854 | sí |
| C1.especialidad\|iq | strict | tvd | 0,000103 | 0 | 0,000460 | sí |
| C1.problema\|ges | strict | tvd | 0,000446 | 0 | 0,00305 | sí |
| C1.servicio\|ges | strict | tvd | 0,000553 | 0 | 0,00221 | sí |
| C1.comuna\|servicio | strict | tvd | 0,00168 | 0 | 0,00504 | sí |
| C1.edad\|clase | strict | tvd | 0,00000816 | 0 | 0,0000265 | sí |
| C1.previsión | strict | tvd | 0,00000621 | 0 | 0,0000294 | sí |
| C2.mediana | strict | max\|obs-obj\| días | 0 | 0 | sin dato | sí |
| C2.media | strict | max error relativo | 0,000148 | 0 | 0,0300 | sí |
| C3.cne.mediana | strict | mediana | 247 | 242 | 12,1 | sí |
| C3.cne.media | strict | media | 340 | 341 | 17,1 | sí |
| C3.iq.mediana | strict | mediana | 271 | 264 | 13,2 | sí |
| C3.iq.media | strict | media | 394 | 394 | 19,7 | sí |
| C4.registros/personas | strict | max\|razón-obj\| | 0,00487 | 0 | sin dato | sí |
| C5.problemas | strict | grupos con n>=30 | 13 | sin dato | sin dato | sí |
| C5.nacional.media(mapeados) | strict | media de retraso | 133 | 133 | 6,65 | sí |
| C5.nacional.media(total) | soft | media de retraso | 133 | 136 | 6,80 | sí |
| C5.nacional.mediana(total) | soft | mediana de retraso | 76 | 71 | 3,55 | no |
| C6.media_p | strict | max\|media p - tasa\| (verifica la bisección, no la independencia) | 0 | 0 | 0,000100 | sí |
| C6.media_p.independiente | strict | max\|media p (u independiente) - tasa\| | 0,00884 | 0 | sin dato | sí |
| C6.historial.global | strict | tasa realizada vs E[p historial] | 0,148 | 0,147 | 0,00797 | sí |
| C6.historial.servicios | strict | tasa realizada vs E[p historial] | 29 | sin dato | sin dato | sí |
| C6.historial.vs_tasa_objetivo.cne | soft | tasa realizada vs tasa objetivo del tipo | 0,164 | 0,157 | 0,0100 | sí |
| C6.historial.vs_tasa_objetivo.iq | soft | tasa realizada vs tasa objetivo del tipo | 0,0532 | 0,0500 | 0,0100 | sí |
| C7.iq_mayor | strict | participación | 0,723 | 0,723 | 0,0300 | sí |
| C8.minutos_programados | strict | max\|min/sem - objetivo\| | 7,38 | 0 | sin dato | sí |
| C9.E[p2]_cne | soft | E[p²] CNE | 0,0383 | 0,0304 | 0,0150 | sí |
| C9.cobertura_ges | soft | cobertura sobre retrasadas | 0,682 | 1 | sin dato | sí |
| C9.cramer_v_servicio_x_especialidad | soft | V de Cramér | 0,0307 | sin dato | sin dato | sí |

- Celdas (servicio, especialidad) con entradas pero sin sesiones: 319 de 2216
- Minutos por semana de celdas sin oferta posible (menos de media sesión de la menor duración en el periodo de referencia): 182 de 121393 (0.1%); no entran en la meta de C8

## Priorización

Reglas `prioriza-default`, versión 2026.10-1. El puntaje de cada paciente combina tres componentes: prioridad clínica declarada (entrada definida por profesionales, nunca inferida del sistema), días de espera acumulados y cercanía a los plazos de garantía GES. La prioridad clínica es un dato exógeno y auditable; el sistema respeta lo que declare el gestor. La regla GES estricta adelanta las garantías vencidas o que vencen pronto por sobre el resto de la cola, salvo las entradas de máxima prioridad, que van antes (cesión a máxima prioridad). La tabla siguiente muestra cómo cada política afecta el cumplimiento de estas obligaciones y la atención de máxima prioridad.

| Componente | Campo | Peso | Participación | Parámetros |
|---|---|---:|---:|---|
| Prioridad clínica declarada | `clinical_priority` | 50 | 50 % | p1: 1, p2: 0,6, p3: 0,25, p4: 0 |
| Días de espera | `wait_days` | 35 | 35 % | type: linear_saturated, saturation_days: 730 |
| Cercanía al plazo GES | `days_to_ges_deadline` | 15 | 15 % | type: ramp_down, start_days: 60, end_days: 0 |

Regla GES estricta: activa: sí; vencidas o por vencer en 14 días o menos van antes que el resto, ordenadas por `deadline`; ceden el paso las prioridades p1.

Las reglas versionadas coinciden con las que usó el plan canónico (versión 2026.10-1).

Efecto en el plan canónico (06-10-2025 a 03-11-2025, exclusivo):

| Política | Agendadas | Máxima prioridad agendadas | GES con obligación | GES cumplidas | GES agendadas antes del plazo | GES sin cumplir |
|---|---:|---:|---:|---:|---:|---:|
| Orden de llegada | 13.312 | 871 | 3.866 | 337 | 14 | 3.529 |
| Solo prioridad | 13.304 | 4.760 | 3.866 | 1.110 | 107 | 2.756 |
| Optimizada | 13.750 | 4.778 | 3.866 | 1.645 | 650 | 2.221 |

## Modelo de inasistencias

Modelo principal: `logistic_regression_uncalibrated` (versión `noshow-4f0429cd-652dd76d`), sin calibrar. Predice la probabilidad de que un paciente no se presente a su cita (inasistencia), usando solo las variables permitidas: `specialty_code`, `care_type`, `weekday`, `lead_days`, `prior_attended`, `prior_no_show`. Edad, previsión, comuna y servicio de salud no entran al modelo (se usan solo para medir equidad; motivos en la tabla de variables excluidas). Criterio de selección del modelo principal: Menor Brier en el conjunto de calibración entre los modelos sin calibrar (que no lo vieron al entrenar) y calibrados (predicciones fuera de pliegue, KFold contiguo). El conjunto de prueba no participa. Con datos sintéticos se valida la canalización (ingesta, features, entrenamiento, calibración, persistencia) pero no el desempeño en la población real. AUC mide la capacidad de separar asistencias de inasistencias; Brier es el error cuadrático medio; la calibración compara la probabilidad predicha contra la tasa observada. El intervalo de confianza del Δ Brier contra el baseline (1.000 remuestreos por paciente) excluye el cero: sí. Las brechas por grupo contra la verdad sintética muestran si el modelo da estimaciones sesgadas en grupos específicos; la brecha es predicha menos verdad: una diferencia negativa indica subestimación de la inasistencia y una positiva, sobrestimación.

Con datos sintéticos, estas métricas validan el pipeline (que aprende la estructura que el generador puso), no el desempeño en pacientes reales.

Partición temporal (sin barajar):

| Parte | Citas | Desde | Hasta | Tasa de inasistencia |
|---|---:|---|---|---:|
| Entrenamiento | 75.181 | 01-10-2023 | 02-12-2024 | 14,8 % |
| Calibración | 20.714 | 03-12-2024 | 01-04-2025 | 15,2 % |
| Prueba | 31.622 | 02-04-2025 | 29-09-2025 | 14,5 % |

Métricas en el conjunto de prueba:

| Modelo | AUC | Brier | ECE | Pérdida logarítmica | Probabilidad media predicha | Tasa observada |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_specialty_rate` | 0,602 | 0,1215 | 0,0087 | 0,4035 | 14,7 % | 14,5 % |
| `gradient_boosting` | 0,609 | 0,1215 | 0,0092 | 0,4037 | 15,1 % | 14,5 % |
| `gradient_boosting_uncalibrated` | 0,611 | 0,1218 | 0,0176 | 0,4052 | 14,4 % | 14,5 % |
| `logistic_regression` | 0,624 | 0,1206 | 0,0072 | 0,4003 | 15,2 % | 14,5 % |
| `logistic_regression_uncalibrated` (principal) | 0,625 | 0,1205 | 0,0064 | 0,4001 | 14,6 % | 14,5 % |
| Referencia con la probabilidad verdadera del generador | 0,737 | 0,1110 | 0,0037 | 0,3660 | sin dato | sin dato |

Diferencia de Brier del modelo principal contra el baseline por especialidad: -0,0010 (IC 95 % -0,0013 a -0,0007; 1.000 remuestreos por paciente). Mejora al baseline: sí; el IC 95 % excluye el cero: sí.

Calibración del modelo principal en prueba (por decil de probabilidad predicha):

| Probabilidad media predicha | Tasa observada | Citas |
|---:|---:|---:|
| 4,2 % | 4,6 % | 3.163 |
| 7,5 % | 9,0 % | 3.161 |
| 11,2 % | 12,0 % | 3.163 |
| 12,7 % | 12,2 % | 3.162 |
| 13,9 % | 13,7 % | 3.160 |
| 15,0 % | 14,9 % | 3.163 |
| 16,3 % | 15,1 % | 3.163 |
| 17,9 % | 17,8 % | 3.162 |
| 20,7 % | 20,1 % | 3.162 |
| 26,6 % | 25,4 % | 3.163 |

Brier por modelo en el conjunto de calibración (criterio de selección):

| Modelo | Brier |
|---|---:|
| `gradient_boosting` | 0,1266 |
| `gradient_boosting_uncalibrated` | 0,1267 |
| `logistic_regression` | 0,1260 |
| `logistic_regression_uncalibrated` | 0,1260 |

### Equidad del modelo

Probabilidad media predicha por el modelo principal frente a la tasa observada y a la probabilidad verdadera media, por grupo, en el conjunto de prueba. Las variables de grupo no entran al modelo. Se reportan grupos con al menos 200 citas de prueba. La brecha es la probabilidad media predicha menos la probabilidad verdadera media del generador.

**age_group**: 5 grupos evaluados de 5; mayor brecha absoluta contra la verdad (predicha menos verdad, con su signo): -3,21 pp, en el grupo 15-19.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| 0-14 | 3.391 | 17,8 % | 17,6 % | 17,4 % | +0,18 pp |
| 15-19 | 1.364 | 16,7 % | 15,4 % | 18,6 % | -3,21 pp |
| 20-44 | 7.281 | 17,1 % | 14,4 % | 17,6 % | -3,13 pp |
| 45-64 | 9.965 | 13,7 % | 14,1 % | 13,7 % | +0,46 pp |
| 65+ | 9.621 | 11,7 % | 14,0 % | 11,7 % | +2,27 pp |

**care_type**: 2 grupos evaluados de 2; mayor brecha absoluta contra la verdad (predicha menos verdad, con su signo): -0,54 pp, en el grupo surgery.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| consultation | 26.900 | 16,0 % | 16,3 % | 16,2 % | +0,09 pp |
| surgery | 4.722 | 5,6 % | 4,8 % | 5,3 % | -0,54 pp |

**insurance**: 5 grupos evaluados de 5; mayor brecha absoluta contra la verdad (predicha menos verdad, con su signo): +0,23 pp, en el grupo fonasa a.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| fonasa a | 5.867 | 14,0 % | 14,6 % | 14,3 % | +0,23 pp |
| fonasa b | 12.378 | 14,5 % | 14,6 % | 14,6 % | -0,02 pp |
| fonasa c | 4.702 | 14,6 % | 14,7 % | 14,7 % | -0,07 pp |
| fonasa d | 6.811 | 14,6 % | 14,5 % | 14,7 % | -0,16 pp |
| other | 1.864 | 14,8 % | 14,6 % | 14,5 % | +0,09 pp |

**health_service_code**: 29 grupos evaluados de 29; mayor brecha absoluta contra la verdad (predicha menos verdad, con su signo): -4,94 pp, en el grupo 1.

Se listan los 10 grupos con mayor brecha absoluta.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| 1 | 427 | 20,4 % | 14,8 % | 19,8 % | -4,94 pp |
| 2 | 678 | 20,8 % | 15,5 % | 19,8 % | -4,29 pp |
| 25 | 216 | 18,1 % | 14,4 % | 13,3 % | +1,10 pp |
| 4 | 431 | 16,5 % | 14,7 % | 13,8 % | +0,91 pp |
| 28 | 365 | 14,5 % | 15,0 % | 14,2 % | +0,84 pp |
| 6 | 911 | 12,7 % | 14,1 % | 14,7 % | -0,58 pp |
| 17 | 1.066 | 11,6 % | 14,5 % | 14,0 % | +0,54 pp |
| 5 | 1.806 | 13,1 % | 14,7 % | 14,1 % | +0,53 pp |
| 26 | 406 | 14,0 % | 14,5 % | 15,0 % | -0,46 pp |
| 10 | 1.876 | 14,2 % | 15,2 % | 14,8 % | +0,43 pp |

**commune_code**: 44 grupos evaluados de 338; mayor brecha absoluta contra la verdad (predicha menos verdad, con su signo): -5,11 pp, en el grupo 15101. En el sintético la comuna no tiene efecto propio (solo vía servicio), así que este análisis no puede detectar daño por comuna aunque exista en la realidad.

Se listan los 10 grupos con mayor brecha absoluta.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| 15101 | 374 | 21,7 % | 15,0 % | 20,1 % | -5,11 pp |
| 13107 | 259 | 12,0 % | 14,9 % | 17,1 % | -2,24 pp |
| 05801 | 201 | 18,9 % | 14,7 % | 16,1 % | -1,41 pp |
| 04303 | 206 | 15,5 % | 14,4 % | 13,1 % | +1,26 pp |
| 08110 | 203 | 13,8 % | 14,8 % | 13,6 % | +1,24 pp |
| 14101 | 279 | 12,5 % | 14,8 % | 13,7 % | +1,12 pp |
| 16101 | 266 | 8,6 % | 14,2 % | 13,1 % | +1,05 pp |
| 04301 | 304 | 15,5 % | 14,2 % | 15,2 % | -1,03 pp |
| 08108 | 214 | 13,1 % | 14,0 % | 13,1 % | +0,93 pp |
| 13111 | 243 | 11,5 % | 14,9 % | 14,0 % | +0,91 pp |

### Variables

Variables usadas. Categóricas: specialty_code, care_type, weekday. Numéricas: lead_days, prior_attended, prior_no_show. Eliminadas por ser constantes en el entrenamiento: time_band.

Variables excluidas del modelo y motivo:

| Variable | Motivo |
|---|---|
| `age_group` | No está en la lista de variables permitidas. Aunque el generador la usa, incluirla concentraría el sobreagendamiento en 15-44 años (hallazgo M3 de la revisión del generador). Se usa solo para medir equidad. |
| `clinical_priority` | No existe en el historial (sin entrada asociada). Además, el sistema no debe aprender de la prioridad clínica para decidir sobreagendamiento. |
| `commune_code` | Proxy geográfico de nivel socioeconómico, etnia y nacionalidad. Se usa solo para medir equidad. |
| `distance_km` | Permitida si existe, pero no hay coordenadas ni establecimiento en las citas del historial; usarla exigiría la comuna del paciente, que es un proxy excluido. |
| `duration_min` | En consultas vale siempre 20 min y en cirugías delata el procedimiento (hallazgo B2); redundante con la especialidad y con un sesgo asimétrico entre tipos de atención. |
| `ethnicity` | Atributo protegido (CLAUDE.md). No existe en los datos sintéticos. |
| `health_service_code` | Determinado por la comuna (V de Cramér = 1 en el sintético): mismo proxy geográfico. Costo: el modelo no ve que Arica e Iquique tienen tasas más altas. |
| `insurance` | Previsión: proxy evidente de nivel socioeconómico. Se usa solo para medir equidad. |
| `nationality` | Atributo protegido (CLAUDE.md). No existe en los datos sintéticos. |
| `noshow_frailty` | Verdad sintética del generador: prohibida como variable. |
| `sex` | Atributo protegido (CLAUDE.md). No existe en los datos sintéticos. |
| `true_noshow_prob` | Verdad sintética del generador: prohibida como variable. |
| `wait_days` | Permitida, pero las citas del historial no tienen entrada asociada (entry_id nulo) y el generador fija el término de espera en 0 (hallazgo A2). Se incluye automáticamente solo si tiene valores en el periodo de entrenamiento. |

Riesgo de proxies entre las variables usadas:

| Variable | Riesgo |
|---|---|
| `specialty_code` | Las especialidades pediátricas delatan el grupo 0-14 años (y así reintroducen parte del efecto de edad excluido); en datos reales ginecología y obstetricia, urología y mama delatarían el sexo. Alternativa no adoptada: unificar variantes pediátricas y adultas. |

### Costo de las variables excluidas

Esta subsección es solo una medición: cuánto desempeño se pierde por no usar las variables excluidas por equidad. Ningún modelo del diagnóstico se guarda ni lo usan el programador o la simulación (`used_by_scheduler`: no; modelos persistidos: no). Las variables siguen excluidas del modelo de producción porque son proxies de condiciones socioeconómicas o territoriales y porque el modelo no debe tratar distinto a los grupos por ellas; que una variante mejore no cambia esa decisión. Solo medición: costo en desempeño de no usar variables excluidas por equidad. Ningún modelo de diagnóstico se persiste ni lo usa el programador o la simulación; las variables siguen prohibidas en el modelo de producción.

Cada variante agrega variables al principal y repite el mismo pipeline (mismo split temporal, candidatos, calibración y semilla). Δ Brier = Brier de la variante menos el del principal, con IC 95 % por bootstrap (1.000 remuestreos por paciente); negativo significa que la variante es mejor. La última columna es la proporción de la distancia de Brier entre el principal y el oráculo que la variante cierra. Nunca entran: `entry_id`, `ethnicity`, `gender`, `id`, `nationality`, `noshow_frailty`, `patient_id`, `run_id`, `sex`, `true_noshow_prob`.
| Variante | Candidato elegido | AUC | Brier | ECE | Δ Brier vs principal | Significativo (IC 95 % excluye el cero) | Lectura | Brecha al oráculo cerrada |
|---|---|---:|---:|---:|---|---|---|---:|
| Principal (sin excluidas) | logística sin calibrar | 0,6248 | 0,120548 | 0,0064 | referencia | no aplica | referencia | no aplica |
| + grupo etario | logística sin calibrar | 0,6326 | 0,120185 | 0,0068 | -0,000364 (IC 95 % -0,000535 a -0,000198) | sí | mejora | 3,8 % |
| + previsión | logística calibrada | 0,6244 | 0,120612 | 0,0070 | +0,000063 (IC 95 % -0,000053 a +0,000183) | no | sin diferencia clara | -0,7 % |
| + comuna | logística calibrada | 0,6200 | 0,120953 | 0,0109 | +0,000405 (IC 95 % +0,000164 a +0,000645) | sí | empeora | -4,2 % |
| + servicio de salud | logística sin calibrar | 0,6257 | 0,120468 | 0,0077 | -0,000080 (IC 95 % -0,000206 a +0,000041) | no | sin diferencia clara | 0,8 % |
| + las cuatro | logística calibrada | 0,6262 | 0,120522 | 0,0064 | -0,000026 (IC 95 % -0,000302 a +0,000268) | no | sin diferencia clara | 0,3 % |
| Oráculo (probabilidad verdadera del generador) | no aplica | 0,7370 | 0,110977 | 0,0037 | -0,009571 (sin IC) | no aplica | referencia | no aplica |

Lectura. Variantes que mejoran el Brier de forma significativa: + grupo etario. Variantes que lo empeoran de forma significativa: + comuna. Variantes sin diferencia clara con el principal: + previsión, + servicio de salud, + las cuatro. Una variante que empeora se informa tal cual: agregar variables no garantiza mejor desempeño fuera de la muestra de entrenamiento.

## Programador

Plan canónico de la corrida `d7a0c251-9a0f-5d0a-9941-5140560fb5b2` (100.000 entradas en espera), horizonte de 4 semanas, estado de revisión: pendiente de revisión humana. El programador asigna pacientes a cupos de consulta y bloques de pabellón respetando la capacidad disponible (12.498 cupos en 1.100 sesiones, 199.206 minutos en 651 bloques) y los plazos legales de garantía. Maximiza objetivos en orden lexicográfico: primero atender máxima prioridad, luego cumplir GES, luego maximizar puntaje total. El sobrecupo controlado agrega citas en sesiones de consulta usando la probabilidad predicha de inasistencia, con la condición de que el riesgo de que asistan más pacientes que cupos en cada sesión no supere α = 0,10. Los estados del solver indican si probó el óptimo de cada fase (OPTIMAL, dentro de la brecha relativa configurada), si encontró una solución sin probar que es la mejor (FEASIBLE, con su brecha) o si se quedó con la solución de partida sin cota útil (UNKNOWN); en todos los casos el plan es factible y verificado. Modelo usado: `noshow-4f0429cd-652dd76d`.

| Política | Agendadas | Consultas | Cirugías | Máxima prioridad agendadas | GES cumplidas | GES antes del plazo | Citas con sobrecupo | Puntaje total | Estado del solver | Brecha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| Orden de llegada | 13.312 | 11.957 | 1.355 | 871 | 337 | 14 | 0 | 54.768.964 | NOT_APPLICABLE | no aplica |
| Solo prioridad | 13.304 | 11.958 | 1.346 | 4.760 | 1.110 | 107 | 0 | 67.762.389 | NOT_APPLICABLE | no aplica |
| Optimizada | 13.750 | 12.283 | 1.467 | 4.778 | 1.645 | 650 | 325 | 69.861.974 | UNKNOWN | no aplica |

Diferencia de la optimizada frente a las políticas voraces:

| Métrica | Contra solo prioridad | Contra orden de llegada |
|---|---:|---:|
| Agendadas | +446 (3,4 %) | +438 (3,3 %) |
| Máxima prioridad agendadas | +18 (0,4 %) | +3.907 (448,6 %) |
| GES cumplidas | +535 (48,2 %) | +1.308 (388,1 %) |
| GES antes del plazo | +543 (507,5 %) | +636 (4.542,9 %) |
| Puntaje total | +2.099.585 (3,1 %) | +15.093.010 (27,6 %) |

Detalle de la optimizada: de 100.000 entradas en espera, 83.330 tienen algún bloque compatible y 16.670 no tienen ninguno; de las que tienen bloque compatible, 36.052 son candidatas y 47.278 quedan fuera del conjunto de candidatas. Sobrecupo: nivel alfa 0,10, 325 bloques con sobrecupo (325 con citas por sobre su capacidad, 325 citas por sobre la capacidad en total); 325 entradas ingresan en la fase 3b (incluye reemplazos, por lo que no equivale a las citas sobre la capacidad), riesgo exacto máximo 9,99 %. GES sin cumplir por causa:

| Causa | GES |
|---|---:|
| `capacity_taken` | 1.028 |
| `deadline_before_first_block` | 724 |
| `no_block_in_horizon` | 469 |

Tiempo y estados del solver (optimizada): 268 subproblemas, 55,5 s de pared medidos en el plan final más 18,8 s de una primera pasada descartada (74,3 s de pared en total); el tiempo de pared es informativo y el límite del plan se mide con el presupuesto descrito más abajo. Estado global: `UNKNOWN`. Colas que alcanzaron la frontera de candidatas: 43, y 4 siguieron en la frontera tras ampliarla.

| Fase | Subproblemas por estado | Total | Brecha máxima de la fase |
|---|---|---:|---:|
| 1 | OPTIMAL: 223 | 223 | no aplica |
| 2 | OPTIMAL: 132 | 132 | no aplica |
| 3a | FEASIBLE: 1, OPTIMAL: 267 | 268 | 0,039 % |
| 3b | FEASIBLE: 18, OPTIMAL: 46, UNKNOWN: 22 | 86 | no aplica |
| 4 | OPTIMAL: 118 | 118 | no aplica |

### Presupuesto de tiempo del plan

El límite de tiempo del plan es un presupuesto único que se reparte entre la primera pasada y la expansión de la frontera de candidatas. Unidad: unidades de tiempo determinista de CP-SAT (no son segundos). Plan reproducible (mismas entradas dan el mismo plan): sí.

| Concepto | Valor |
|---|---:|
| Presupuesto total | 120,0 |
| Gastado en total | 103,0 (85,8 % del total) |
| Primera pasada: asignado | 90,0 |
| Primera pasada: gastado | 74,2 |
| Expansión de frontera: asignado | 45,8 |
| Expansión de frontera: gastado | 28,8 |
| Componentes omitidos en la expansión | 0 |
| Fases terminadas por el límite de tiempo | 53 |
| Sobregiro | 0,0 |
| Presupuesto agotado | sí |

**El presupuesto se agotó.** Es un resultado desfavorable y se informa tal cual: parte de las fases se cerró por el límite de tiempo y no por haber probado el óptimo, así que el plan puede estar por debajo del mejor posible con más tiempo; los estados y brechas por fase de la tabla anterior muestran dónde ocurrió.
53 fases terminaron por el límite de tiempo en lugar de por una prueba de optimalidad.

Avisos del programador:

- candidate_frontier_reached en 43 colas
- candidate_frontier_reached persiste tras duplicar el margen en 4 colas
- time_budget_exhausted: 53 fases terminaron por el límite de tiempo y 0 componentes no se resolvieron de nuevo (presupuesto 120, unidad deterministic)
- lead_extrapolation: 151 citas con aviso fuera de 7-90 días; su p extrapola el modelo de inasistencias

### Benchmark por tamaño y horizonte

El benchmark mide el rendimiento del programador al crecer el tamaño (1.000, 10.000, 50.000 entradas) y el horizonte (2, 4 semanas): tiempo real de pared, estado final del solver y brecha del óptimo. Máquina: macOS-27.0.1-arm64-arm-64bit, 8 núcleos, Python 3.12.13, OR-Tools 9.15.6755; CP-SAT en modo determinista con 1 hilo, límite de 120 s para todo el plan (repartido entre subproblemas y fases), semilla 42. La comparación contra la política voraz de solo prioridad muestra el valor añadido de la optimización en celdas que alcanzan óptimo probado. Las celdas con estado FEASIBLE (sin prueba de optimalidad) reportan brecha positiva; algunas no pasan calibración estricta (se listan en cada celda), lo que indica limitación en la reproducción de agregados en esa población sintética.

| Entradas | Semanas | Estado | Brecha | Tiempo mediano (s) | Repeticiones | Candidatas | Subproblemas | Frontera sin resolver | Calibración de la corrida |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1.000 | 2 | OPTIMAL | 0,000 % | 0,01 | 3 | 34 | 12 | 0 | no pasa: C3.iq.mediana, C5.nacional.media(mapeados) |
| 1.000 | 4 | OPTIMAL | 0,000 % | 0,02 | 3 | 67 | 23 | 0 | no pasa: C3.iq.mediana, C5.nacional.media(mapeados) |
| 10.000 | 2 | OPTIMAL | 0,000 % | 0,13 | 3 | 1.188 | 87 | 0 | pasa |
| 10.000 | 4 | OPTIMAL | 0,000 % | 0,37 | 3 | 2.389 | 144 | 0 | pasa |
| 50.000 | 2 | OPTIMAL | 0,023 % | 9,04 | 3 | 7.554 | 252 | 3 | pasa |
| 50.000 | 4 | FEASIBLE | 0,496 % | 58,57 | 3 | 17.239 | 259 | 3 | pasa |

Optimizada frente a la voraz de solo prioridad en cada celda:

| Entradas | Semanas | Agendadas (optimizada) | Δ agendadas | Δ máxima prioridad agendadas | Δ GES cumplidas | Δ GES antes del plazo | Δ puntaje total | No peor en el orden lexicográfico | Sin sobrecupo, no peor |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1.000 | 2 | 30 | 0 | 0 | 0 | 0 | 0 | sí | sí |
| 1.000 | 4 | 60 | 0 | 0 | 0 | 0 | 0 | sí | sí |
| 10.000 | 2 | 614 | +12 | 0 | +2 | +1 | +34.532 | sí | sí |
| 10.000 | 4 | 1.276 | +29 | +1 | +13 | +12 | +72.306 | sí | sí |
| 50.000 | 2 | 3.224 | +122 | +11 | +46 | +54 | +639.240 | sí | sí |
| 50.000 | 4 | 6.951 | +263 | +5 | +248 | +266 | +1.196.566 | sí | sí |

#### Ablación de técnicas

Tiempo mediano de pared en segundos y estado final del solver, por variante y celda (entradas y semanas). Cada variante apaga una técnica de la formulación.

| Variante | 1.000 entradas, 2 sem | 1.000 entradas, 4 sem | 10.000 entradas, 2 sem | 10.000 entradas, 4 sem | 50.000 entradas, 2 sem | 50.000 entradas, 4 sem |
|---|---:|---:|---:|---:|---:|---:|
| Completa (todas las técnicas) | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,13 s, OPTIMAL | 0,37 s, OPTIMAL | 9,04 s, OPTIMAL | 58,57 s, FEASIBLE |
| Sin ninguna técnica | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,14 s, OPTIMAL | 0,37 s, OPTIMAL | 26,00 s, OPTIMAL | 58,05 s, UNKNOWN |
| Sin pistas de solución | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,13 s, OPTIMAL | 0,36 s, OPTIMAL | 7,72 s, OPTIMAL | 57,20 s, UNKNOWN |
| Sin corte del objetivo | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,13 s, OPTIMAL | 0,38 s, OPTIMAL | 8,02 s, OPTIMAL | 61,32 s, FEASIBLE |
| Sin pista de sobrecupo | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,14 s, OPTIMAL | 0,42 s, OPTIMAL | 11,41 s, OPTIMAL | 61,16 s, FEASIBLE |
| Sin poda de niveles de sobrecupo | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,19 s, OPTIMAL | 0,48 s, OPTIMAL | 18,62 s, OPTIMAL | 64,95 s, FEASIBLE |
| Sin ruptura de simetría | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,14 s, OPTIMAL | 0,36 s, OPTIMAL | 8,89 s, OPTIMAL | 59,25 s, FEASIBLE |
| Sin arranque en caliente de la frontera | 0,01 s, OPTIMAL | 0,01 s, OPTIMAL | 0,13 s, OPTIMAL | 0,36 s, OPTIMAL | 8,94 s, OPTIMAL | 60,14 s, FEASIBLE |

Puntaje total y brecha de cada variante en la celda más grande (50.000 entradas, 4 semanas):

| Variante | Estado | Brecha | Agendadas | Puntaje total | Tiempo mediano (s) | Repeticiones |
|---|---|---:|---:|---:|---:|---:|
| Completa (todas las técnicas) | FEASIBLE | 0,496 % | 6.951 | 33.392.317 | 58,57 | 3 |
| Sin ninguna técnica | UNKNOWN | no aplica | 6.918 | 33.270.922 | 58,05 | 1 |
| Sin pistas de solución | UNKNOWN | no aplica | 6.962 | 33.442.269 | 57,20 | 1 |
| Sin corte del objetivo | FEASIBLE | 0,436 % | 6.957 | 33.412.075 | 61,32 | 1 |
| Sin pista de sobrecupo | FEASIBLE | 0,943 % | 6.914 | 33.245.105 | 61,16 | 1 |
| Sin poda de niveles de sobrecupo | FEASIBLE | 0,966 % | 6.939 | 33.333.417 | 64,95 | 1 |
| Sin ruptura de simetría | FEASIBLE | 0,469 % | 6.956 | 33.414.947 | 59,25 | 1 |
| Sin arranque en caliente de la frontera | FEASIBLE | 0,484 % | 6.954 | 33.396.970 | 60,14 | 1 |

## Simulación

Simulación de 26 semanas con 5 réplicas (semillas 101, 102, 103, 104, 105). Cada semana, nuevos pacientes llegan a la lista, la política programa con el horizonte disponible (4 semanas), y los pacientes asisten o no según su probabilidad verdadera (de `synthetic.noshow_truth.true_noshow_prob`, sin usar la predicción). Réplicas con semillas distintas reproducen variabilidad; cada métrica reporta media e IC 95 % entre réplicas. Población de 10.000 entradas (corrida `d25b3696-d1f2-5e45-9185-1968ec968db0`, semilla 42), multiplicador de capacidad 1,00, tasa de abandono semanal 0,0 %, salida tras 2 inasistencias. Las comparaciones pareadas muestran la diferencia media entre políticas (por ejemplo, "Optimizada menos Prioridad"); dirección "mejor" significa que el IC 95 % está fuera de cero y el signo favorece la métrica; "peor" indica lo contrario. Las diferencias desfavorables (p. ej., donde la optimizada no gana) se reportan tal cual.

**Atención.** Esta simulación usa 10.000 entradas; el plan canónico usa 100.000. Las cifras de esta sección no son extrapolables al tamaño canónico.

### Medias por política

Media entre réplicas con su IC 95 %.

| Métrica | Orden de llegada | Solo prioridad | Optimizada | Optimizada con sobrecupo |
|---|---:|---:|---:|---:|
| Pacientes atendidos | 7.081,6 (IC 95 % 7.045,1 a 7.118,1) | 7.153,8 (IC 95 % 7.127,2 a 7.180,4) | 7.174,6 (IC 95 % 7.148,0 a 7.201,2) | 7.271,6 (IC 95 % 7.250,1 a 7.293,1) |
| Mediana de espera de los atendidos (días) | 362,4 (IC 95 % 361,0 a 363,8) | 302,7 (IC 95 % 300,9 a 304,5) | 299,8 (IC 95 % 298,2 a 301,4) | 299,0 (IC 95 % 297,0 a 301,0) |
| p90 de espera de los atendidos (días) | 806,8 (IC 95 % 801,9 a 811,8) | 777,4 (IC 95 % 769,7 a 785,1) | 774,0 (IC 95 % 764,5 a 783,5) | 772,0 (IC 95 % 762,8 a 781,2) |
| Mediana de espera de la lista final (días) | 129,0 (IC 95 % 128,1 a 129,9) | 144,6 (IC 95 % 143,9 a 145,3) | 143,8 (IC 95 % 143,2 a 144,4) | 143,0 (IC 95 % 143,0 a 143,0) |
| p90 de espera de la lista final (días) | 422,2 (IC 95 % 421,6 a 422,8) | 509,6 (IC 95 % 505,5 a 513,6) | 513,0 (IC 95 % 509,6 a 516,3) | 511,8 (IC 95 % 509,0 a 514,6) |
| Tamaño final de la lista | 10.558,4 (IC 95 % 10.496,7 a 10.620,1) | 10.498,0 (IC 95 % 10.418,9 a 10.577,1) | 10.477,4 (IC 95 % 10.394,9 a 10.559,9) | 10.380,6 (IC 95 % 10.302,4 a 10.458,8) |
| GES atendidas a tiempo | 58,6 (IC 95 % 53,9 a 63,3) | 431,6 (IC 95 % 413,6 a 449,6) | 625,0 (IC 95 % 613,5 a 636,5) | 645,0 (IC 95 % 636,1 a 653,9) |
| GES incumplidas | 1.350,4 (IC 95 % 1.306,0 a 1.394,8) | 1.192,6 (IC 95 % 1.149,6 a 1.235,6) | 1.028,8 (IC 95 % 985,5 a 1.072,1) | 1.027,8 (IC 95 % 984,6 a 1.071,0) |
| GES vencidas al final | 1.139,4 (IC 95 % 1.107,0 a 1.171,8) | 777,2 (IC 95 % 742,4 a 812,0) | 758,0 (IC 95 % 724,1 a 791,9) | 758,0 (IC 95 % 724,0 a 792,0) |
| Llegadas sin cupo en el horizonte del plan | 7.387,0 (IC 95 % 7.336,0 a 7.438,0) | 7.026,6 (IC 95 % 6.965,2 a 7.088,0) | 7.023,6 (IC 95 % 6.962,4 a 7.084,8) | 7.005,2 (IC 95 % 6.941,7 a 7.068,7) |
| Salidas por dos inasistencias | 105,4 (IC 95 % 87,0 a 123,8) | 93,6 (IC 95 % 81,2 a 106,0) | 93,4 (IC 95 % 81,9 a 104,9) | 93,2 (IC 95 % 83,6 a 102,8) |
| Inasistencia realizada, consultas | 16,0 % (IC 95 % 15,3 % a 16,7 %) | 15,3 % (IC 95 % 14,7 % a 16,0 %) | 15,4 % (IC 95 % 14,7 % a 16,0 %) | 15,3 % (IC 95 % 14,7 % a 16,0 %) |
| Inasistencia realizada, cirugías | 6,1 % (IC 95 % 4,7 % a 7,4 %) | 5,1 % (IC 95 % 3,6 % a 6,5 %) | 5,1 % (IC 95 % 3,6 % a 6,6 %) | 5,1 % (IC 95 % 3,6 % a 6,6 %) |
| Utilización de cupos de consulta | 82,4 % (IC 95 % 81,9 % a 82,9 %) | 83,1 % (IC 95 % 82,6 % a 83,5 %) | 83,0 % (IC 95 % 82,6 % a 83,5 %) | 84,2 % (IC 95 % 83,7 % a 84,6 %) |
| Utilización de pabellón | 68,8 % (IC 95 % 67,5 % a 70,0 %) | 69,1 % (IC 95 % 67,9 % a 70,3 %) | 69,4 % (IC 95 % 68,0 % a 70,8 %) | 69,4 % (IC 95 % 68,0 % a 70,8 %) |
| Cupos de consulta perdidos | 1.209,8 (IC 95 % 1.152,8 a 1.266,8) | 1.157,8 (IC 95 % 1.105,8 a 1.209,8) | 1.161,0 (IC 95 % 1.107,7 a 1.214,3) | 1.072,6 (IC 95 % 1.023,0 a 1.122,2) |
| Minutos de pabellón perdidos | 6.347,0 (IC 95 % 4.792,9 a 7.901,1) | 5.370,0 (IC 95 % 3.731,5 a 7.008,5) | 5.433,0 (IC 95 % 3.804,5 a 7.061,5) | 5.433,0 (IC 95 % 3.804,5 a 7.061,5) |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 11,0 (IC 95 % 8,2 a 13,8) |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 140,0 (IC 95 % 103,8 a 176,2) |

### Comparaciones pareadas

Diferencia pareada (política menos base) en las mismas réplicas, con IC 95 %. La lectura dice si el IC excluye el cero a favor ("mejora") o en contra ("empeora") según la dirección de la métrica; las diferencias desfavorables se muestran igual que las favorables. La comparación de orden de llegada contra solo prioridad es el espejo con signo invertido de la de solo prioridad contra orden de llegada y no se repite.

#### Optimizada frente a Solo prioridad

Métricas que mejoran: 8; que empeoran: 1; sin diferencia clara: 10. Empeoran: p90 de espera de la lista final (días).

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +20,8 (IC 95 % +16,7 a +24,9) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -2,9 (IC 95 % -3,6 a -2,2) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -3,4 (IC 95 % -6,5 a -0,3) | 4 de 5 | mejora |
| Mediana de espera de la lista final (días) | -0,8 (IC 95 % -1,4 a -0,2) | 4 de 5 | mejora |
| p90 de espera de la lista final (días) | +3,4 (IC 95 % +2,5 a +4,3) | 0 de 5 | empeora |
| Tamaño final de la lista | -20,6 (IC 95 % -24,8 a -16,4) | 5 de 5 | mejora |
| GES atendidas a tiempo | +193,4 (IC 95 % +174,8 a +212,0) | 5 de 5 | mejora |
| GES incumplidas | -163,8 (IC 95 % -176,5 a -151,1) | 5 de 5 | mejora |
| GES vencidas al final | -19,2 (IC 95 % -21,4 a -17,0) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -3,0 (IC 95 % -6,6 a +0,6) | 4 de 5 | sin diferencia clara |
| Salidas por dos inasistencias | -0,2 (IC 95 % -3,4 a +3,0) | 3 de 5 | sin diferencia clara |
| Inasistencia realizada, consultas | 0,0 pp (IC 95 % 0,0 pp a +0,1 pp) | 0 de 5 | sin diferencia clara |
| Inasistencia realizada, cirugías | 0,0 pp (IC 95 % -0,3 pp a +0,4 pp) | 3 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | 0,0 pp (IC 95 % -0,1 pp a 0,0 pp) | 0 de 5 | sin diferencia clara |
| Utilización de pabellón | +0,3 pp (IC 95 % 0,0 pp a +0,6 pp) | 5 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | +3,2 (IC 95 % -1,2 a +7,6) | 0 de 5 | sin diferencia clara |
| Minutos de pabellón perdidos | +63,0 (IC 95 % -222,3 a +348,3) | 2 de 5 | sin diferencia clara |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |

#### Optimizada frente a Orden de llegada

Métricas que mejoran: 12; que empeoran: 2; sin diferencia clara: 5. Empeoran: Mediana de espera de la lista final (días); p90 de espera de la lista final (días).

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +93,0 (IC 95 % +65,2 a +120,8) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -62,6 (IC 95 % -65,2 a -60,0) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -32,9 (IC 95 % -39,6 a -26,1) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | +14,8 (IC 95 % +13,8 a +15,8) | 0 de 5 | empeora |
| p90 de espera de la lista final (días) | +90,8 (IC 95 % +87,7 a +93,8) | 0 de 5 | empeora |
| Tamaño final de la lista | -81,0 (IC 95 % -105,1 a -56,9) | 5 de 5 | mejora |
| GES atendidas a tiempo | +566,4 (IC 95 % +555,3 a +577,5) | 5 de 5 | mejora |
| GES incumplidas | -321,6 (IC 95 % -332,9 a -310,3) | 5 de 5 | mejora |
| GES vencidas al final | -381,4 (IC 95 % -397,3 a -365,5) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -363,4 (IC 95 % -374,4 a -352,4) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -12,0 (IC 95 % -23,4 a -0,6) | 5 de 5 | mejora |
| Inasistencia realizada, consultas | -0,6 pp (IC 95 % -0,9 pp a -0,4 pp) | 5 de 5 | mejora |
| Inasistencia realizada, cirugías | -1,0 pp (IC 95 % -1,9 pp a 0,0 pp) | 5 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +0,6 pp (IC 95 % +0,4 pp a +0,9 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,6 pp (IC 95 % -0,3 pp a +1,6 pp) | 3 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -48,8 (IC 95 % -70,6 a -27,0) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -914,0 (IC 95 % -1.980,8 a +152,8) | 4 de 5 | sin diferencia clara |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |

#### Solo prioridad frente a Orden de llegada

Métricas que mejoran: 14; que empeoran: 2; sin diferencia clara: 3. Empeoran: Mediana de espera de la lista final (días); p90 de espera de la lista final (días).

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +72,2 (IC 95 % +47,7 a +96,7) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -59,7 (IC 95 % -62,7 a -56,7) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -29,4 (IC 95 % -35,0 a -23,9) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | +15,6 (IC 95 % +14,5 a +16,7) | 0 de 5 | empeora |
| p90 de espera de la lista final (días) | +87,4 (IC 95 % +83,6 a +91,2) | 0 de 5 | empeora |
| Tamaño final de la lista | -60,4 (IC 95 % -81,6 a -39,2) | 5 de 5 | mejora |
| GES atendidas a tiempo | +373,0 (IC 95 % +359,4 a +386,6) | 5 de 5 | mejora |
| GES incumplidas | -157,8 (IC 95 % -161,2 a -154,4) | 5 de 5 | mejora |
| GES vencidas al final | -362,2 (IC 95 % -380,0 a -344,4) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -360,4 (IC 95 % -371,5 a -349,3) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -11,8 (IC 95 % -20,8 a -2,8) | 5 de 5 | mejora |
| Inasistencia realizada, consultas | -0,7 pp (IC 95 % -0,9 pp a -0,4 pp) | 5 de 5 | mejora |
| Inasistencia realizada, cirugías | -1,0 pp (IC 95 % -1,9 pp a -0,1 pp) | 5 de 5 | mejora |
| Utilización de cupos de consulta | +0,7 pp (IC 95 % +0,4 pp a +0,9 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,3 pp (IC 95 % -0,3 pp a +1,0 pp) | 3 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -52,0 (IC 95 % -71,6 a -32,4) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -977,0 (IC 95 % -1.948,6 a -5,4) | 5 de 5 | mejora |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |

#### Optimizada con sobrecupo frente a Solo prioridad

Métricas que mejoran: 11; que empeoran: 3; sin diferencia clara: 5. Empeoran: p90 de espera de la lista final (días); Sesiones con desborde; Pacientes afectados por desborde.

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +117,8 (IC 95 % +110,8 a +124,8) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -3,7 (IC 95 % -5,3 a -2,1) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -5,4 (IC 95 % -8,8 a -1,9) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | -1,6 (IC 95 % -2,3 a -0,9) | 5 de 5 | mejora |
| p90 de espera de la lista final (días) | +2,2 (IC 95 % +0,7 a +3,8) | 0 de 5 | empeora |
| Tamaño final de la lista | -117,4 (IC 95 % -121,2 a -113,6) | 5 de 5 | mejora |
| GES atendidas a tiempo | +213,4 (IC 95 % +193,3 a +233,5) | 5 de 5 | mejora |
| GES incumplidas | -164,8 (IC 95 % -178,2 a -151,4) | 5 de 5 | mejora |
| GES vencidas al final | -19,2 (IC 95 % -22,4 a -16,0) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -21,4 (IC 95 % -32,2 a -10,6) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -0,4 (IC 95 % -4,0 a +3,2) | 3 de 5 | sin diferencia clara |
| Inasistencia realizada, consultas | 0,0 pp (IC 95 % 0,0 pp a +0,1 pp) | 2 de 5 | sin diferencia clara |
| Inasistencia realizada, cirugías | 0,0 pp (IC 95 % -0,3 pp a +0,4 pp) | 3 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +1,1 pp (IC 95 % +1,0 pp a +1,2 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,3 pp (IC 95 % 0,0 pp a +0,6 pp) | 5 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -85,2 (IC 95 % -92,9 a -77,5) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | +63,0 (IC 95 % -222,3 a +348,3) | 2 de 5 | sin diferencia clara |
| Sesiones con desborde | +11,0 (IC 95 % +8,2 a +13,8) | 0 de 5 | empeora |
| Pacientes afectados por desborde | +140,0 (IC 95 % +103,8 a +176,2) | 0 de 5 | empeora |

#### Optimizada con sobrecupo frente a Orden de llegada

Métricas que mejoran: 12; que empeoran: 4; sin diferencia clara: 3. Empeoran: Mediana de espera de la lista final (días); p90 de espera de la lista final (días); Sesiones con desborde; Pacientes afectados por desborde.

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +190,0 (IC 95 % +161,2 a +218,8) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -63,4 (IC 95 % -66,1 a -60,7) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -34,8 (IC 95 % -41,2 a -28,4) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | +14,0 (IC 95 % +13,1 a +14,9) | 0 de 5 | empeora |
| p90 de espera de la lista final (días) | +89,6 (IC 95 % +87,0 a +92,2) | 0 de 5 | empeora |
| Tamaño final de la lista | -177,8 (IC 95 % -199,7 a -155,9) | 5 de 5 | mejora |
| GES atendidas a tiempo | +586,4 (IC 95 % +576,0 a +596,8) | 5 de 5 | mejora |
| GES incumplidas | -322,6 (IC 95 % -334,8 a -310,4) | 5 de 5 | mejora |
| GES vencidas al final | -381,4 (IC 95 % -396,2 a -366,6) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -381,8 (IC 95 % -397,5 a -366,1) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -12,2 (IC 95 % -23,9 a -0,5) | 5 de 5 | mejora |
| Inasistencia realizada, consultas | -0,7 pp (IC 95 % -0,9 pp a -0,4 pp) | 5 de 5 | mejora |
| Inasistencia realizada, cirugías | -1,0 pp (IC 95 % -1,9 pp a 0,0 pp) | 5 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +1,8 pp (IC 95 % +1,5 pp a +2,1 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,6 pp (IC 95 % -0,3 pp a +1,6 pp) | 3 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -137,2 (IC 95 % -161,4 a -113,0) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -914,0 (IC 95 % -1.980,8 a +152,8) | 4 de 5 | sin diferencia clara |
| Sesiones con desborde | +11,0 (IC 95 % +8,2 a +13,8) | 0 de 5 | empeora |
| Pacientes afectados por desborde | +140,0 (IC 95 % +103,8 a +176,2) | 0 de 5 | empeora |

#### Optimizada con sobrecupo frente a Optimizada

Métricas que mejoran: 9; que empeoran: 2; sin diferencia clara: 8. Empeoran: Sesiones con desborde; Pacientes afectados por desborde.

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +97,0 (IC 95 % +91,3 a +102,7) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -0,8 (IC 95 % -1,8 a +0,2) | 3 de 5 | sin diferencia clara |
| p90 de espera de los atendidos (días) | -2,0 (IC 95 % -2,7 a -1,2) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | -0,8 (IC 95 % -1,4 a -0,2) | 4 de 5 | mejora |
| p90 de espera de la lista final (días) | -1,2 (IC 95 % -2,1 a -0,2) | 4 de 5 | mejora |
| Tamaño final de la lista | -96,8 (IC 95 % -102,5 a -91,1) | 5 de 5 | mejora |
| GES atendidas a tiempo | +20,0 (IC 95 % +13,8 a +26,2) | 5 de 5 | mejora |
| GES incumplidas | -1,0 (IC 95 % -2,2 a +0,2) | 3 de 5 | sin diferencia clara |
| GES vencidas al final | 0,0 (IC 95 % -1,2 a +1,2) | 2 de 5 | sin diferencia clara |
| Llegadas sin cupo en el horizonte del plan | -18,4 (IC 95 % -28,7 a -8,1) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -0,2 (IC 95 % -2,4 a +2,0) | 2 de 5 | sin diferencia clara |
| Inasistencia realizada, consultas | 0,0 pp (IC 95 % -0,1 pp a 0,0 pp) | 3 de 5 | sin diferencia clara |
| Inasistencia realizada, cirugías | 0,0 pp (IC 95 % 0,0 pp a 0,0 pp) | 0 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +1,1 pp (IC 95 % +1,0 pp a +1,2 pp) | 5 de 5 | mejora |
| Utilización de pabellón | 0,0 pp (IC 95 % 0,0 pp a 0,0 pp) | 0 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -88,4 (IC 95 % -93,4 a -83,4) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Sesiones con desborde | +11,0 (IC 95 % +8,2 a +13,8) | 0 de 5 | empeora |
| Pacientes afectados por desborde | +140,0 (IC 95 % +103,8 a +176,2) | 0 de 5 | empeora |

### Cobertura de la oferta

Algunas combinaciones de servicio y especialidad (celdas) no reciben ningún bloque de oferta en el periodo simulado, lo que deja parte del stock sin posibilidad de ser atendido: ninguna política puede programar citas en cupos que no existen. La tabla muestra la cobertura de la oferta sintética: qué fracción del stock cae en celdas que reciben al menos un bloque.

| Tipo de atención | Bloques de oferta | Celdas | Celdas con algún bloque | Stock | Stock en celdas con bloque |
|---|---:|---:|---:|---:|---:|
| Consulta nueva de especialidad | 1.067 | 1.246 | 726 (58,3 %) | 8.559 | 7.857 (91,8 %) |
| Intervención quirúrgica | 397 | 304 | 198 (65,1 %) | 1.441 | 1.279 (88,8 %) |

Minutos ofrecidos frente a la meta de la calibración:

| Tipo de atención | Minutos meta | Minutos ofrecidos | Ofrecido / meta |
|---|---:|---:|---:|
| Consulta nueva de especialidad | 162.663 | 153.960 | 94,6 % |
| Intervención quirúrgica | 152.349 | 142.920 | 93,8 % |

Histograma de duraciones de las sesiones (minutos por sesión):

| Tipo de atención | Duración (min) | Bloques | Proporción de los bloques |
|---|---:|---:|---:|
| Consulta nueva de especialidad | 60 | 429 | 40,2 % |
| Consulta nueva de especialidad | 120 | 164 | 15,4 % |
| Consulta nueva de especialidad | 180 | 87 | 8,2 % |
| Consulta nueva de especialidad | 240 | 387 | 36,3 % |
| Intervención quirúrgica | 360 | 397 | 100,0 % |

En consulta nueva de especialidad, 16,7 % de los 7.698 cupos están en sesiones que no admiten sobrecupo, y esas sesiones son 40,2 % de los 1.067 bloques. Cambio de equidad: el sobrecupo se permite según la duración de la sesión y las sesiones cortas no admiten ninguno, así que el sobreagendamiento solo puede operar en las sesiones largas. Los pacientes que dependen de sesiones cortas no se benefician de los cupos recuperados por inasistencia, mientras que quienes acceden a sesiones largas sí; si las sesiones cortas se concentran en ciertos servicios, comunas o previsiones, el efecto del sobrecupo se reparte de forma desigual, y por eso se mide por grupo en la sección de equidad.

### Programador dentro de la simulación

| Política | Planes semanales | Estados del solver por fase | Brecha máxima | Tiempo de pared del solver (s) |
|---|---:|---|---:|---:|
| Orden de llegada | 130 | no usa el solver | no aplica | 0,0 |
| Solo prioridad | 130 | no usa el solver | no aplica | 0,0 |
| Optimizada | 130 | 1: OPTIMAL 7.776; 2: OPTIMAL 4.827; 3a: OPTIMAL 23.411; 4: OPTIMAL 275 | 0,003 % | 5,1 |
| Optimizada con sobrecupo | 130 | 1: OPTIMAL 7.786; 2: OPTIMAL 4.822; 3a: OPTIMAL 23.431; 3b: OPTIMAL 3.486; 4: OPTIMAL 275 | 0,014 % | 8,4 |

Tiempo de simulación por política:

| Política | Media por réplica (s) | Total (s) |
|---|---:|---:|
| Orden de llegada | 16,1 | 80,3 |
| Solo prioridad | 15,6 | 78,0 |
| Optimizada | 20,4 | 101,9 |
| Optimizada con sobrecupo | 22,8 | 114,0 |

## Equidad

Se miden desigualdades por comuna, grupo etario y previsión en el programador y la simulación: exposición al sobrecupo (proporción de citas en cupos con overbooking), tasa de atención (agendadas sobre entradas) y mediana de espera. Brechas se calculan contra el total ponderado por entradas; la comuna del sintético es un atributo del paciente sin correlato económico o de distancia, por lo que no tiene efecto causal propio. Se nombran sin suavizar los grupos más expuestos o que quedan en desventaja frente a otros: el informe no filtra resultados por signo.

### Plan canónico

Referencia (todas las entradas):

| Política | Tasa de agendamiento | Exposición al sobrecupo | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|
| Orden de llegada | 13,31 % | 0,0 % | 0,0 % | 0,0 % |
| Solo prioridad | 13,30 % | 0,0 % | 0,0 % | 0,0 % |
| Optimizada | 13,75 % | 34,1 % | 2,6 % | 7,6 % |

La exposición al sobrecupo es la proporción de las citas de consulta agendadas que caen en un bloque con sobrecupo; la tasa de agendamiento es agendadas sobre entradas del grupo. Se listan grupos con al menos 30 entradas.

#### age_group

Grupo más expuesto al sobrecupo: 0-14 (39,4 %, +5,3 pp respecto del total, 10.751 entradas). Mayor desvío de exposición respecto del total: 0-14 (+5,3 pp). Mayor desvío de la tasa de agendamiento de la optimizada respecto del total: +0,21 pp (0-14). Grupos donde la optimizada agenda menos que solo prioridad: 0 de 5; peor caso: 0-14 (+0,20 pp). 5 grupos evaluados de 5.

| Grupo | Entradas | Agendamiento, orden de llegada | Agendamiento, solo prioridad | Agendamiento, optimizada | Δ optimizada contra solo prioridad | Exposición al sobrecupo | Desvío de exposición | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-14 | 10.751 | 13,60 % | 13,76 % | 13,96 % | +0,20 pp | 39,4 % | +5,3 pp | 3,3 % | 6,2 % |
| 15-19 | 4.340 | 13,92 % | 13,29 % | 13,69 % | +0,39 pp | 37,3 % | +3,2 pp | 3,2 % | 7,5 % |
| 20-44 | 23.586 | 13,28 % | 13,23 % | 13,67 % | +0,44 pp | 34,2 % | +0,1 pp | 3,1 % | 7,9 % |
| 45-64 | 31.133 | 13,12 % | 13,33 % | 13,93 % | +0,60 pp | 33,0 % | -1,1 pp | 2,2 % | 7,9 % |
| 65+ | 30.190 | 13,35 % | 13,17 % | 13,56 % | +0,39 pp | 32,7 % | -1,4 pp | 2,4 % | 7,7 % |

#### insurance

Grupo más expuesto al sobrecupo: fonasa b (35,2 %, +1,0 pp respecto del total, 38.982 entradas). Mayor desvío de exposición respecto del total: fonasa a (-2,0 pp). Mayor desvío de la tasa de agendamiento de la optimizada respecto del total: -0,44 pp (fonasa c). Grupos donde la optimizada agenda menos que solo prioridad: 0 de 5; peor caso: other (+0,28 pp). 5 grupos evaluados de 5.

| Grupo | Entradas | Agendamiento, orden de llegada | Agendamiento, solo prioridad | Agendamiento, optimizada | Δ optimizada contra solo prioridad | Exposición al sobrecupo | Desvío de exposición | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fonasa a | 18.435 | 13,19 % | 13,25 % | 13,64 % | +0,39 pp | 32,1 % | -2,0 pp | 2,1 % | 7,5 % |
| fonasa b | 38.982 | 13,33 % | 13,45 % | 13,93 % | +0,48 pp | 35,2 % | +1,0 pp | 2,8 % | 7,6 % |
| fonasa c | 15.030 | 13,19 % | 12,87 % | 13,31 % | +0,44 pp | 33,4 % | -0,7 pp | 2,5 % | 7,6 % |
| fonasa d | 21.487 | 13,49 % | 13,42 % | 13,90 % | +0,48 pp | 34,9 % | +0,7 pp | 3,1 % | 7,6 % |
| other | 6.066 | 13,25 % | 13,19 % | 13,47 % | +0,28 pp | 32,3 % | -1,8 pp | 1,8 % | 7,8 % |

#### commune_code

Grupo más expuesto al sobrecupo: 05703 (100,0 %, +65,9 pp respecto del total, 63 entradas). Mayor desvío de exposición respecto del total: 05703 (+65,9 pp). Mayor desvío de la tasa de agendamiento de la optimizada respecto del total: +15,20 pp (08104). Grupos donde la optimizada agenda menos que solo prioridad: 57 de 313; peor caso: 06113 (-2,99 pp). 313 grupos evaluados de 338.

Se listan los 10 grupos más expuestos.

| Grupo | Entradas | Agendamiento, orden de llegada | Agendamiento, solo prioridad | Agendamiento, optimizada | Δ optimizada contra solo prioridad | Exposición al sobrecupo | Desvío de exposición | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 05703 | 63 | 14,29 % | 4,76 % | 4,76 % | 0,00 pp | 100,0 % | +65,9 pp | 0,0 % | 7,7 % |
| 09208 | 96 | 13,54 % | 8,33 % | 8,33 % | 0,00 pp | 85,7 % | +51,6 pp | 14,3 % | 6,7 % |
| 05705 | 121 | 15,70 % | 18,18 % | 19,01 % | +0,83 pp | 71,4 % | +37,3 pp | 4,8 % | 8,8 % |
| 09203 | 72 | 6,94 % | 8,33 % | 9,72 % | +1,39 pp | 71,4 % | +37,3 pp | 14,3 % | 8,9 % |
| 05304 | 120 | 17,50 % | 20,00 % | 21,67 % | +1,67 pp | 68,2 % | +34,1 pp | 9,1 % | 9,1 % |
| 06201 | 31 | 19,35 % | 22,58 % | 22,58 % | 0,00 pp | 66,7 % | +32,5 pp | 0,0 % | 7,5 % |
| 01107 | 565 | 8,32 % | 8,14 % | 9,03 % | +0,88 pp | 60,9 % | +26,7 pp | 4,3 % | 8,8 % |
| 01403 | 320 | 6,25 % | 7,81 % | 8,13 % | +0,31 pp | 60,0 % | +25,9 pp | 4,0 % | 9,0 % |
| 10305 | 137 | 16,79 % | 13,14 % | 14,60 % | +1,46 pp | 60,0 % | +25,9 pp | 13,3 % | 6,9 % |
| 01401 | 189 | 10,05 % | 10,58 % | 8,99 % | -1,59 pp | 58,8 % | +24,7 pp | 5,9 % | 8,5 % |

### Simulación

Medias entre 5 réplicas, población de 10.000 entradas. La exposición al sobrecupo es la proporción de citas en sesiones con sobrecupo. Las brechas son contra el total de la dimensión ponderado por entradas.

#### age_group

Grupo más expuesto al sobrecupo (Optimizada con sobrecupo): 0-14 (20,3 %, +1,1 pp respecto del total, 1.833 entradas). 5 grupos evaluados.
| Política | Mayor desvío de la tasa de atención | Grupo | Menor tasa de atención | Grupo | Mayor desvío de la exposición | Grupo |
|---|---:|---|---:|---|---:|---|
| Orden de llegada | -3,3 pp | 0-14 | 36,7 % | 0-14 | 0,0 pp | ninguno |
| Solo prioridad | -3,9 pp | 0-14 | 36,4 % | 0-14 | 0,0 pp | ninguno |
| Optimizada | -3,9 pp | 0-14 | 36,5 % | 0-14 | 0,0 pp | ninguno |
| Optimizada con sobrecupo | -3,8 pp | 0-14 | 37,2 % | 0-14 | +1,1 pp | 0-14 |

| Grupo | Entradas | Atención, Orden de llegada | Atención, Solo prioridad | Atención, Optimizada | Atención, Optimizada con sobrecupo | Exposición al sobrecupo | Mediana de espera de atendidos, Optimizada con sobrecupo | GES incumplidas, Optimizada con sobrecupo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-14 | 1.833 | 36,7 % | 36,4 % | 36,5 % | 37,2 % | 20,3 % | 318,6 | 91,4 |
| 15-19 | 733 | 39,1 % | 38,6 % | 39,2 % | 39,7 % | 20,3 % | 325,7 | 24,6 |
| 20-44 | 4.204 | 39,5 % | 39,6 % | 39,6 % | 40,2 % | 18,9 % | 302,2 | 258,4 |
| 45-64 | 5.549 | 40,7 % | 40,8 % | 40,9 % | 41,4 % | 18,9 % | 299,2 | 305,8 |
| 65+ | 5.426 | 40,6 % | 41,9 % | 42,0 % | 42,6 % | 19,1 % | 289,9 | 347,6 |

#### insurance

Grupo más expuesto al sobrecupo (Optimizada con sobrecupo): fonasa d (19,7 %, +0,6 pp respecto del total, 3.817 entradas). 5 grupos evaluados.
| Política | Mayor desvío de la tasa de atención | Grupo | Menor tasa de atención | Grupo | Mayor desvío de la exposición | Grupo |
|---|---:|---|---:|---|---:|---|
| Orden de llegada | +0,4 pp | fonasa a | 39,6 % | fonasa b | 0,0 pp | ninguno |
| Solo prioridad | +0,8 pp | other | 39,9 % | fonasa c | 0,0 pp | ninguno |
| Optimizada | +0,9 pp | other | 39,8 % | fonasa c | 0,0 pp | ninguno |
| Optimizada con sobrecupo | +0,7 pp | other | 40,5 % | fonasa c | -0,8 pp | fonasa a |

| Grupo | Entradas | Atención, Orden de llegada | Atención, Solo prioridad | Atención, Optimizada | Atención, Optimizada con sobrecupo | Exposición al sobrecupo | Mediana de espera de atendidos, Optimizada con sobrecupo | GES incumplidas, Optimizada con sobrecupo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fonasa a | 3.302 | 40,3 % | 40,6 % | 40,9 % | 41,4 % | 18,4 % | 306,4 | 195,2 |
| fonasa b | 6.944 | 39,6 % | 40,0 % | 40,1 % | 40,7 % | 19,4 % | 302,3 | 398,4 |
| fonasa c | 2.642 | 40,2 % | 39,9 % | 39,8 % | 40,5 % | 18,8 % | 294,2 | 133,6 |
| fonasa d | 3.817 | 39,8 % | 40,7 % | 40,9 % | 41,4 % | 19,7 % | 289,4 | 257,0 |
| other | 1.041 | 40,3 % | 41,1 % | 41,3 % | 41,6 % | 18,8 % | 305,9 | 43,6 |

#### commune_code

Grupo más expuesto al sobrecupo (Optimizada con sobrecupo): 04204 (55,9 %, +37,0 pp respecto del total, 44 entradas). 207 grupos evaluados. De ellos, 48 no alcanzan el mínimo de entradas en todas las réplicas: se promedian sobre las réplicas en que aparecen, por lo que sus cifras son menos estables.
| Política | Mayor desvío de la tasa de atención | Grupo | Menor tasa de atención | Grupo | Mayor desvío de la exposición | Grupo |
|---|---:|---|---:|---|---:|---|
| Orden de llegada | -24,7 pp | 08206 | 15,1 % | 08206 | 0,0 pp | ninguno |
| Solo prioridad | -29,7 pp | 08207 | 10,7 % | 08207 | 0,0 pp | ninguno |
| Optimizada | -29,8 pp | 08207 | 10,7 % | 08207 | 0,0 pp | ninguno |
| Optimizada con sobrecupo | -30,4 pp | 08207 | 10,7 % | 08207 | +37,0 pp | 04204 |

Se listan los 10 grupos más expuestos al sobrecupo.

| Grupo | Entradas | Atención, Orden de llegada | Atención, Solo prioridad | Atención, Optimizada | Atención, Optimizada con sobrecupo | Exposición al sobrecupo | Mediana de espera de atendidos, Optimizada con sobrecupo | GES incumplidas, Optimizada con sobrecupo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 04204 | 44 | 49,5 % | 42,5 % | 43,4 % | 44,7 % | 55,9 % | 293,2 | 0,0 |
| 08308 | 34 | 35,3 % | 23,5 % | 23,5 % | 26,5 % | 50,0 % | 375,0 | 6,0 |
| 07402 | 36 | 38,3 % | 53,4 % | 54,4 % | 55,6 % | 46,3 % | 136,4 | 1,2 |
| 09107 | 34 | 22,8 % | 25,9 % | 22,9 % | 25,2 % | 45,8 % | 416,9 | 4,3 |
| 07108 | 31 | 54,8 % | 64,5 % | 64,5 % | 64,5 % | 42,1 % | 152,0 | 0,0 |
| 10106 | 35 | 44,2 % | 39,6 % | 41,3 % | 41,9 % | 40,8 % | 281,3 | 1,8 |
| 05401 | 35 | 36,4 % | 49,5 % | 47,3 % | 49,5 % | 40,5 % | 201,2 | 0,0 |
| 13303 | 42 | 35,0 % | 43,9 % | 44,5 % | 44,9 % | 39,4 % | 668,3 | 1,6 |
| 06101 | 213 | 45,5 % | 52,1 % | 52,5 % | 53,7 % | 38,5 % | 176,7 | 12,8 |
| 08105 | 47 | 55,6 % | 53,2 % | 52,3 % | 55,0 % | 38,1 % | 195,3 | 0,0 |

## Limitaciones

Los datos son sintéticos, calibrados a agregados públicos pero no derivados de ellos. Las conclusiones del informe valen únicamente para el mundo simulado: no son extrapolables a la red de salud real sin validación institucional e implementación cuidadosa. El sistema apoya la decisión pero no la toma; no hay validación clínica de los supuestos ni autorización de cambios en política de atención. Varios parámetros del generador (distribuciones de espera, composición por edad y previsión, tasas de inasistencia sintéticas) se derivan de datos públicos agregados pero no se comparan directamente con la realidad celda a celda; otros no tienen fuente pública y se listan abajo como supuestos sin verificar.

Supuestos del generador sin verificar con una fuente pública: 56 de 61.

- `capacity_multiplier`
- `cne_session_lengths_min`
- `cne_session_min`
- `cne_session_reference_weeks`
- `cne_session_starts`
- `commune_facility_weights`
- `consult_min`
- `general_age_mix`
- `ges_in_plazo_factor`
- `ges_in_plazo_wait`
- `ges_service_share_in_deadline`
- `history_lead_range_days`
- `history_max_appointments`
- `history_poisson_lambda`
- `history_window_days`
- `hospital_complexity_weights`
- `insurance_waitlist_proxy`
- `iq_block_lengths_min`
- `iq_block_min`
- `iq_block_start`
- `iq_turnover_min`
- `iq_utilization`
- `lognormal_sigma_floor`
- `noshow_e_p2_cne_target`
- `noshow_rate_iq`
- `noshow_rate_others_rule`
- `noshow_ref_lead_days`
- `noshow_scenarios`
- `noshow_sigma_u`
- `patient_link_retries`
- `pediatric_age_mix`
- `priority_mix_cne`
- `priority_mix_ges_oncologic`
- `priority_mix_iq`
- `timezone`
- `wait_clip_days`
- `ges_problem_map[11]`
- `ges_problem_map[26]`
- `ges_problem_map[12]`
- `ges_problem_map[35]`
- `ges_problem_map[10]`
- `ges_problem_map[44]`
- `ges_problem_map[43]`
- `ges_problem_map[30]`
- `ges_problem_map[25]`
- `ges_problem_map[8]`
- `ges_problem_map[70]`
- `ges_problem_map[3]`
- `ges_problem_map[27]`
- `ges_problem_map[28]`
- `ges_problem_map[81]`
- `ges_problem_map[16]`
- `ges_problem_map[17]`
- `ges_problem_map[31]`
- `ges_problem_map[29]`
- `ges_problem_map[56]`

Limitaciones declaradas por la simulación:

- Granularidad de la oferta: cada sesión atiende una sola celda (servicio x especialidad); a tamaños chicos muchas celdas no reciben ninguna sesión en el periodo simulado y su stock no puede atenderse con ninguna política (ver supply_coverage).
- Llegadas por Little en estado estacionario: sin estacionalidad, sin tendencia y con la espera media de un solo corte.
- La oferta replica la del generador (capacity_multiplier 1,0, sin margen) y es igual todas las semanas; no hay feriados, suspensiones de pabellón ni ausentismo de especialistas.
- Sin abandono ni otras causales administrativas por defecto; sin controles posteriores ni derivación a cirugía.
- El modelo de inasistencias no se reentrena durante la simulación.
- La verdad de inasistencia es la del generador: las conclusiones valen para ese mundo sintético, no para la red real.

Avisos del plan canónico:

- candidate_frontier_reached en 43 colas
- candidate_frontier_reached persiste tras duplicar el margen en 4 colas
- time_budget_exhausted: 53 fases terminaron por el límite de tiempo y 0 componentes no se resolvieron de nuevo (presupuesto 120, unidad deterministic)
- lead_extrapolation: 151 citas con aviso fuera de 7-90 días; su p extrapola el modelo de inasistencias

Advertencia del modelo de inasistencias: Con datos sintéticos, estas métricas validan el pipeline (que aprende la estructura que el generador puso), no el desempeño en pacientes reales.

## Metodología reproducible

El informe es determinista: dadas las mismas entradas (archivos en `results/`), se regenera byte a byte sin marcas de tiempo. Cada paso usa una semilla fija leída de los JSON para reproducibilidad: semilla única para la población sintética, para el entrenamiento del modelo y para la simulación de réplicas. Para verificar una cifra, búscala en el JSON de origen que indica la tabla de procedencia. Los pasos se corren en orden: síntesis, entrenamiento, programación, benchmark, simulación, reporte. Comandos, con argumentos y semillas leídos de los resultados:

```
make synth SIZE=100000 SEED=42
make train-noshow SIZE=100000 SEED=42 SCENARIO=baseline
make schedule SIZE=100000 SEED=42 SCENARIO=baseline WEEKS=4
make bench-scheduler BENCH_ARGS="--sizes 1000,10000,50000 --weeks 2,4 --seed 42 --scenario baseline --time-limit 120 --repeats 3"
make simulate SIM_ARGS="--size 10000 --seed 42 --scenario baseline --weeks 26 --replica-seeds 101,102,103,104,105 --horizon-weeks 4 --time-limit 30 --capacity-multiplier 1 --abandon-weekly-rate 0 --policies fifo,priority,optimized,optimized_overbooking"
make report
```

Archivos de origen:

| Archivo | Generado | Versión de código | Corridas | Semilla |
|---|---|---|---:|---:|
| `synthetic_calibration_baseline_seed42_n100000.json` | sin marca de tiempo | sin dato | 1 | 42 |
| `noshow.json` | sin marca de tiempo | noshow-4f0429cd-652dd76d | 1 | 42 |
| `schedule_d7a0c251-9a0f-5d0a-9941-5140560fb5b2_4w.json` | sin marca de tiempo | scheduler-0.1.0 | 1 | 42 |
| `scheduler-benchmark.json` | 10-10-2026 | scheduler-0.1.0 | 6 | 42 |
| `simulation.json` | 10-10-2026 | simulation-0.1.0 | 1 | 42 |

Último commit que modificó `results/`: `a71be63a1bc5ee7d9998c6aa3845741aa0a3ed78`.

Este informe se genera con `prioriza-report` y es determinista: con los mismos resultados produce los mismos bytes, sin hora de generación.
