# Revisión crítica del proyecto (P17)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Revisión hecha el 2026-10-10 sobre `main` en el commit `3baf70f` (antes de las correcciones de esta fase). Resultado: **0 hallazgos críticos, 2 altos (corregidos), 6 medios (4 corregidos, 2 abiertos con justificación) y 12 bajos (en [`backlog.md`](backlog.md))**. Las líneas citadas son las del commit revisado.

## Cómo se hizo

- **Suite completa con cobertura** (sesión principal): 1.168 pruebas pasadas y 14 omitidas. Las 14 son las pruebas `db`; las corrí además contra un PostgreSQL 16 temporal con las migraciones aplicadas y pasan.
- **Búsquedas dirigidas** (sesión principal, con `git grep` y lectura de código): variables del modelo de inasistencias, fugas en el split temporal, caminos que dejan un plan vigente, aislamiento de la verdad sintética, datos personales en logs y fixtures, constructos riesgosos (`pickle`, `subprocess`, `yaml.load`), aviso de herramienta de investigación.
- **Revisión de restricciones del programador contra la formulación** (subagente `reviewer`, solo lectura): R1 a R15, fases 1 a 4, filtro de candidatos y fijaciones entre fases.
- **Revisión del informe contra `results/`** (subagente `reviewer`, solo lectura): regeneró el informe en un directorio temporal (idéntico al de `docs/`) y contrastó 25 cifras con su JSON.
- **Código de tiers externos.** Las tareas de Tier 2 y 3 se delegaron al proxy de OpenCode Go, que falló casi siempre (límite de uso, ver `TASK_PLAN.md`). Lo que sí escribieron modelos externos: DeepSeek, la simulación (P10-T2, corregida tras mi revisión); Qwen, tests de P8-T3 y P10-T4 y la primera parte del panel (P13-T1, terminada por un subagente Claude); Kimi, escaneos y `scheduler-performance.md` (P8-T0, P9-T2/T3). El resto de las tareas "externas" las hicieron subagentes Claude por respaldo. En esta revisión no encontré construcciones peligrosas en ese código (sin `eval`, `exec`, `shell=True`, `dangerously_allow_html` ni `yaml.load` inseguro) y la simulación mantiene la verdad sintética aislada (solo `simulation/truth.py` la calcula). No hice una relectura línea por línea del panel; la cubren sus 84 % de cobertura y la revisión visual de P13.

## Cobertura por paquete

| Paquete | Líneas cubiertas | Cobertura |
|---|---:|---:|
| `noshow` | 866 / 872 | 99,3 % |
| `priority` | 1.573 / 1.586 | 99,2 % |
| `ingestion` | 2.645 / 2.703 | 97,9 % |
| `reports` | 966 / 1.002 | 96,4 % |
| `simulation` | 995 / 1.036 | 96,0 % |
| `scheduler` | 3.019 / 3.152 | 95,8 % |
| `api` | 2.399 / 2.628 | 91,3 % |
| `synthetic` | 2.358 / 2.599 | 90,7 % |
| `shared` | 1.087 / 1.221 | 89,0 % |
| `dashboard` | 1.810 / 2.152 | 84,1 % |

Medida con `pytest-cov` (ejecutado con `uv run --with`, sin agregarlo al proyecto) incluyendo las pruebas `db` omitidas. Sin ellas, `api/sql_store.py` queda en 29 % y `synthetic/load.py` en 28 %. Archivos grandes con baja cobertura: `dashboard/views/programacion.py` (65 %), `dashboard/cli.py` (49 %), `simulation/world.py` (59 %), migraciones 0002, 0003 y 0005 (57 %).

## Verificaciones sin hallazgos

