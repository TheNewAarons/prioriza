# Limitaciones

> **Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.**

Los datos son sintéticos, calibrados a agregados públicos pero no derivados directamente de ellos. Las conclusiones de Prioriza valen únicamente para el mundo simulado: no son extrapolables a la red de salud real sin validación institucional, implementación cuidadosa y revisión clínica completa. El sistema apoya la decisión pero no la toma; no hay autorización de cambios en política de atención.

## Datos y calibración

### Población sintética (`synthetic/`)

- **Supuestos sin fuente pública**: 53 de 58 supuestos del generador no se verifican con una fuente pública. La lista está en `docs/results.md` § Limitaciones.
- **Chequeos por construcción**: la mayoría de los chequeos estrictos de calibración verifica lo que el generador impone por construcción; sirven para detectar errores de implementación, no para validar la población contra la realidad. De los contrastes que no salen por construcción, la mediana GES nacional falla (76 vs 71 días) y la tasa del historial CNE queda 0,76 pp sobre el objetivo.
- **Sin sexo, etnia ni nacionalidad**: el generador no produce esos atributos protegidos.
- **Horizonte de la oferta**: el generador produce oferta para 26 semanas; la simulación genera su propia oferta estacionaria para las semanas siguientes.

Fuente: `docs/synthetic-data.md` § Alcance de los chequeos estrictos, `docs/results.md` § Limitaciones.

### Calibración fallida a tamaño chico

Con 100.000 entradas pasan los 26 chequeos estrictos. Con 1.000 (la demo con `--size 1000`, semilla 42) fallan 2 de 23: la mediana de espera de intervenciones quirúrgicas (284,5 vs 264 días) y la media GES de los problemas mapeados. El generador sale con código 1 pero igual escribe la corrida, y `scripts/demo.sh` sigue con un aviso.

Fuente: `docs/synthetic-data.md` § Resultado global, `scripts/demo.sh` (paso 2).

## Modelo de inasistencias (`noshow/`)

- **Desempeño acotado**: AUC 0,625; la probabilidad verdadera del generador alcanza 0,737. La brecha viene en parte de las variables excluidas por equidad (servicio, comuna, edad), que el generador sí usa. **Aprende solo la estructura que el generador puso**, no fenómenos reales de inasistencia.
- **Variables excluidas** (no están disponibles o son proxies de atributos protegidos):
  - Edad: incluirla concentraría el sobreagendamiento en 15-44 años (hallazgo M3 de la revisión del generador); se usa solo para medir equidad.
  - Previsión y comuna: proxies de nivel socioeconómico; se usan solo para medir equidad.
  - Sexo, etnia, nacionalidad: atributos protegidos; no existen en los datos.
  - `health_service_code`: determinado por comuna (V de Cramér = 1 sintético); mismo proxy geográfico que la comuna.
  - Duración y procedimiento: redundantes con la especialidad; la duración delata el tipo de intervención (hallazgo B2).
  - Días de espera (`wait_days`): permitida, pero el generador fija el término de espera en 0 en el historial, así que hoy no aporta.
- **Brechas por servicio y comuna**: el modelo subestima la inasistencia de Arica e Iquique (−4,94 y −4,29 pp contra la verdad) porque no ve el servicio, y la de la comuna 15101 (−5,11 pp, servicio de Arica). En esos lugares se sobreagendaría menos de lo que la inasistencia real justifica.
- **Sin reentrenamiento en la simulación**: el modelo se entrena una vez sobre el historial sintético y no se reentrena durante la simulación.

Fuente: `docs/noshow-model-card.md`, `docs/results.md` § Modelo de inasistencias.

## Programador (`scheduler/`)

