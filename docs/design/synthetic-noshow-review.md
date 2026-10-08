# Revisión del generador de inasistencias sintéticas (ml-engineer, 2026-10-08)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Revisión de solo lectura sobre `synthetic/` previa a P4 (modelo de inasistencias). Estado de cada hallazgo al final.

El proceso generador está implementado como dice el plan y los interceptos quedan calibrados. Pero hay un error que falsea los análisis de sensibilidad. Además, el historial observable no permite aprender los efectos de especialidad ni de espera. Y con k ~ Poisson(1,5) casi toda la señal está en u_i, que un modelo no puede recuperar.

No edité nada del repo ni hice commits. Los scripts de análisis están en el scratchpad (`analyze.py` y `ceiling.py`). Usé scikit-learn 1.9.1 cargado desde la caché de uv, porque `noshow/` todavía no lo declara como dependencia.

**1. Proceso generador (pregunta 1)**
- El logit coincide con la sección 2 del plan (`noshow_truth.py:158-177`).
- Los escenarios coinciden con `assumptions.json`. En `baseline`, β_ins = 0 en las 5 categorías. `neutral` deja β_wait y β_lead activos, como pide el plan.
- La bisección (±40, 100 iteraciones) converge. C6.media_p pasa en los 3 escenarios con N = 20.000 y N = 100.000: 58 grupos (servicio, tipo), todos con error menor a 1e-4. El informe de calibración completo pasa (`passed = True`); C5.nacional.mediana falla, pero es un aviso blando previsto (el nacional incluye problemas GES no mapeados).

**Cifras de AUC (N = 20.000, seed 42; test temporal = últimos 183 días del historial, 6.356 citas, error estándar ~0,01)**

| | baseline | neutral | ses_gradient |
|---|---|---|---|
| Oráculo, historial (p verdadera) | 0,741 | 0,723 | 0,740 |
| Oráculo, citas futuras simuladas (1 por entrada) | 0,753 | 0,737 | 0,753 |
| Oráculo sin u_i (solo la estructura) | 0,646 | 0,601 | 0,648 |
| Cota bayesiana: estructura exacta + E[u \| historial] | 0,649 | 0,619 | – |
| Regresión logística, sin historial (test temporal) | 0,613 | 0,570 | 0,613 |
| Regresión logística, con historial previo (test temporal) | 0,630 | 0,603 | 0,631 |
| Gradient boosting, con historial previo | 0,615 | 0,596 | 0,626 |
| Regresión logística entrenada en historial y aplicada a citas futuras | 0,634 | 0,610 | 0,634 |
| Regresión logística con especialidad + espera (sobre citas futuras simuladas) | 0,647 | 0,609 | 0,647 |

Solo u_i ya da AUC 0,696. Si se aumenta λ en la cota bayesiana, el AUC sube así: λ = 1,5 → 0,648; λ = 3 → 0,661; λ = 6 → 0,680; λ = 12 → 0,695.

**Conclusión sobre la pregunta 2: el problema se puede aprender, pero el techo práctico está en AUC 0,63-0,65.** Hay unos 0,10 de AUC (frente al oráculo) que ningún modelo con variables observables puede recuperar.

## ALTO

**A1. `noshow_truth.py:301-302`: `generate_history` ignora los `targets` y `assumptions` que recibe.** Llama a `load_targets()` y `load_assumptions()` internamente.
- Lo comprobé: con `history_poisson_lambda = 4` pasado a `generate(...)`, `params_sha256` cambia (caed1216 → acb01194), pero el historial queda idéntico (6.406 citas en ambos casos).
- Consecuencia: los análisis de sensibilidad (λ, ventana, rango de anticipación) quedan registrados con parámetros que en realidad no se usaron.
- Corrección: agregar `t` y `a` a la firma, pasarlos desde `pipeline.py:77` y añadir un test que compruebe que cambiar λ cambia el número de citas.