| Verificación | Resultado |
|---|---|
| Variables prohibidas en el modelo de inasistencias | El modelo usa solo `specialty_code`, `care_type`, `weekday`, `time_band`, `lead_days`, `prior_attended`, `prior_no_show` (y `wait_days` si existe) (`noshow/src/noshow/features.py:22-36`). `FORBIDDEN_FEATURES` (sexo, etnia, nacionalidad, edad, previsión, comuna, servicio, fragilidad, verdad, ids) se comprueba con una excepción antes de entrenar (`features.py:232-238`) y `data.py` solo carga las tablas permitidas. |
| Fugas en el split temporal | El split divide por `scheduled_start` en tres intervalos disjuntos y posteriores (`split.py:50-69`). El historial de cada cita cuenta solo resultados con fecha anterior al agendamiento, con desigualdad estricta (`features.py:133-170`, `_prior_history`). El modelo se elige y calibra con el conjunto de calibración; el de prueba solo se evalúa (`train.py:151-165`). |
| Verdad sintética | Solo `simulation/truth.py:17` importa `true_noshow_prob`; `noshow` la lee únicamente para evaluar en el conjunto de prueba (`train.py:171,273,283`). El programador solo ve la probabilidad predicha. |
| Planes vigentes sin aprobación | Cuatro capas: `CHECK NOT is_current OR review_status = 'approved'` en la base (`shared/db/models.py:348`), índice único parcial de un vigente por corrida, `check_review` y `check_activate` (`api/plans.py:123-158`) con cuatro ojos y rol, y bloqueo de fila en el almacén SQL (`sql_store.py:285-327`). Todo plan nace `pending` (`persist.py:54`, `plan.py:717`, `plans.py:320`). La prueba `test_sql_store.py:144-149` intenta forzar `is_current` directamente en la base. |
| Datos personales en logs y fixtures | Sin RUT ni correos reales en archivos versionados (el único correo es un dato falso de la prueba de redacción). Los fixtures son extractos de palabras de los PDF públicos de la Glosa 06 (984 KB, agregados). Los logs pasan por la redacción central de `shared.logging` y no hay `log`/`print` de ids de pacientes fuera de ella. |
| Aviso de herramienta de investigación | README (primera línea), `docs/results.md` (1) y `docs/results.html` (2), `docs/limitations.md`, `docs/security.md`, `docs/api.md`, `DESCRIPTION` de la API y todos los modelos de respuesta de datos (`DisclaimerModel`; los modelos anidados lo heredan de su contenedor), y banda fija del panel. Única excepción: las respuestas de error (`ErrorOut`), en el backlog. |
| Construcciones riesgosas | `yaml.load` usa un `SafeLoader` propio (`priority/rules.py:314`); los `subprocess` usan listas fijas sin shell (`dashboard/cli.py:93-103`, `reports/facts.py:209`). `joblib.load`: ver M-05. |

## Hallazgos

Estado: **Corregido** (con el commit de esta fase), **Abierto** (justificado) o **Backlog** (bajo).

### Críticos

Ninguno.

### Altos

| Id | Archivo:línea | Hallazgo | Estado |
|---|---|---|---|
| A-01 | `reports/src/reports/templates/results.md.j2:110` | El texto fijo decía "diferencias negativas indican sobrestimación", pero la brecha es predicha menos verdad: negativa significa **subestimación**. El informe invertía el sentido del sesgo en edades 15-44, servicio 1 y comuna 15101 (por ejemplo, 15-19: predicha 15,4 %, verdad 18,6 %). | **Corregido.** Texto aclarado con el sentido de ambos signos; prueba en `reports/tests/test_build.py`. |
| A-02 | `reports/src/reports/facts.py:948-951` (se ve en `results.md:676`) | En la equidad de la simulación se descartaban sin aviso los grupos que no alcanzaban el mínimo de entradas en alguna réplica: 51 de 207 comunas. Uno de ellos (09107) tenía 56,2 % de exposición al sobrecupo, más que el "grupo más expuesto" que el informe nombraba (05503, 53,8 %): se ocultaba un resultado desfavorable, contra la regla de CLAUDE.md. | **Corregido.** Los grupos parciales se promedian sobre las réplicas en que aparecen y se marcan (`replicas`, `n_partial`); el informe dice en cuántas réplicas está presente el más expuesto y cuántos grupos son parciales. **El resultado publicado cambia:** el grupo más expuesto es ahora la comuna 08308 (66,7 %, +43,9 pp, 36 entradas, presente en 1 de 5 réplicas) y son 207 grupos evaluados (antes 156). La cifra es poco estable por el tamaño del grupo, y así se dice. Pruebas en `test_facts.py` y `test_build.py`. |

### Medios