- **Candidatos acotados por cola**: el programador considera solo los mejores candidatos de cada cola. En el plan canónico el filtro pudo ser activo en 96 colas; se duplicó el margen y en 14 siguió activo, así que puede haber asignaciones mejores fuera de los candidatos.
- **Sin presupuesto de tiempo global**: `time_limit_s` (120 s) es por pasada, no por plan. Con la expansión de frontera el total lo supera: la política optimizada tardó 163,5 s reales en el plan canónico (las voraces, 2,2-2,6 s).
- **Optimalidad no probada en todo**: en la fase 3a, 4 de 159 subproblemas terminan `FEASIBLE`, con brecha agregada de 2,06 %; en la fase 3b, 16 `FEASIBLE` y 21 `UNKNOWN`.
- **Extrapolación de la probabilidad**: 139 citas del plan canónico tienen un aviso fuera del rango del historial (7-90 días); su probabilidad extrapola el modelo de inasistencias.
- **Solo dentro del mismo servicio de salud** (`match_level = health_service`): no se modelan derivaciones entre servicios.

Fuente: `docs/scheduler-formulation.md` § 11.3, `docs/results.md` § Programador.

### Artefacto: concentración de la oferta (ya corregido)

El generador concentraba las sesiones CNE de los recursos con una sola sesión en la semana 13 de 26, y los pabellones en lunes. Se corrigió en el generador 0.2.0 con una fase de Weyl por recurso; los resultados actuales usan la oferta corregida.

Fuente: `docs/scheduler-formulation.md` § 11.2, `docs/decisions.md` § 13.

## Simulación (`simulation/`)

- **Granularidad de la oferta (limitación principal)**: cada sesión atiende una sola celda (servicio × especialidad). A 10.000 entradas:
  - Consultas: solo 466 de 1.246 celdas (37 %) reciben algún bloque en 26 semanas; cubren el 76 % del stock.
  - Pabellón: 219 de 304 celdas (72 %); cubren el 90 % del stock.
  - El resto del stock **no puede atenderse con ninguna política** porque no hay cupos en su celda. Esto pesa más cuanto menor es el tamaño de la corrida.
  
  Fuente: `docs/results.md` § Cobertura de la oferta, `docs/simulation-design.md` § 3.

- **Llegadas sin series públicas**: se derivan de la ley de Little (estado estacionario con la espera media de un solo corte) más los casos GES nuevos anuales de la Superintendencia. No hay estacionalidad ni tendencia.
  
  Fuente: `docs/simulation-design.md` § 2.

- **Oferta estacionaria**: se replica la del generador (multiplicador 1,0) sin margen. Todas las semanas tienen igual capacidad; no hay feriados, suspensiones de pabellón ni ausentismo de especialistas.
  
  Fuente: `docs/simulation-design.md` § 3.

- **Sin egresos administrativos por defecto**: solo atención (consulta o cirugía resuelve la entrada) y dos inasistencias. No hay abandono (parámetro `abandon_weekly_rate`, apagado por defecto), muerte ni derivación a otro servicio.
  
  Fuente: `docs/simulation-design.md` § 1.

- **Sesgo de composición**: dentro de una celda, la composición del stock no es exactamente la de las llegadas (las entradas que esperan más están sobrerrepresentadas). El sesgo se limita a la mezcla GES (corregida) y a la de procedimientos de duración distinta.
  
  Fuente: `docs/simulation-design.md` § 2.

- **Sin controles posteriores**: toda atención resuelve la entrada; no se modelan controles ni la derivación de consulta a cirugía.

- **Verdad de inasistencia es del generador**: la probabilidad verdadera con la que se sortea asistencia es la del generador sintético. **Las conclusiones valen para ese mundo, no para la red real.** El programador ve solo la predicción de `noshow/`.

Fuente: `docs/simulation-design.md`.

## Equidad y agregación

- **Control por grupo, no por paciente**: el programador limita la brecha de exposición al sobrecupo entre grupos (`GroupLimitsConfig`: edad, previsión y comuna, grupos de al menos 30 entradas, 5 pp por defecto; contrato provisional, no validado con expertos). No garantiza nada para un paciente específico, y en el plan canónico hay comunas pequeñas con exposición muy por sobre el total (la mayor, 16305 con 91 entradas, +38,5 pp).
  
  Fuente: `docs/results.md` § Equidad.