**A2. Con el historial no se pueden aprender ni la especialidad ni la espera** (`noshow_truth.py:346-356` pone el término de espera en 0; `:373` deja `entry_id = None`; `appointment` no tiene `specialty_code`).
- γ_spec (desviación estándar 0,3) y β_wait no se pueden identificar desde los datos observables. Las citas futuras sí dependen de ellos.
- Sesgo del modelo entrenado en historial al aplicarlo a citas futuras (predicción menos verdad):
  - Por especialidad: entre −8,7 y +7,4 pp; sesgo absoluto medio de 2,1 pp.
  - Por quintil de espera: +2,7 pp en el quintil de menor espera y −2,6 pp en el de mayor espera.
  - GES: +2,7 pp.
- Ese sesgo está correlacionado con la espera. El sobreagendamiento recaerá entonces en quienes esperan poco y se subestimará en quienes esperan mucho y en GES.
- Corrección (requiere cambio de esquema, a decidir con architect):
  - Agregar `specialty_code` y `wait_days_at_appointment` a la cita del historial, o generar entradas pasadas resueltas y enlazarlas por `entry_id`.
  - Calcular el término de espera con la espera real a la fecha de la cita, no con 0.

**A3. Casi toda la señal está en u_i y el historial no basta para estimarla.**
- Con σ_u = 0,8 y k ~ Poisson(1,5), el 22 % de los pacientes no tiene historial (k medio 1,49). El historial aporta solo +0,017 de AUC en baseline y +0,03 en neutral.
- El historial completo, incluido lo posterior a la cita evaluada (una fuga deliberada, solo como referencia), no mejora: 0,631.
- Riesgo: las probabilidades predichas quedan comprimidas, y la política optimizada podría no diferenciarse de sobreagendar con una tasa uniforme por servicio. Hay que reportarlo así.
- Corrección: decidir explícitamente con architect. Opciones: subir λ (con 3-6 la cota pasa a 0,66-0,68) o ampliar la ventana. Además, documentar en el informe el techo de AUC 0,65 y la brecha de 0,10 frente al oráculo.

## MEDIO

**M1. La verdad sintética se separa solo con un comentario.**
- `patient_latent` y `appointment_truth` quedan en el mismo esquema y en el mismo directorio parquet (`io.py:30-33`).
- `synthetic_run.params` y `manifest.json` exponen γ por especialidad, β e interceptos.
- No encontré ninguna columna observable derivada de u o p, salvo `status`, que es la etiqueta legítima.
- Corrección: separar un esquema o rol `truth`, usar en `noshow/` una lista explícita de tablas permitidas y agregar un test que falle si el código de features lee esas tablas o `params`.

**M2. Los interceptos se calibran mezclando GES y no GES** (`noshow_truth.py:274`).
- La media de p de las entradas CNE no GES se desvía entre −0,50 y +0,74 pp de la tasa objetivo por servicio. El 6 % de las CNE y el 10 % de las IQ son GES.
- La calibración se hace sobre los u ya sorteados en la muestra, no sobre la distribución poblacional. Por eso C6.media_p (`validate.py:529-538`) es tautológico: comprueba sobre la misma muestra exactamente lo que la bisección ya ajustó.
- Corrección: definir si t_{s,c} incluye GES y, si no, calibrar solo sobre no GES. Agregar un chequeo C6 con un sorteo independiente de u.

**M3. Poder estadístico para la equidad (pregunta 3).**
- Se puede medir por grupo etario y por previsión. En `ses_gradient`, el modelo sin previsión predice 15,0 % para fonasa_a cuando la verdad es 16,5 %, y 14,6 % para fonasa_d cuando la verdad es 12,9 %. Se detecta contra `appointment_truth`; contra las tasas realizadas el ruido es de ~0,6 pp por grupo.
- Por comuna, con N = 20.000: 338 comunas, mediana de 36 entradas, solo 18 con 200 o más y 136 con menos de 30. Necesita N = 100.000, un mínimo de n por comuna y estimadores agrupados o con contracción hacia la media del grupo.
- La comuna determina el servicio por completo (V de Cramér = 1,0), y el generador no tiene ningún efecto propio de comuna. Un análisis por comuna saldrá "sin daño" por construcción. Sugiero un escenario con un efecto por comuna oculto al modelo, para medir si el análisis detecta daño cuando sí existe.
- Falta decidir si el modelo puede usar `age_group`. CLAUDE.md no lo prohíbe y el generador lo usa, pero usarlo concentra el sobreagendamiento en 15-44 años. Debe quedar en `docs/decisions.md`.

