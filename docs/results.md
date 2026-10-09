# Informe de resultados de Prioriza

> **Aviso.** Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Qué es este informe

Este informe compara cuatro políticas de atención para la corrida sintética `32c9e349-74f9-5c85-bf4b-990796b47323`: orden de llegada (línea de base), solo prioridad clínica, programación optimizada respetando la capacidad y los plazos, y programación optimizada con sobrecupo controlado. El sistema apoya la decisión pero no la toma: cada plan se genera bajo demanda y permanece pendiente de revisión humana antes de cualquier uso. Todas las cifras provienen de `results/` sin escritura manual.

Las corridas que alimentan el informe no tienen el mismo tamaño:

| Resultado | Entradas de la corrida | Corrida |
|---|---:|---|
| synthetic_calibration_baseline_seed42_n100000.json | 100.000 | 32c9e349 |
| noshow.json | 100.000 | 32c9e349 |
| schedule_32c9e349-74f9-5c85-bf4b-990796b47323_4w.json | 100.000 | 32c9e349 |
| scheduler-benchmark.json | 1.000, 10.000, 50.000 | 01f43e87, 062f5290, 08c2871c, 7dc0d40f, 9fedfa46, e0e261f1 |
| simulation.json | 10.000 | a0386f24 |

**Atención.** La simulación corrió con una población de 10.000 entradas y el plan canónico usa 100.000. Las cifras absolutas de la simulación no son comparables con las del plan canónico; solo se comparan entre las políticas de la misma simulación.

## Contexto y fuentes

Al momento de corte de la Glosa 06 (30-09-2025), el sistema público de Chile registraba las entradas en espera, las garantías GES retrasadas y las medianas de espera que muestra la tabla de esta sección. La población de esta corrida es sintética: generada de forma controlada con semilla fija y calibrada a partir de datos públicos agregados para reproducir el tamaño, composición y tiempos de espera observados. Los chequeos de calibración muestran si el simulador replica fielmente estos agregados; cuando alguno falla (especialmente si es informativo y no estricto), indica una limitación en la reproducción que debe interpretarse al examinar los resultados. Fuentes de calibración: `glosa06_2025q3` (30-09-2025), `glosa06_2025q4` (31-12-2025), `glosa06_2026q1` (31-03-2026), `sis_ges_cases_2026q1` (31-03-2026), `minsal_establishments`.
| Lista | Registros | Personas | Espera media (días) | Mediana de espera (días) |
|---|---:|---:|---:|---:|
| Consulta nueva de especialidad | 2.576.371 | 2.134.364 | 341 | 242 |
| Intervención quirúrgica | 417.561 | 365.781 | 394 | 264 |
| Garantías GES retrasadas | 80.022 | sin dato | 136 | 71 |

### Calibración de la población sintética

La población de la corrida `32c9e349-74f9-5c85-bf4b-990796b47323` (100.000 entradas, semilla 42, escenario `baseline`) se contrastó con los objetivos públicos. Chequeos estrictos que pasan: 26; estrictos que fallan: 0; informativos que fallan: 1; omitidos: 0. Resultado global: pasa.

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
| C8.minutos_programados | strict | max\|min/sem - objetivo\| | 6,36 | 0 | sin dato | sí |
| C9.E[p2]_cne | soft | E[p²] CNE | 0,0383 | 0,0304 | 0,0150 | sí |
| C9.cobertura_ges | soft | cobertura sobre retrasadas | 0,682 | 1 | sin dato | sí |
| C9.cramer_v_servicio_x_especialidad | soft | V de Cramér | 0,0307 | sin dato | sin dato | sí |

- Celdas (servicio, especialidad) con entradas pero sin sesiones: 613 de 2216

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
| Orden de llegada | 13.169 | 844 | 3.866 | 342 | 23 | 3.524 |
| Solo prioridad | 13.168 | 4.146 | 3.866 | 1.070 | 92 | 2.796 |
| Optimizada | 13.616 | 4.150 | 3.866 | 1.594 | 615 | 2.272 |

## Modelo de inasistencias

Modelo principal: `logistic_regression_uncalibrated` (versión `noshow-4f0429cd-3ba6e988`), sin calibrar. Predice la probabilidad de que un paciente no se presente a su cita (inasistencia), usando solo las variables permitidas: `specialty_code`, `care_type`, `weekday`, `lead_days`, `prior_attended`, `prior_no_show`. Edad, previsión, comuna y servicio de salud no entran al modelo (se usan solo para medir equidad; motivos en la tabla de variables excluidas). Criterio de selección del modelo principal: Menor Brier en el conjunto de calibración entre los modelos sin calibrar (que no lo vieron al entrenar) y calibrados (predicciones fuera de pliegue, KFold contiguo). El conjunto de prueba no participa. Con datos sintéticos se valida la canalización (ingesta, features, entrenamiento, calibración, persistencia) pero no el desempeño en la población real. AUC mide la capacidad de separar asistencias de inasistencias; Brier es el error cuadrático medio; la calibración compara la probabilidad predicha contra la tasa observada. El intervalo de confianza del Δ Brier contra el baseline (1.000 remuestreos por paciente) excluye el cero: sí. Las brechas por grupo contra la verdad sintética muestran si el modelo da estimaciones sesgadas en grupos específicos; diferencias negativas indican sobrestimación.

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

Diferencia de Brier del modelo principal contra el baseline por especialidad: -0,0010 (IC 95 % -0,0012 a -0,0007; 1.000 remuestreos por paciente). Mejora al baseline: sí; el IC 95 % excluye el cero: sí.

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

**age_group**: 5 grupos evaluados de 5; mayor brecha absoluta contra la verdad: +3,21 pp, en el grupo 15-19.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| 0-14 | 3.391 | 17,8 % | 17,6 % | 17,4 % | +0,18 pp |
| 15-19 | 1.364 | 16,7 % | 15,4 % | 18,6 % | -3,21 pp |
| 20-44 | 7.281 | 17,1 % | 14,4 % | 17,6 % | -3,13 pp |
| 45-64 | 9.965 | 13,7 % | 14,1 % | 13,7 % | +0,46 pp |
| 65+ | 9.621 | 11,7 % | 14,0 % | 11,7 % | +2,27 pp |

**care_type**: 2 grupos evaluados de 2; mayor brecha absoluta contra la verdad: +0,54 pp, en el grupo surgery.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| consultation | 26.900 | 16,0 % | 16,3 % | 16,2 % | +0,09 pp |
| surgery | 4.722 | 5,6 % | 4,8 % | 5,3 % | -0,54 pp |

**insurance**: 5 grupos evaluados de 5; mayor brecha absoluta contra la verdad: +0,23 pp, en el grupo fonasa a.

| Grupo | Citas | Tasa observada | Predicha media | Verdad media | Brecha contra la verdad |
|---|---:|---:|---:|---:|---:|
| fonasa a | 5.867 | 14,0 % | 14,6 % | 14,3 % | +0,23 pp |
| fonasa b | 12.378 | 14,5 % | 14,6 % | 14,6 % | -0,02 pp |
| fonasa c | 4.702 | 14,6 % | 14,7 % | 14,7 % | -0,07 pp |
| fonasa d | 6.811 | 14,6 % | 14,5 % | 14,7 % | -0,16 pp |
| other | 1.864 | 14,8 % | 14,6 % | 14,5 % | +0,09 pp |