| Id | Archivo:línea | Hallazgo | Estado |
|---|---|---|---|
| M-01 | `reports/.../results.md.j2:154` | "Mayor brecha absoluta" se imprimía sin su signo real ("+3,21 pp" en 15-19 cuando el JSON dice -3,21; igual en surgery, servicio 1 y comuna 15101). | **Corregido.** Se imprime `gap_vs_truth` con su signo. |
| M-02 | `reports/.../results.md.j2:206` | "40.870 candidatas de 100.000 (31.978 fuera)" mezclaba denominadores (31.978 sale de 72.848 con bloque compatible); y "540 citas agregadas por sobrecupo" (entradas que ingresan en la fase 3b, con reemplazos) contradecía los 343 bloques con una cita sobre su capacidad. | **Corregido.** La frase cuadra (72.848 con bloque compatible + 27.152 sin ninguno = 100.000; 40.870 + 31.978 = 72.848), `facts` falla si no cuadra, y el sobrecupo se informa por bloques y por citas sobre la capacidad. |
| M-03 | `scheduler/src/scheduler/cpsat.py:586-587`, `plan.py:111-119` | R4 (un cupo por paciente y día) ignora las citas congeladas (`prebooked_*`): con `commit_weeks ≥ 2` en la simulación, o con citas `scheduled` previas en `make schedule`, un paciente puede quedar con dos citas el mismo día sin que la verificación lo detecte. | **Abierto.** Latente: con `commit_weeks = 1` (por defecto y en todos los resultados publicados) no hay citas congeladas. El arreglo cambia la interfaz de `SchedulingInstance` y exige regenerar resultados. En [`backlog.md`](backlog.md). |
| M-04 | `scheduler/src/scheduler/phases.py:310-319` | La fase 4 (equilibrio) no fija el conjunto de pacientes agendados, aunque la formulación §8.1 dice que solo puede mover bloques; podría agregar pacientes etiquetados `phase_added = "3b"` sin que la 3b haya corrido y desactivar la comprobación de §9.4. | **Abierto.** El plan cumple todas las restricciones duras; es una incoherencia con la formulación y de etiquetado. Corregirlo cambia el plan canónico. En [`backlog.md`](backlog.md). |
| M-05 | `noshow/src/noshow/train.py:319` (usos en `scheduler/.../adapters.py:275`, `simulation/.../world.py`) | El modelo se cargaba con `joblib.load` (pickle) sin verificar el archivo. | **Corregido.** `save` registra `joblib_sha256` en `metadata.json` y `load_verified_bundle` lo verifica antes de cargar (falla si falta o no coincide). Detecta corrupción o reemplazo parcial; no protege si alguien puede escribir ambos archivos, y `docs/security.md` lo dice. **Los modelos entrenados antes de esta fase deben reentrenarse** (`make train-noshow`, o `scripts/demo.sh --fresh`). |
| M-06 | `shared/src/shared/config.py:16` | La contraseña de PostgreSQL por defecto (`change-me`) se aceptaba también con `ENVIRONMENT=production`. | **Corregido.** En producción, sin `DATABASE_URL`, se rechaza la contraseña por defecto o vacía (sin imprimirla). Desarrollo no cambia. |

### Bajos

Los 12 hallazgos bajos están en [`backlog.md`](backlog.md), con archivo y línea. Los de mayor interés: la fase 3b sin exigir puntaje `≥ Z0` cuando `objective_cut` y `hints` están apagados (`phases.py:286`); R15 con `floor` mientras la formulación dice `round` (`cpsat.py:33-35`); la dirección "mejora" asignada a la inasistencia realizada en el informe; el aviso ausente en `ErrorOut` (`api/schemas.py:36`); y el CI desactivado.

## Limitaciones de esta revisión

- El revisor del programador no ejecutó el solver completo (tarda minutos): comparó el código con la formulación y corrió 17 pruebas puntuales. Las restricciones se verificaron por lectura, no por un barrido de instancias adversarias.
- Las cifras del informe se contrastaron por muestreo (25 cifras de las cinco fuentes), más la regeneración idéntica del informe; no se contrastó cada una.
- No hubo revisión de seguridad independiente ni pruebas de penetración (ver `docs/security.md`, "Qué falta antes de usar datos reales").
- La revisión se hizo en la misma sesión que construyó parte del proyecto; los dos subagentes revisores partieron sin ese contexto, pero no es una revisión externa.