**M4. Split temporal (pregunta 4).**
- Es factible: el historial cubre 730 días uniformes; con corte a 183 días quedan 18.976 citas de entrenamiento y 6.356 de test.
- Pero el proceso es estacionario (sin deriva ni estacionalidad, u constante). Un split temporal equivale estadísticamente a uno aleatorio y no prueba robustez.
- Las fechas del historial son independientes de `entry_date`: por la mediana de espera de 242 días, estimo que alrededor de la mitad de las citas quedan antes del ingreso a la lista (no lo medí).
- Hay 40 pares de citas del mismo paciente el mismo día. Las variables de historial deben usar desigualdad estricta en la fecha.
- Falta guardar la fecha de agendamiento (hoy hay que derivarla como `scheduled_start − lead_days`). También falta, de forma opcional, un parámetro de deriva temporal. Y no hay etiquetas posteriores a `as_of` hasta que exista la simulación.

## BAJO

**B1. `validate.py:599-617` compara peras con manzanas.** Compara la tasa del historial (CNE + IQ, 14,85 %) con el objetivo solo de CNE. Si se filtra CNE usando duración = 20, la tasa es 16,6 %, con anticipación media de 48 días frente a la referencia de 28. Corrección: filtrar por tipo de atención.

**B2. `duration_min` delata el procedimiento solo en IQ.** En CNE todas las citas duran 20 minutos. No es una fuga de la verdad, pero da una pista asimétrica de especialidad (10 duraciones distintas). Mejor resolverlo con A2 que como variable.

**B3. Aviso C9 de E[p²].** E[p²] en CNE es 3,8 %, frente al objetivo de 3,0 %. Pasa la tolerancia blanda, pero σ_u = 0,8 está en el límite alto. Subir σ_u para mejorar el punto A3 empeoraría este chequeo.

**B4. Proxies.**
- En los datos sintéticos, la previsión es independiente de la edad (V = 0,017) y del servicio (V = 0,036). No hay proxies dentro del sintético.
- En datos reales sí habría:
  - La especialidad delata el sexo: ginecología y obstetricia, urología, mama.
  - El servicio y la comuna delatan etnia y nacionalidad: Arica, Iquique, Araucanía.
  - Las especialidades pediátricas determinan la edad.
- Recomiendo excluir comuna y previsión, permitir el servicio solo como efecto fijo y documentarlo en `docs/decisions.md`.
## Estado de los hallazgos (2026-10-08)

| Hallazgo | Estado |
|---|---|
| A1 `generate_history` ignora targets/assumptions | Corregido, con test de regresión |
| A2 historial sin especialidad ni espera | Parcial: `appointment.specialty_code` (migración 0004) se llena en el historial; el término de espera sigue en 0 (diferido a P4) |
| A3 techo de AUC ~0,63-0,65 | Diferido a P4 (decisión sobre λ del historial y ventana) |
| M1 separación técnica de la verdad sintética | Diferido a P4 (lista de tablas permitidas y test en `noshow/`) |
| M2 C6 tautológico | Corregido: nuevo chequeo estricto con sorteo independiente de la fragilidad |
| M3 poder estadístico por comuna; uso de `age_group` | Diferido a P4 |
| M4 split temporal en proceso estacionario | Diferido a P4 |
| B1 tasa del historial CNE+IQ vs objetivo CNE | Corregido: comparación separada por tipo |
| B2, B3, B4 | Documentados; sin cambios |