**health_service_code**: 29 grupos evaluados de 29; mayor brecha absoluta contra la verdad: +4,94 pp, en el grupo 1.

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

**commune_code**: 44 grupos evaluados de 338; mayor brecha absoluta contra la verdad: +5,11 pp, en el grupo 15101. En el sintético la comuna no tiene efecto propio (solo vía servicio), así que este análisis no puede detectar daño por comuna aunque exista en la realidad.

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

## Programador

Plan canónico de la corrida `32c9e349-74f9-5c85-bf4b-990796b47323` (100.000 entradas en espera), horizonte de 4 semanas, estado de revisión: pendiente de revisión humana. El programador asigna pacientes a cupos de consulta y bloques de pabellón respetando la capacidad disponible (12.504 cupos en 1.042 sesiones, 199.818 minutos en 653 bloques) y los plazos legales de garantía. Maximiza objetivos en orden lexicográfico: primero atender máxima prioridad, luego cumplir GES, luego maximizar puntaje total. El sobrecupo controlado agrega citas en sesiones de consulta usando la probabilidad predicha de inasistencia, con la condición de que el riesgo de que asistan más pacientes que cupos en cada sesión no supere α = 0,10. Los estados del solver indican si probó el óptimo de cada fase (OPTIMAL, dentro de la brecha relativa configurada), si encontró una solución sin probar que es la mejor (FEASIBLE, con su brecha) o si se quedó con la solución de partida sin cota útil (UNKNOWN); en todos los casos el plan es factible y verificado. Modelo usado: `noshow-4f0429cd-3ba6e988`.

| Política | Agendadas | Consultas | Cirugías | Máxima prioridad agendadas | GES cumplidas | GES antes del plazo | Citas con sobrecupo | Puntaje total | Estado del solver | Brecha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| Orden de llegada | 13.169 | 11.905 | 1.264 | 844 | 342 | 23 | 0 | 52.705.746 | NOT_APPLICABLE | no aplica |
| Solo prioridad | 13.168 | 11.906 | 1.262 | 4.146 | 1.070 | 92 | 0 | 64.732.928 | NOT_APPLICABLE | no aplica |
| Optimizada | 13.616 | 12.212 | 1.404 | 4.150 | 1.594 | 615 | 343 | 66.454.560 | UNKNOWN | no aplica |

Diferencia de la optimizada frente a las políticas voraces:

| Métrica | Contra solo prioridad | Contra orden de llegada |
|---|---:|---:|
| Agendadas | +448 (3,4 %) | +447 (3,4 %) |
| Máxima prioridad agendadas | +4 (0,1 %) | +3.306 (391,7 %) |
| GES cumplidas | +524 (49,0 %) | +1.252 (366,1 %) |
| GES antes del plazo | +523 (568,5 %) | +592 (2.573,9 %) |
| Puntaje total | +1.721.632 (2,7 %) | +13.748.814 (26,1 %) |

Detalle de la optimizada: 40.870 candidatas de 100.000 en espera (31.978 fuera del conjunto de candidatas). Sobrecupo: nivel alfa 0,10, 343 bloques con sobrecupo, 540 citas agregadas por sobrecupo, riesgo exacto máximo 9,99 %. GES sin cumplir por causa:

| Causa | GES |
|---|---:|
| `capacity_taken` | 652 |
| `deadline_before_first_block` | 602 |
| `no_block_in_horizon` | 1.018 |

Tiempo y estados del solver (optimizada): 159 subproblemas, 98,2 s de pared en el plan final más 42,1 s de una primera pasada descartada (140,2 s en total); límite configurado de 120 s para todo el plan, repartido entre subproblemas; con la primera pasada descartada el total puede superarlo. Estado global: `UNKNOWN`. Colas que alcanzaron la frontera de candidatas: 96, y 14 siguieron en la frontera tras ampliarla.

| Fase | Subproblemas por estado | Total | Brecha máxima de la fase |
|---|---|---:|---:|
| 1 | OPTIMAL: 136 | 136 | no aplica |
| 2 | OPTIMAL: 89 | 89 | no aplica |
| 3a | FEASIBLE: 4, OPTIMAL: 155 | 159 | 2,060 % |
| 3b | FEASIBLE: 16, OPTIMAL: 42, UNKNOWN: 21 | 79 | no aplica |
| 4 | FEASIBLE: 6, OPTIMAL: 76, UNKNOWN: 14 | 96 | no aplica |

Avisos del programador:

- candidate_frontier_reached en 96 colas
- candidate_frontier_reached persiste tras duplicar el margen en 14 colas
- lead_extrapolation: 139 citas con aviso fuera de 7-90 días; su p extrapola el modelo de inasistencias

### Benchmark por tamaño y horizonte

El benchmark mide el rendimiento del programador al crecer el tamaño (1.000, 10.000, 50.000 entradas) y el horizonte (2, 4 semanas): tiempo real de pared, estado final del solver y brecha del óptimo. Máquina: macOS-27.0.1-arm64-arm-64bit, 8 núcleos, Python 3.12.13, OR-Tools 9.15.6755; CP-SAT en modo determinista con 1 hilo, límite de 120 s para todo el plan (repartido entre subproblemas y fases), semilla 42. La comparación contra la política voraz de solo prioridad muestra el valor añadido de la optimización en celdas que alcanzan óptimo probado. Las celdas con estado FEASIBLE (sin prueba de optimalidad) reportan brecha positiva; algunas no pasan calibración estricta (se listan en cada celda), lo que indica limitación en la reproducción de agregados en esa población sintética.

| Entradas | Semanas | Estado | Brecha | Tiempo mediano (s) | Repeticiones | Candidatas | Subproblemas | Frontera sin resolver | Calibración de la corrida |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1.000 | 2 | OPTIMAL | 0,000 % | 0,01 | 3 | 81 | 9 | 0 | no pasa: C3.iq.mediana, C5.nacional.media(mapeados) |
| 1.000 | 4 | OPTIMAL | 0,000 % | 0,02 | 3 | 111 | 17 | 0 | no pasa: C3.iq.mediana, C5.nacional.media(mapeados) |
| 10.000 | 2 | OPTIMAL | 0,000 % | 0,16 | 3 | 1.527 | 66 | 0 | pasa |
| 10.000 | 4 | OPTIMAL | 0,002 % | 0,39 | 3 | 2.879 | 94 | 0 | pasa |
| 50.000 | 2 | OPTIMAL | 0,020 % | 15,13 | 3 | 8.673 | 190 | 4 | pasa |
| 50.000 | 4 | FEASIBLE | 0,366 % | 93,76 | 3 | 18.430 | 190 | 3 | pasa |

Optimizada frente a la voraz de solo prioridad en cada celda:

| Entradas | Semanas | Agendadas (optimizada) | Δ agendadas | Δ máxima prioridad agendadas | Δ GES cumplidas | Δ GES antes del plazo | Δ puntaje total | No peor en el orden lexicográfico | Sin sobrecupo, no peor |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1.000 | 2 | 79 | 0 | 0 | 0 | 0 | 0 | sí | sí |
| 1.000 | 4 | 108 | +1 | 0 | 0 | 0 | +530 | sí | sí |
| 10.000 | 2 | 673 | +16 | +1 | +6 | +6 | +36.109 | sí | sí |
| 10.000 | 4 | 1.333 | +31 | +1 | +13 | +12 | +60.255 | sí | sí |
| 50.000 | 2 | 3.338 | +120 | +13 | +43 | +60 | +695.144 | sí | sí |
| 50.000 | 4 | 6.935 | +284 | +6 | +225 | +240 | +1.324.117 | sí | sí |

#### Ablación de técnicas

Tiempo mediano de pared en segundos y estado final del solver, por variante y celda (entradas y semanas). Cada variante apaga una técnica de la formulación.

| Variante | 1.000 entradas, 2 sem | 1.000 entradas, 4 sem | 10.000 entradas, 2 sem | 10.000 entradas, 4 sem | 50.000 entradas, 2 sem | 50.000 entradas, 4 sem |
|---|---:|---:|---:|---:|---:|---:|
| Completa (todas las técnicas) | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,16 s, OPTIMAL | 0,39 s, OPTIMAL | 15,13 s, OPTIMAL | 93,76 s, FEASIBLE |
| Sin ninguna técnica | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,16 s, OPTIMAL | 0,42 s, OPTIMAL | 17,38 s, OPTIMAL | 115,95 s, UNKNOWN |
| Sin pistas de solución | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,15 s, OPTIMAL | 0,39 s, OPTIMAL | 12,13 s, UNKNOWN | 100,36 s, UNKNOWN |
| Sin corte del objetivo | 0,01 s, OPTIMAL | 0,01 s, OPTIMAL | 0,16 s, OPTIMAL | 0,38 s, OPTIMAL | 15,25 s, OPTIMAL | 100,59 s, FEASIBLE |
| Sin pista de sobrecupo | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,16 s, OPTIMAL | 0,44 s, OPTIMAL | 15,07 s, OPTIMAL | 106,51 s, FEASIBLE |
| Sin poda de niveles de sobrecupo | 0,02 s, OPTIMAL | 0,02 s, OPTIMAL | 0,21 s, OPTIMAL | 0,50 s, OPTIMAL | 14,01 s, OPTIMAL | 112,34 s, FEASIBLE |
| Sin ruptura de simetría | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,16 s, OPTIMAL | 0,40 s, OPTIMAL | 15,69 s, OPTIMAL | 98,22 s, FEASIBLE |
| Sin arranque en caliente de la frontera | 0,01 s, OPTIMAL | 0,02 s, OPTIMAL | 0,16 s, OPTIMAL | 0,40 s, OPTIMAL | 14,58 s, OPTIMAL | 96,06 s, FEASIBLE |

Puntaje total y brecha de cada variante en la celda más grande (50.000 entradas, 4 semanas):

| Variante | Estado | Brecha | Agendadas | Puntaje total | Tiempo mediano (s) | Repeticiones |
|---|---|---:|---:|---:|---:|---:|
| Completa (todas las técnicas) | FEASIBLE | 0,366 % | 6.935 | 34.848.421 | 93,76 | 3 |
| Sin ninguna técnica | UNKNOWN | no aplica | 6.884 | 34.655.722 | 115,95 | 1 |
| Sin pistas de solución | UNKNOWN | no aplica | 6.944 | 34.885.292 | 100,36 | 1 |
| Sin corte del objetivo | FEASIBLE | 0,387 % | 6.934 | 34.842.298 | 100,59 | 1 |
| Sin pista de sobrecupo | FEASIBLE | 0,815 % | 6.898 | 34.691.199 | 106,51 | 1 |
| Sin poda de niveles de sobrecupo | FEASIBLE | 0,915 % | 6.924 | 34.799.074 | 112,34 | 1 |
| Sin ruptura de simetría | FEASIBLE | 0,374 % | 6.935 | 34.850.118 | 98,22 | 1 |
| Sin arranque en caliente de la frontera | FEASIBLE | 0,347 % | 6.937 | 34.856.501 | 96,06 | 1 |

## Simulación

Simulación de 26 semanas con 5 réplicas (semillas 101, 102, 103, 104, 105). Cada semana, nuevos pacientes llegan a la lista, la política programa con el horizonte disponible (4 semanas), y los pacientes asisten o no según su probabilidad verdadera (de `synthetic.noshow_truth.true_noshow_prob`, sin usar la predicción). Réplicas con semillas distintas reproducen variabilidad; cada métrica reporta media e IC 95 % entre réplicas. Población de 10.000 entradas (corrida `a0386f24-5378-5fee-add8-5c1e1c81fa7e`, semilla 42), multiplicador de capacidad 1,00, tasa de abandono semanal 0,0 %, salida tras 2 inasistencias. Las comparaciones pareadas muestran la diferencia media entre políticas (por ejemplo, "Optimizada menos Prioridad"); dirección "mejor" significa que el IC 95 % está fuera de cero y el signo favorece la métrica; "peor" indica lo contrario. Las diferencias desfavorables (p. ej., donde la optimizada no gana) se reportan tal cual.

**Atención.** Esta simulación usa 10.000 entradas; el plan canónico usa 100.000. Las cifras de esta sección no son extrapolables al tamaño canónico.

### Medias por política

Media entre réplicas con su IC 95 %.