- **Comuna sin efecto propio en el sintético**: la comuna no tiene efecto directo en la inasistencia, solo a través del servicio de salud. El análisis por comuna mide sobre todo las brechas por servicio, no un efecto geográfico propio.
  
  Fuente: `docs/noshow-model-card.md` § Equidad, `docs/results.md` § Equidad.

- **Sin ajuste por comparaciones múltiples**: los IC 95 % de las comparaciones entre políticas son por comparación (t de Student con pocas réplicas), sin corrección por comparaciones múltiples; con muchas métricas y grupos, alguna diferencia puede ser azar.
  
  Fuente: `docs/simulation-design.md` (agregado entre réplicas).

## API y seguridad

- **Claves estáticas y sin expiración**: no hay rotación, revocación ni expiración automática. Las claves viven en un archivo JSON sin cifrado.
  
  Fuente: `docs/security.md` § Qué falta.

- **Limitador de peticiones por proceso**: si hay varias réplicas o instancias, el tope efectivo se multiplica. Detrás de un proxy, la IP vista es la del proxy (afecta solo a peticiones sin clave válida).
  
  Fuente: `docs/security.md` § API, Rate limiting.

- **Tiempo máximo de trabajos sin matar threads**: los trabajos se marcan `failed` al vencer el plazo, pero el hilo de Python que los ejecuta sigue ocupado resolviendo CP-SAT. Si guarda un plan antes de vencer, queda `pending` (requiere revisión) y el trabajo no se reporta exitoso. Hay un solo hilo de ejecución, así que las siguientes programaciones esperan.
  
  Fuente: `docs/security.md` § API.

- **CSP del panel débil**: incluye `'unsafe-inline'` y `'unsafe-eval'` porque Dash y Plotly lo requieren. Más vulnerable que la de la API.
  
  Fuente: `docs/security.md` § Panel.

- **Sin auditoría central**: los logs de la API y del panel quedan en cada proceso, sin centralización ni análisis de seguridad.

## Qué falta antes de datos reales

Nada de lo siguiente existe hoy:

1. **Proveedor de identidad**: reemplazar claves estáticas por autenticación institucional (SSO/OIDC).
2. **TLS**: HTTPS con HSTS; hoy se sirve HTTP plano.
3. **Cifrado en reposo**: PostgreSQL, Parquet, copias de seguridad.
4. **Política de retención y borrado**: de auditoría, planes y logs; hoy no hay rotación ni caducidad.
5. **Límite de peticiones distribuido**: protección contra DoS si hay varias réplicas o exposición pública.
6. **Revisión legal**: protección de datos personales y de datos de salud (normativa chilena), evaluación de impacto, convenios con servicios de salud.
7. **Validación institucional de los modelos**: ningún modelo ha pasado por revisión de expertos clínicos o administrativos.
8. **Pruebas de seguridad**: revisión independiente, pruebas de penetración, análisis estático de seguridad adicional.
9. **Permisos seguros en contenedores**: el modo 600 de usuarios.json depende del dueño en el host; en producción conviene usar secretos del orquestador.

Fuente: `docs/security.md` § Qué falta, modelo de amenazas.

## Resumen ejecutivo

- **Datos sintéticos**: no son extrapolables sin validación.
- **Supuestos sin verificación**: 53 parámetros del generador.
- **Granularidad de oferta**: a 10.000 entradas, el 24 % del stock CNE está en celdas sin ningún cupo.
- **Modelo de inasistencias**: AUC 0,625 (techo del generador 0,737).
- **Programador**: sin garantía de tiempo global, frontera no siempre alcanzada.
- **Simulación**: sin estacionalidad, sin abandono, sin derivación.
- **Equidad**: sin validación clínica, control solo por grupo (no individual).
- **Seguridad**: sin TLS, sin identidad institucional, sin cifrado en reposo.
- **No hay autorización clínica ni legal** para decisiones sobre pacientes reales.

Usar Prioriza como **herramienta de investigación y demostración de cómo mejorar la gestión de listas de espera**. Para datos reales: validar cada supuesto, entrenar modelos con datos locales, implementar con supervisión clínica y legal continua.