| Métrica | Orden de llegada | Solo prioridad | Optimizada | Optimizada con sobrecupo |
|---|---:|---:|---:|---:|
| Pacientes atendidos | 6.428,4 (IC 95 % 6.400,6 a 6.456,2) | 6.482,8 (IC 95 % 6.448,2 a 6.517,4) | 6.515,2 (IC 95 % 6.475,9 a 6.554,5) | 6.616,0 (IC 95 % 6.577,8 a 6.654,2) |
| Mediana de espera de los atendidos (días) | 356,8 (IC 95 % 355,0 a 358,6) | 300,7 (IC 95 % 299,2 a 302,2) | 295,4 (IC 95 % 293,5 a 297,3) | 294,9 (IC 95 % 293,1 a 296,7) |
| p90 de espera de los atendidos (días) | 799,9 (IC 95 % 796,3 a 803,6) | 772,5 (IC 95 % 767,3 a 777,7) | 768,3 (IC 95 % 764,2 a 772,4) | 766,0 (IC 95 % 761,5 a 770,4) |
| Mediana de espera de la lista final (días) | 138,6 (IC 95 % 137,2 a 140,0) | 154,4 (IC 95 % 153,0 a 155,8) | 154,4 (IC 95 % 153,0 a 155,8) | 153,8 (IC 95 % 152,0 a 155,6) |
| p90 de espera de la lista final (días) | 488,4 (IC 95 % 484,7 a 492,1) | 552,0 (IC 95 % 548,5 a 555,5) | 554,9 (IC 95 % 550,9 a 558,9) | 554,5 (IC 95 % 550,6 a 558,4) |
| Tamaño final de la lista | 11.239,8 (IC 95 % 11.171,3 a 11.308,3) | 11.192,6 (IC 95 % 11.119,2 a 11.266,0) | 11.161,8 (IC 95 % 11.088,7 a 11.234,9) | 11.058,6 (IC 95 % 10.987,8 a 11.129,4) |
| GES atendidas a tiempo | 56,4 (IC 95 % 50,9 a 61,9) | 416,8 (IC 95 % 388,5 a 445,1) | 619,4 (IC 95 % 589,1 a 649,7) | 634,6 (IC 95 % 601,9 a 667,3) |
| GES incumplidas | 1.358,8 (IC 95 % 1.318,7 a 1.398,9) | 1.201,4 (IC 95 % 1.163,4 a 1.239,4) | 1.034,6 (IC 95 % 1.002,0 a 1.067,2) | 1.034,2 (IC 95 % 1.000,9 a 1.067,5) |
| GES vencidas al final | 1.166,0 (IC 95 % 1.118,8 a 1.213,2) | 833,6 (IC 95 % 790,5 a 876,7) | 813,4 (IC 95 % 772,0 a 854,8) | 813,2 (IC 95 % 772,2 a 854,2) |
| Llegadas sin cupo en el horizonte del plan | 7.337,2 (IC 95 % 7.286,6 a 7.387,8) | 7.003,0 (IC 95 % 6.964,0 a 7.042,0) | 6.998,8 (IC 95 % 6.962,7 a 7.034,9) | 6.979,4 (IC 95 % 6.938,9 a 7.019,9) |
| Salidas por dos inasistencias | 77,2 (IC 95 % 69,9 a 84,5) | 70,0 (IC 95 % 66,2 a 73,8) | 68,4 (IC 95 % 61,8 a 75,0) | 70,8 (IC 95 % 65,4 a 76,2) |
| Inasistencia realizada, consultas | 15,4 % (IC 95 % 15,2 % a 15,6 %) | 14,9 % (IC 95 % 14,7 % a 15,1 %) | 14,9 % (IC 95 % 14,5 % a 15,2 %) | 14,9 % (IC 95 % 14,6 % a 15,2 %) |
| Inasistencia realizada, cirugías | 5,3 % (IC 95 % 4,0 % a 6,6 %) | 4,8 % (IC 95 % 3,9 % a 5,7 %) | 4,6 % (IC 95 % 3,7 % a 5,4 %) | 4,6 % (IC 95 % 3,7 % a 5,4 %) |
| Utilización de cupos de consulta | 69,8 % (IC 95 % 69,5 % a 70,2 %) | 70,3 % (IC 95 % 69,9 % a 70,7 %) | 70,3 % (IC 95 % 69,9 % a 70,8 %) | 71,4 % (IC 95 % 71,0 % a 71,9 %) |
| Utilización de pabellón | 67,9 % (IC 95 % 66,8 % a 68,9 %) | 67,8 % (IC 95 % 67,0 % a 68,7 %) | 68,3 % (IC 95 % 67,4 % a 69,1 %) | 68,3 % (IC 95 % 67,4 % a 69,1 %) |
| Cupos de consulta perdidos | 1.030,2 (IC 95 % 1.017,0 a 1.043,4) | 995,4 (IC 95 % 981,9 a 1.008,9) | 993,2 (IC 95 % 972,4 a 1.014,0) | 901,8 (IC 95 % 883,2 a 920,4) |
| Minutos de pabellón perdidos | 6.049,0 (IC 95 % 4.458,1 a 7.639,9) | 5.447,0 (IC 95 % 4.124,0 a 6.770,0) | 5.244,0 (IC 95 % 3.787,8 a 6.700,2) | 5.244,0 (IC 95 % 3.787,8 a 6.700,2) |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 11,8 (IC 95 % 6,2 a 17,4) |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 0,0 (IC 95 % 0,0 a 0,0) | 153,4 (IC 95 % 80,0 a 226,8) |

### Comparaciones pareadas

Diferencia pareada (política menos base) en las mismas réplicas, con IC 95 %. La lectura dice si el IC excluye el cero a favor ("mejora") o en contra ("empeora") según la dirección de la métrica; las diferencias desfavorables se muestran igual que las favorables. La comparación de orden de llegada contra solo prioridad es el espejo con signo invertido de la de solo prioridad contra orden de llegada y no se repite.

#### Optimizada frente a Solo prioridad

Métricas que mejoran: 8; que empeoran: 1; sin diferencia clara: 10. Empeoran: p90 de espera de la lista final (días).

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +32,4 (IC 95 % +24,4 a +40,4) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -5,3 (IC 95 % -5,9 a -4,7) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -4,2 (IC 95 % -7,0 a -1,3) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| p90 de espera de la lista final (días) | +2,9 (IC 95 % +1,5 a +4,4) | 0 de 5 | empeora |
| Tamaño final de la lista | -30,8 (IC 95 % -37,9 a -23,7) | 5 de 5 | mejora |
| GES atendidas a tiempo | +202,6 (IC 95 % +190,7 a +214,5) | 5 de 5 | mejora |
| GES incumplidas | -166,8 (IC 95 % -182,7 a -150,9) | 5 de 5 | mejora |
| GES vencidas al final | -20,2 (IC 95 % -32,2 a -8,2) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -4,2 (IC 95 % -9,6 a +1,2) | 4 de 5 | sin diferencia clara |
| Salidas por dos inasistencias | -1,6 (IC 95 % -4,6 a +1,4) | 3 de 5 | sin diferencia clara |
| Inasistencia realizada, consultas | 0,0 pp (IC 95 % -0,1 pp a +0,1 pp) | 3 de 5 | sin diferencia clara |
| Inasistencia realizada, cirugías | -0,2 pp (IC 95 % -0,5 pp a +0,1 pp) | 4 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | 0,0 pp (IC 95 % -0,1 pp a +0,1 pp) | 2 de 5 | sin diferencia clara |
| Utilización de pabellón | +0,4 pp (IC 95 % +0,2 pp a +0,6 pp) | 5 de 5 | mejora |
| Cupos de consulta perdidos | -2,2 (IC 95 % -10,3 a +5,9) | 3 de 5 | sin diferencia clara |
| Minutos de pabellón perdidos | -203,0 (IC 95 % -603,2 a +197,2) | 4 de 5 | sin diferencia clara |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |

#### Optimizada frente a Orden de llegada

Métricas que mejoran: 14; que empeoran: 2; sin diferencia clara: 3. Empeoran: Mediana de espera de la lista final (días); p90 de espera de la lista final (días).

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +86,8 (IC 95 % +71,0 a +102,6) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -61,4 (IC 95 % -62,5 a -60,3) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -31,6 (IC 95 % -35,6 a -27,6) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | +15,8 (IC 95 % +14,8 a +16,8) | 0 de 5 | empeora |
| p90 de espera de la lista final (días) | +66,5 (IC 95 % +64,7 a +68,3) | 0 de 5 | empeora |
| Tamaño final de la lista | -78,0 (IC 95 % -95,2 a -60,8) | 5 de 5 | mejora |
| GES atendidas a tiempo | +563,0 (IC 95 % +533,9 a +592,1) | 5 de 5 | mejora |
| GES incumplidas | -324,2 (IC 95 % -341,7 a -306,7) | 5 de 5 | mejora |
| GES vencidas al final | -352,6 (IC 95 % -375,3 a -329,9) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -338,4 (IC 95 % -359,7 a -317,1) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -8,8 (IC 95 % -14,6 a -3,0) | 5 de 5 | mejora |
| Inasistencia realizada, consultas | -0,6 pp (IC 95 % -0,8 pp a -0,4 pp) | 5 de 5 | mejora |
| Inasistencia realizada, cirugías | -0,7 pp (IC 95 % -1,3 pp a -0,2 pp) | 5 de 5 | mejora |
| Utilización de cupos de consulta | +0,5 pp (IC 95 % +0,3 pp a +0,7 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,4 pp (IC 95 % -0,1 pp a +0,9 pp) | 5 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -37,0 (IC 95 % -50,7 a -23,3) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -805,0 (IC 95 % -1.471,8 a -138,2) | 5 de 5 | mejora |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |

#### Solo prioridad frente a Orden de llegada

Métricas que mejoran: 12; que empeoran: 2; sin diferencia clara: 5. Empeoran: Mediana de espera de la lista final (días); p90 de espera de la lista final (días).

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +54,4 (IC 95 % +43,7 a +65,1) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -56,1 (IC 95 % -57,4 a -54,8) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -27,4 (IC 95 % -31,7 a -23,1) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | +15,8 (IC 95 % +14,8 a +16,8) | 0 de 5 | empeora |
| p90 de espera de la lista final (días) | +63,6 (IC 95 % +60,7 a +66,5) | 0 de 5 | empeora |
| Tamaño final de la lista | -47,2 (IC 95 % -59,0 a -35,4) | 5 de 5 | mejora |
| GES atendidas a tiempo | +360,4 (IC 95 % +333,0 a +387,8) | 5 de 5 | mejora |
| GES incumplidas | -157,4 (IC 95 % -164,2 a -150,6) | 5 de 5 | mejora |
| GES vencidas al final | -332,4 (IC 95 % -351,3 a -313,5) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -334,2 (IC 95 % -353,0 a -315,4) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -7,2 (IC 95 % -12,6 a -1,8) | 5 de 5 | mejora |
| Inasistencia realizada, consultas | -0,5 pp (IC 95 % -0,7 pp a -0,4 pp) | 5 de 5 | mejora |
| Inasistencia realizada, cirugías | -0,5 pp (IC 95 % -1,1 pp a +0,1 pp) | 4 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +0,5 pp (IC 95 % +0,3 pp a +0,6 pp) | 5 de 5 | mejora |
| Utilización de pabellón | 0,0 pp (IC 95 % -0,6 pp a +0,6 pp) | 1 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -34,8 (IC 95 % -44,9 a -24,7) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -602,0 (IC 95 % -1.370,8 a +166,8) | 4 de 5 | sin diferencia clara |
| Sesiones con desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Pacientes afectados por desborde | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |

#### Optimizada con sobrecupo frente a Solo prioridad

Métricas que mejoran: 11; que empeoran: 3; sin diferencia clara: 5. Empeoran: p90 de espera de la lista final (días); Sesiones con desborde; Pacientes afectados por desborde.

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +133,2 (IC 95 % +122,7 a +143,7) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -5,8 (IC 95 % -6,5 a -5,1) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -6,5 (IC 95 % -9,0 a -4,1) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | -0,6 (IC 95 % -1,3 a +0,1) | 3 de 5 | sin diferencia clara |
| p90 de espera de la lista final (días) | +2,5 (IC 95 % +1,2 a +3,8) | 0 de 5 | empeora |
| Tamaño final de la lista | -134,0 (IC 95 % -143,1 a -124,9) | 5 de 5 | mejora |
| GES atendidas a tiempo | +217,8 (IC 95 % +208,0 a +227,6) | 5 de 5 | mejora |
| GES incumplidas | -167,2 (IC 95 % -183,8 a -150,6) | 5 de 5 | mejora |
| GES vencidas al final | -20,4 (IC 95 % -32,6 a -8,2) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -23,6 (IC 95 % -33,7 a -13,5) | 5 de 5 | mejora |
| Salidas por dos inasistencias | +0,8 (IC 95 % -1,4 a +3,0) | 0 de 5 | sin diferencia clara |
| Inasistencia realizada, consultas | 0,0 pp (IC 95 % -0,1 pp a +0,1 pp) | 3 de 5 | sin diferencia clara |
| Inasistencia realizada, cirugías | -0,2 pp (IC 95 % -0,5 pp a +0,1 pp) | 4 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +1,1 pp (IC 95 % +1,0 pp a +1,2 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,4 pp (IC 95 % +0,2 pp a +0,6 pp) | 5 de 5 | mejora |
| Cupos de consulta perdidos | -93,6 (IC 95 % -100,3 a -86,9) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -203,0 (IC 95 % -603,2 a +197,2) | 4 de 5 | sin diferencia clara |
| Sesiones con desborde | +11,8 (IC 95 % +6,2 a +17,4) | 0 de 5 | empeora |
| Pacientes afectados por desborde | +153,4 (IC 95 % +80,0 a +226,8) | 0 de 5 | empeora |

#### Optimizada con sobrecupo frente a Orden de llegada

Métricas que mejoran: 14; que empeoran: 4; sin diferencia clara: 1. Empeoran: Mediana de espera de la lista final (días); p90 de espera de la lista final (días); Sesiones con desborde; Pacientes afectados por desborde.

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +187,6 (IC 95 % +173,5 a +201,7) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -61,9 (IC 95 % -62,6 a -61,2) | 5 de 5 | mejora |
| p90 de espera de los atendidos (días) | -34,0 (IC 95 % -37,8 a -30,1) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | +15,2 (IC 95 % +14,2 a +16,2) | 0 de 5 | empeora |
| p90 de espera de la lista final (días) | +66,1 (IC 95 % +64,2 a +68,0) | 0 de 5 | empeora |
| Tamaño final de la lista | -181,2 (IC 95 % -197,5 a -164,9) | 5 de 5 | mejora |
| GES atendidas a tiempo | +578,2 (IC 95 % +546,3 a +610,1) | 5 de 5 | mejora |
| GES incumplidas | -324,6 (IC 95 % -342,6 a -306,6) | 5 de 5 | mejora |
| GES vencidas al final | -352,8 (IC 95 % -375,7 a -329,9) | 5 de 5 | mejora |
| Llegadas sin cupo en el horizonte del plan | -357,8 (IC 95 % -382,3 a -333,3) | 5 de 5 | mejora |
| Salidas por dos inasistencias | -6,4 (IC 95 % -10,1 a -2,7) | 5 de 5 | mejora |
| Inasistencia realizada, consultas | -0,5 pp (IC 95 % -0,7 pp a -0,4 pp) | 5 de 5 | mejora |
| Inasistencia realizada, cirugías | -0,7 pp (IC 95 % -1,3 pp a -0,2 pp) | 5 de 5 | mejora |
| Utilización de cupos de consulta | +1,6 pp (IC 95 % +1,4 pp a +1,7 pp) | 5 de 5 | mejora |
| Utilización de pabellón | +0,4 pp (IC 95 % -0,1 pp a +0,9 pp) | 5 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -128,4 (IC 95 % -141,0 a -115,8) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | -805,0 (IC 95 % -1.471,8 a -138,2) | 5 de 5 | mejora |
| Sesiones con desborde | +11,8 (IC 95 % +6,2 a +17,4) | 0 de 5 | empeora |
| Pacientes afectados por desborde | +153,4 (IC 95 % +80,0 a +226,8) | 0 de 5 | empeora |

#### Optimizada con sobrecupo frente a Optimizada

Métricas que mejoran: 7; que empeoran: 2; sin diferencia clara: 10. Empeoran: Sesiones con desborde; Pacientes afectados por desborde.

| Métrica | Diferencia media | Réplicas en que mejora | Lectura |
|---|---:|---:|---|
| Pacientes atendidos | +100,8 (IC 95 % +94,8 a +106,8) | 5 de 5 | mejora |
| Mediana de espera de los atendidos (días) | -0,5 (IC 95 % -1,1 a +0,1) | 3 de 5 | sin diferencia clara |
| p90 de espera de los atendidos (días) | -2,4 (IC 95 % -3,4 a -1,4) | 5 de 5 | mejora |
| Mediana de espera de la lista final (días) | -0,6 (IC 95 % -1,3 a +0,1) | 3 de 5 | sin diferencia clara |
| p90 de espera de la lista final (días) | -0,4 (IC 95 % -1,0 a +0,1) | 3 de 5 | sin diferencia clara |
| Tamaño final de la lista | -103,2 (IC 95 % -108,1 a -98,3) | 5 de 5 | mejora |
| GES atendidas a tiempo | +15,2 (IC 95 % +9,2 a +21,2) | 5 de 5 | mejora |
| GES incumplidas | -0,4 (IC 95 % -1,5 a +0,7) | 1 de 5 | sin diferencia clara |
| GES vencidas al final | -0,2 (IC 95 % -0,8 a +0,4) | 1 de 5 | sin diferencia clara |
| Llegadas sin cupo en el horizonte del plan | -19,4 (IC 95 % -26,6 a -12,2) | 5 de 5 | mejora |
| Salidas por dos inasistencias | +2,4 (IC 95 % 0,0 a +4,8) | 0 de 5 | sin diferencia clara |
| Inasistencia realizada, consultas | 0,0 pp (IC 95 % 0,0 pp a +0,1 pp) | 1 de 5 | sin diferencia clara |
| Inasistencia realizada, cirugías | 0,0 pp (IC 95 % 0,0 pp a 0,0 pp) | 0 de 5 | sin diferencia clara |
| Utilización de cupos de consulta | +1,1 pp (IC 95 % +1,0 pp a +1,2 pp) | 5 de 5 | mejora |
| Utilización de pabellón | 0,0 pp (IC 95 % 0,0 pp a 0,0 pp) | 0 de 5 | sin diferencia clara |
| Cupos de consulta perdidos | -91,4 (IC 95 % -95,8 a -87,0) | 5 de 5 | mejora |
| Minutos de pabellón perdidos | 0,0 (IC 95 % 0,0 a 0,0) | 0 de 5 | sin diferencia clara |
| Sesiones con desborde | +11,8 (IC 95 % +6,2 a +17,4) | 0 de 5 | empeora |
| Pacientes afectados por desborde | +153,4 (IC 95 % +80,0 a +226,8) | 0 de 5 | empeora |

### Cobertura de la oferta

Algunas combinaciones de servicio y especialidad (celdas) no reciben ningún bloque de oferta en el periodo simulado, lo que deja parte del stock sin posibilidad de ser atendido: ninguna política puede programar citas en cupos que no existen. La tabla muestra la cobertura de la oferta sintética: qué fracción del stock cae en celdas que reciben al menos un bloque.

| Tipo de atención | Bloques de oferta | Celdas | Celdas con algún bloque | Stock | Stock en celdas con bloque |
|---|---:|---:|---:|---:|---:|
| Consulta nueva de especialidad | 674 | 1.246 | 466 (37,4 %) | 8.559 | 6.537 (76,4 %) |
| Intervención quirúrgica | 423 | 304 | 219 (72,0 %) | 1.441 | 1.293 (89,7 %) |

### Programador dentro de la simulación

| Política | Planes semanales | Estados del solver por fase | Brecha máxima | Tiempo de pared del solver (s) |
|---|---:|---|---:|---:|
| Orden de llegada | 130 | no usa el solver | no aplica | 0,0 |
| Solo prioridad | 130 | no usa el solver | no aplica | 0,0 |
| Optimizada | 130 | 1: OPTIMAL 6.235; 2: OPTIMAL 4.269; 3a: OPTIMAL 16.990; 4: OPTIMAL 200 | 0,006 % | 4,5 |
| Optimizada con sobrecupo | 130 | 1: OPTIMAL 6.241; 2: OPTIMAL 4.264; 3a: OPTIMAL 17.026; 3b: OPTIMAL 3.523; 4: OPTIMAL 200 | 0,019 % | 8,1 |

Tiempo de simulación por política:

| Política | Media por réplica (s) | Total (s) |
|---|---:|---:|
| Orden de llegada | 15,6 | 78,0 |
| Solo prioridad | 15,6 | 78,1 |
| Optimizada | 19,4 | 96,9 |
| Optimizada con sobrecupo | 21,9 | 109,6 |

## Equidad

Se miden desigualdades por comuna, grupo etario y previsión en el programador y la simulación: exposición al sobrecupo (proporción de citas en cupos con overbooking), tasa de atención (agendadas sobre entradas) y mediana de espera. Brechas se calculan contra el total ponderado por entradas; la comuna del sintético es un atributo del paciente sin correlato económico o de distancia, por lo que no tiene efecto causal propio. Se nombran sin suavizar los grupos más expuestos o que quedan en desventaja frente a otros: el informe no filtra resultados por signo.

### Plan canónico

Referencia (todas las entradas):

| Política | Tasa de agendamiento | Exposición al sobrecupo | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|
| Orden de llegada | 13,17 % | 0,0 % | 0,0 % | 0,0 % |
| Solo prioridad | 13,17 % | 0,0 % | 0,0 % | 0,0 % |
| Optimizada | 13,62 % | 36,5 % | 2,8 % | 7,6 % |

La exposición al sobrecupo es la proporción de las citas de consulta agendadas que caen en un bloque con sobrecupo; la tasa de agendamiento es agendadas sobre entradas del grupo. Se listan grupos con al menos 30 entradas.

#### age_group

Grupo más expuesto al sobrecupo: 0-14 (41,4 %, +4,9 pp respecto del total, 10.751 entradas). Mayor desvío de exposición respecto del total: 0-14 (+4,9 pp). Mayor desvío de la tasa de agendamiento de la optimizada respecto del total: -0,34 pp (15-19). Grupos donde la optimizada agenda menos que solo prioridad: 0 de 5; peor caso: 65+ (+0,34 pp). 5 grupos evaluados de 5.

| Grupo | Entradas | Agendamiento, orden de llegada | Agendamiento, solo prioridad | Agendamiento, optimizada | Δ optimizada contra solo prioridad | Exposición al sobrecupo | Desvío de exposición | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-14 | 10.751 | 13,08 % | 13,10 % | 13,45 % | +0,35 pp | 41,4 % | +4,9 pp | 3,9 % | 5,7 % |
| 15-19 | 4.340 | 12,95 % | 12,58 % | 13,27 % | +0,69 pp | 36,7 % | +0,2 pp | 2,9 % | 7,2 % |
| 20-44 | 23.586 | 13,13 % | 13,28 % | 13,65 % | +0,36 pp | 35,8 % | -0,7 pp | 2,9 % | 7,9 % |
| 45-64 | 31.133 | 13,18 % | 13,29 % | 13,90 % | +0,61 pp | 35,2 % | -1,3 pp | 2,6 % | 7,9 % |
| 65+ | 30.190 | 13,26 % | 13,06 % | 13,41 % | +0,34 pp | 36,6 % | +0,1 pp | 2,5 % | 8,0 % |

#### insurance

Grupo más expuesto al sobrecupo: fonasa c (37,4 %, +0,9 pp respecto del total, 15.030 entradas). Mayor desvío de exposición respecto del total: other (-1,5 pp). Mayor desvío de la tasa de agendamiento de la optimizada respecto del total: -0,22 pp (fonasa d). Grupos donde la optimizada agenda menos que solo prioridad: 0 de 5; peor caso: fonasa d (+0,34 pp). 5 grupos evaluados de 5.

| Grupo | Entradas | Agendamiento, orden de llegada | Agendamiento, solo prioridad | Agendamiento, optimizada | Δ optimizada contra solo prioridad | Exposición al sobrecupo | Desvío de exposición | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fonasa a | 18.435 | 13,06 % | 13,07 % | 13,56 % | +0,48 pp | 35,3 % | -1,2 pp | 2,8 % | 7,6 % |
| fonasa b | 38.982 | 13,17 % | 13,38 % | 13,83 % | +0,45 pp | 36,9 % | +0,4 pp | 2,8 % | 7,6 % |
| fonasa c | 15.030 | 13,07 % | 12,87 % | 13,41 % | +0,55 pp | 37,4 % | +0,9 pp | 3,1 % | 7,7 % |
| fonasa d | 21.487 | 13,28 % | 13,05 % | 13,39 % | +0,34 pp | 36,6 % | +0,1 pp | 2,6 % | 7,7 % |
| other | 6.066 | 13,35 % | 13,24 % | 13,68 % | +0,45 pp | 35,0 % | -1,5 pp | 2,8 % | 7,5 % |

#### commune_code

Grupo más expuesto al sobrecupo: 16305 (75,0 %, +38,5 pp respecto del total, 91 entradas). Mayor desvío de exposición respecto del total: 16305 (+38,5 pp). Mayor desvío de la tasa de agendamiento de la optimizada respecto del total: +13,66 pp (08109). Grupos donde la optimizada agenda menos que solo prioridad: 53 de 313; peor caso: 13203 (-4,17 pp). 313 grupos evaluados de 338.

Se listan los 10 grupos más expuestos.

| Grupo | Entradas | Agendamiento, orden de llegada | Agendamiento, solo prioridad | Agendamiento, optimizada | Δ optimizada contra solo prioridad | Exposición al sobrecupo | Desvío de exposición | Citas marcadas | Riesgo medio de los expuestos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 16305 | 91 | 4,40 % | 7,69 % | 5,49 % | -2,20 pp | 75,0 % | +38,5 pp | 0,0 % | 8,3 % |
| 03202 | 62 | 11,29 % | 9,68 % | 11,29 % | +1,61 pp | 71,4 % | +34,9 pp | 14,3 % | 4,8 % |
| 01403 | 320 | 5,63 % | 8,75 % | 8,75 % | 0,00 pp | 70,4 % | +33,9 pp | 3,7 % | 9,5 % |
| 10304 | 141 | 12,77 % | 7,09 % | 8,51 % | +1,42 pp | 70,0 % | +33,5 pp | 20,0 % | 9,3 % |
| 09202 | 104 | 10,58 % | 6,73 % | 6,73 % | 0,00 pp | 66,7 % | +30,2 pp | 0,0 % | 5,6 % |
| 09207 | 188 | 6,91 % | 9,04 % | 9,04 % | 0,00 pp | 66,7 % | +30,2 pp | 0,0 % | 5,7 % |
| 16207 | 108 | 6,48 % | 9,26 % | 10,19 % | +0,93 pp | 66,7 % | +30,2 pp | 0,0 % | 8,4 % |
| 01107 | 565 | 9,03 % | 7,26 % | 8,14 % | +0,88 pp | 62,5 % | +26,0 pp | 7,5 % | 9,6 % |
| 14203 | 165 | 18,18 % | 13,94 % | 16,36 % | +2,42 pp | 62,5 % | +26,0 pp | 8,3 % | 7,9 % |
| 14204 | 136 | 11,76 % | 17,65 % | 19,85 % | +2,21 pp | 60,9 % | +24,4 pp | 0,0 % | 6,6 % |

### Simulación

Medias entre 5 réplicas, población de 10.000 entradas. La exposición al sobrecupo es la proporción de citas en sesiones con sobrecupo. Las brechas son contra el total de la dimensión ponderado por entradas.

#### age_group

Grupo más expuesto al sobrecupo (Optimizada con sobrecupo): 0-14 (26,9 %, +3,2 pp respecto del total, 1.827 entradas). 5 grupos evaluados.

| Política | Mayor desvío de la tasa de atención | Grupo | Menor tasa de atención | Grupo | Mayor desvío de la exposición | Grupo |
|---|---:|---|---:|---|---:|---|
| Orden de llegada | -5,5 pp | 0-14 | 30,8 % | 0-14 | 0,0 pp | ninguno |
| Solo prioridad | -6,8 pp | 0-14 | 29,7 % | 0-14 | 0,0 pp | ninguno |
| Optimizada | -6,6 pp | 0-14 | 30,1 % | 0-14 | 0,0 pp | ninguno |
| Optimizada con sobrecupo | -6,6 pp | 0-14 | 30,6 % | 0-14 | +3,2 pp | 0-14 |

| Grupo | Entradas | Atención, Orden de llegada | Atención, Solo prioridad | Atención, Optimizada | Atención, Optimizada con sobrecupo | Exposición al sobrecupo | Mediana de espera de atendidos, Optimizada con sobrecupo | GES incumplidas, Optimizada con sobrecupo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-14 | 1.827 | 30,8 % | 29,7 % | 30,1 % | 30,6 % | 26,9 % | 311,8 | 85,6 |
| 15-19 | 751 | 34,6 % | 34,1 % | 34,9 % | 35,5 % | 23,4 % | 316,8 | 27,8 |
| 20-44 | 4.224 | 36,0 % | 36,1 % | 36,3 % | 36,8 % | 23,1 % | 292,8 | 252,4 |
| 45-64 | 5.541 | 37,2 % | 37,5 % | 37,6 % | 38,2 % | 23,5 % | 291,8 | 308,6 |
| 65+ | 5.403 | 37,5 % | 38,5 % | 38,6 % | 39,3 % | 23,3 % | 290,7 | 359,8 |

#### insurance

Grupo más expuesto al sobrecupo (Optimizada con sobrecupo): fonasa c (24,9 %, +1,3 pp respecto del total, 2.641 entradas). 5 grupos evaluados.

| Política | Mayor desvío de la tasa de atención | Grupo | Menor tasa de atención | Grupo | Mayor desvío de la exposición | Grupo |
|---|---:|---|---:|---|---:|---|
| Orden de llegada | +1,7 pp | other | 35,9 % | fonasa c | 0,0 pp | ninguno |
| Solo prioridad | -1,5 pp | fonasa c | 35,1 % | fonasa c | 0,0 pp | ninguno |
| Optimizada | -1,4 pp | fonasa c | 35,3 % | fonasa c | 0,0 pp | ninguno |
| Optimizada con sobrecupo | -1,3 pp | fonasa c | 36,0 % | fonasa c | +1,3 pp | fonasa c |

| Grupo | Entradas | Atención, Orden de llegada | Atención, Solo prioridad | Atención, Optimizada | Atención, Optimizada con sobrecupo | Exposición al sobrecupo | Mediana de espera de atendidos, Optimizada con sobrecupo | GES incumplidas, Optimizada con sobrecupo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fonasa a | 3.308 | 36,3 % | 36,7 % | 36,8 % | 37,4 % | 23,3 % | 289,3 | 196,6 |
| fonasa b | 6.918 | 35,9 % | 36,4 % | 36,6 % | 37,1 % | 23,6 % | 295,4 | 412,0 |
| fonasa c | 2.641 | 35,9 % | 35,1 % | 35,3 % | 36,0 % | 24,9 % | 300,5 | 133,0 |
| fonasa d | 3.835 | 36,6 % | 37,5 % | 37,7 % | 38,2 % | 23,3 % | 292,4 | 254,2 |
| other | 1.044 | 37,9 % | 36,9 % | 37,7 % | 38,0 % | 22,9 % | 306,9 | 38,4 |

#### commune_code

Grupo más expuesto al sobrecupo (Optimizada con sobrecupo): 05503 (53,8 %, +30,9 pp respecto del total, 49 entradas). 156 grupos evaluados.

| Política | Mayor desvío de la tasa de atención | Grupo | Menor tasa de atención | Grupo | Mayor desvío de la exposición | Grupo |
|---|---:|---|---:|---|---:|---|
| Orden de llegada | -21,4 pp | 10202 | 15,6 % | 10202 | 0,0 pp | ninguno |
| Solo prioridad | +27,4 pp | 07307 | 16,7 % | 10202 | 0,0 pp | ninguno |
| Optimizada | +28,4 pp | 07307 | 16,7 % | 10202 | 0,0 pp | ninguno |
| Optimizada con sobrecupo | +27,1 pp | 07307 | 16,7 % | 10202 | +30,9 pp | 05503 |

Se listan los 10 grupos más expuestos al sobrecupo.

| Grupo | Entradas | Atención, Orden de llegada | Atención, Solo prioridad | Atención, Optimizada | Atención, Optimizada con sobrecupo | Exposición al sobrecupo | Mediana de espera de atendidos, Optimizada con sobrecupo | GES incumplidas, Optimizada con sobrecupo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 05503 | 49 | 25,9 % | 33,6 % | 34,8 % | 36,9 % | 53,8 % | 167,9 | 6,2 |
| 04204 | 43 | 44,7 % | 44,7 % | 45,6 % | 47,4 % | 52,0 % | 340,5 | 0,0 |
| 10106 | 36 | 37,3 % | 36,3 % | 35,2 % | 35,8 % | 51,5 % | 307,5 | 2,4 |
| 07402 | 37 | 39,3 % | 54,3 % | 55,7 % | 55,7 % | 50,2 % | 123,4 | 2,0 |
| 06111 | 59 | 30,3 % | 39,7 % | 41,1 % | 42,8 % | 46,4 % | 79,2 | 8,8 |
| 13502 | 39 | 36,3 % | 33,9 % | 38,0 % | 38,7 % | 45,0 % | 220,7 | 0,4 |
| 09111 | 73 | 30,2 % | 40,9 % | 42,6 % | 42,6 % | 43,0 % | 272,8 | 2,4 |
| 04301 | 194 | 36,5 % | 38,6 % | 38,3 % | 39,0 % | 42,9 % | 381,0 | 11,4 |
| 06108 | 38 | 44,0 % | 37,1 % | 37,1 % | 38,2 % | 42,5 % | 362,5 | 4,2 |
| 04305 | 35 | 39,4 % | 38,7 % | 36,4 % | 38,0 % | 41,0 % | 383,5 | 1,2 |

## Limitaciones

Los datos son sintéticos, calibrados a agregados públicos pero no derivados de ellos. Las conclusiones del informe valen únicamente para el mundo simulado: no son extrapolables a la red de salud real sin validación institucional e implementación cuidadosa. El sistema apoya la decisión pero no la toma; no hay validación clínica de los supuestos ni autorización de cambios en política de atención. Varios parámetros del generador (distribuciones de espera, composición por edad y previsión, tasas de inasistencia sintéticas) se derivan de datos públicos agregados pero no se comparan directamente con la realidad celda a celda; otros no tienen fuente pública y se listan abajo como supuestos sin verificar.

Supuestos del generador sin verificar con una fuente pública: 53 de 58.

- `capacity_multiplier`
- `cne_session_min`
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

- candidate_frontier_reached en 96 colas
- candidate_frontier_reached persiste tras duplicar el margen en 14 colas
- lead_extrapolation: 139 citas con aviso fuera de 7-90 días; su p extrapola el modelo de inasistencias

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
| `noshow.json` | sin marca de tiempo | noshow-4f0429cd-3ba6e988 | 1 | 42 |
| `schedule_32c9e349-74f9-5c85-bf4b-990796b47323_4w.json` | sin marca de tiempo | scheduler-0.1.0 | 1 | 42 |
| `scheduler-benchmark.json` | 09-10-2026 | scheduler-0.1.0 | 6 | 42 |
| `simulation.json` | 09-10-2026 | simulation-0.1.0 | 1 | 42 |

Último commit que modificó `results/`: `a71be63a1bc5ee7d9998c6aa3845741aa0a3ed78`.

Este informe se genera con `prioriza-report` y es determinista: con los mismos resultados produce los mismos bytes, sin hora de generación.
