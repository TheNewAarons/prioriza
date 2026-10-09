# Plan de Trabajo

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## P5: modelo de inasistencias (`noshow/`)

Rama: `feat/noshow-model`.

- [x] P5-T0 (Asignada a: Tier 3 - Kimi) -> Hecha por Tier 1 (fallback: proxy Tier 3 caído, ver log)
- [x] P5-T1 (Asignada a: Tier 1 - Claude) -> Hecha
- [x] P5-T2 (Asignada a: Tier 3 - Qwen) -> Hecha por test-writer (fallback)
- [x] P5-T3 (Asignada a: Tier 3 - Kimi) -> Hecha por docs-writer (fallback); reescrita por Tier 1 tras la revisión
- [x] P5-R (reviewer, opus) -> Revisión de P5-T1 hecha; hallazgos 1-9 corregidos por Tier 1

### P5-T0: variables de cita e historial disponibles

Fuente: parquet de `prioriza-synth generate` en `data/synthetic/<run_id>/` (mismas tablas que PostgreSQL),
`shared/src/shared/db/models.py` y `synthetic/src/synthetic/noshow_truth.py`.

| Tabla.columna | Contenido | ¿Observable? |
|---|---|---|
| `appointment.scheduled_start` | Fecha y hora de la cita (UTC). En el historial, siempre 12:00 UTC: la franja horaria es constante | Sí |
| `appointment.lead_days` | Días entre agendamiento y cita; historial U{7..90} | Sí |
| `appointment.status` | `attended` / `no_show` (etiqueta) | Sí (solo como etiqueta o historial previo) |
| `appointment.specialty_code` | Especialidad de la cita (migración 0004) | Sí |
| `appointment.duration_min` | Duración; en CNE siempre 20 min, en IQ delata el procedimiento | Sí (no se usa, ver T1) |
| `appointment.entry_id`, `slot_id` | `NULL` en el historial | No hay espera ni establecimiento por cita |
| `appointment.patient_id` | Enlace al paciente; permite historial previo de asistencia | Solo para agrupar |
| `catalog_specialty.care_type` | `consultation` / `surgery` | Sí |
| `patient.age_group`, `insurance`, `commune_code`, `health_service_code` | Atributos del paciente | Sí, pero excluidos (ver T1) |
| `waitlist_entry.*` | Entradas actuales; `entry_date` no se relaciona con las citas pasadas | Sí, pero sin enlace a citas del historial |
| `patient_latent.noshow_frailty`, `appointment_truth.true_noshow_prob` | Verdad del generador | **Prohibido** como variable; solo evaluación |

Proceso generador del historial: `logit p = α_{servicio,tipo} + γ_especialidad + β_edad + β_previsión(solo ses_gradient)
+ β_lead·log2(1 + lead/7) + u_paciente`; el término de espera vale 0 en el historial (hallazgo A2 de
`docs/design/synthetic-noshow-review.md`). k ~ Poisson(1,5) citas por paciente en 730 días antes de `as_of`.

No existen en los datos: sexo, etnia, nacionalidad, coordenadas ni distancia.

### Log

- 2026-10-08, Tier 1: el proxy LiteLLM (`localhost:38765`) rechaza `kimi-k3`, `qwen-max` y `deepseek-v4` con
  `MissingSessionID` (falta `x-opencode-session`; LiteLLM no reenvía `ANTHROPIC_CUSTOM_HEADERS`). P5-T0 la hizo
  Tier 1 porque su resultado es contexto necesario para P5-T1. P5-T2 y P5-T3 pasan a los subagentes del proyecto
  `test-writer` (sonnet) y `docs-writer` (haiku), fallback más cercano de la tabla de CLAUDE.md.
- 2026-10-08, Tier 1 (P5-T1): `noshow/` implementado (features con política explícita, split temporal en tres
  bloques, baseline por especialidad, logística y boosting, calibración isotónica/sigmoide por regla, métricas AUC,
  Brier, log loss, ECE y curva, bootstrap por paciente, equidad por grupo, persistencia joblib versionada, CLI
  `prioriza-noshow train` y `make train-noshow`). Tests de invariantes en `noshow/tests/test_noshow_invariants.py`;
  fixture reutilizable en `noshow/tests/noshow_test_support.py`. Resultado (seed 42, n 100.000): logística principal,
  AUC 0,624 vs 0,602 del baseline; Δ Brier −0,00089 (IC95 −0,00119 a −0,00058). Decisiones en `docs/decisions.md` §9.
- 2026-10-08, test-writer (P5-T2): 29 tests nuevos en `noshow/tests/` (`test_noshow_pipeline.py` 10, `test_noshow_metrics.py` 6, `test_noshow_models_split_data.py` 11, `test_noshow_cli.py` 2): pipeline de punta a punta, save/load/predict, reproducibilidad, métricas, baseline, calibración, split, data y CLI. Suite noshow: 41 tests, pytest y lint en verde; sin bugs de producción encontrados.
- 2026-10-08, docs-writer (P5-T3): `docs/noshow-model-card.md` (278 líneas): resumen, datos, split temporal, variables usadas y excluidas (con motivos), modelos, calibración, métricas en prueba (AUC 0,624 vs 0,602 baseline, Δ Brier −0,00089 IC95 sig.), equidad por grupo etario/previsión/servicio/comuna con mapeo de daño esperado, limitaciones (techo ~0,65, espera no aprendible, proceso estacionario, franja constante, proxies en reales), reproducción. Todos los números de `results/noshow.json`; sin redondeos que cambien sentido. Aviso obligatorio al inicio.
- 2026-10-08, Tier 1 (revisión de P5-T3): corregidas cifras y afirmaciones del model card que no salían de
  `results/noshow.json` (brecha de Arica vs verdad −4,42 pp, no −5,02; 44 comunas con n ≥ 200, no 29; tamaño = entradas,
  no pacientes; hiperparámetros fijos; causa del empeoramiento por la isotónica; mitigaciones y cifras inventadas
  eliminadas; filas sin calibrar agregadas; comandos de reproducción).
- 2026-10-08, Tier 1 (revisión de P5-T1 por `reviewer`): corregidos ALTO 1 (`build_candidate_features` para citas
  futuras), MEDIO 2 (candidatos sin calibrar en la selección: el principal pasa a logística sin calibrar), MEDIO 3
  (proxy pediátrico documentado + V de Cramér en results), MEDIO 4 (join con `maintain_order`), MEDIO 5 (corrida
  elegida por huellas del generador, sin mtime), BAJO 6-9 (tests de historial intermedio, elección de modelo, franja
  con horario de verano, versión del modelo con hiperparámetros). Model card reescrito con las cifras nuevas.

## P7: programador CP-SAT (`scheduler/`)

- [x] P7-T1 (Asignada a: Tier 1 - Claude) -> Hecha: `docs/scheduler-formulation.md`
- [ ] P7-T2 (implementación del modelo, Tier 1 / `optimizer`) -> Pendiente. Debe agregar `ortools` a `scheduler` y
  registrar en `docs/decisions.md` las decisiones de diseño de la formulación (fases lexicográficas, sobrecupo solo CNE
  y solo agregando, compatibilidad por servicio, límites de equidad provisionales).
- [ ] P6 (límites de equidad por grupo) -> La formulación fija un contrato provisional (§6.5); P6 lo confirma o ajusta.
- [ ] Generador (`synthetic/capacity.py`) -> Pendiente antes de P8: sesiones CNE concentradas en la semana 13 y
  bloques de pabellón concentrados en lunes (§11.2 de la formulación).

### Log

- 2026-10-08, Tier 1 (P7-T1): formulación CP-SAT escrita sin delegar (pedido del usuario). Tamaños medidos sobre la
  corrida canónica (N 100.000, seed 42): 4 semanas → 15.843 candidatos, 92.660 pares, subproblema mayor 14.535 pares;
  ningún paciente cruza servicios (descomposición por servicio exacta). Solo 1.857 de 3.866 GES obligadas tienen algún
  bloque compatible en 4 semanas, en buena parte por la concentración de sesiones CNE del generador.

## P8: implementación del programador (`scheduler/`)

Rama: `feat/scheduler-cpsat` (apilada sobre `feat/noshow-model`, que aún no está en `main`; la CLI usa `noshow`).

- [x] P8-T0 (Asignada a: Tier 3 - Kimi) -> Hecha (Kimi)
- [x] P8-T1 (Asignada a: Tier 1 - Claude) -> Hecha: `scheduler/` (instance, prepare, cpsat, phases, plan, greedy, risk, adapters, persist, cli), CLI `prioriza-schedule`, `make schedule`. Formulación actualizada con las decisiones de implementación; `docs/decisions.md` §10.
- [x] P8-T2 (Asignada a: Tier 1 - Claude) -> Hecha: `test_formulation_example.py`, `test_scheduler_invariants.py` (hypothesis), `test_ges_causes.py`, `test_risk.py`.
- [x] P8-T3 (Asignada a: Tier 3 - Qwen) -> Hecha (Qwen); test `db` reescrito y nombres en inglés por Tier 1 (ver log)

### P8-T0: interfaces que consume el programador

El núcleo de `scheduler/` recibe solo `polars.DataFrame` (formulación §2 y §14); un adaptador arma
las tablas desde PostgreSQL o parquet. Estas son las interfaces reales del repo que ese adaptador usa.

**`priority/`** (puntaje S y puesto en la cola):

- `rank_frame(df: pl.DataFrame, rules: RuleSet, *, as_of: date, partition_by: Sequence[str] = ("health_service_code", "specialty_code", "care_type")) -> dict[tuple[object, ...], Ranking]` — `priority/src/priority/adapters.py:85`. Exige columnas `id`, `clinical_priority`, `entry_date`, `ges_deadline` (+ `status = "waiting"` si existe la columna) y las de partición. Devuelve un `Ranking` por cola; `Ranking.entries` son `RankedEntry(rank, score)` con `score: PriorityScore` (`score.score` es S en [0, 100]; `score.entry_id`, `score.tier: StrictTier` NONE/GES_DUE_SOON/GES_OVERDUE, `score.days_to_ges_deadline`) — `priority/src/priority/score.py:45-101`.
- `score_entry(inp: PriorityInput, rules: RuleSet, *, as_of: date) -> PriorityScore` — `score.py:205`. `rank(inputs, rules, *, as_of) -> Ranking` — `score.py:233`.
- `PriorityInput` (dataclass frozen): `entry_id: str`, `clinical_priority: ClinicalPriority`, `entry_date: date`, `ges_deadline: date | None`; propiedad `is_ges` — `priority/src/priority/inputs.py:14`.
- Reglas: `load_default_rules() -> RuleSet` (`rules.py:427`), `load_rules(path: Path) -> RuleSet` (`rules.py:422`). `RuleSet.rules_id: str`, `rules_version: str`, `digest() -> str` (`rules.py:241-309`) alimentan `rules_digest`/`rules_version` de la instancia.
- `from_waitlist_entry(e: WaitlistEntry) -> PriorityInput` — `adapters.py:24` (falla si `status != waiting`).

**`noshow/`** (probabilidad p; solo el adaptador, nunca el núcleo):

- `build_candidate_features(candidates: pl.DataFrame, history: pl.DataFrame, specialties: pl.DataFrame, entries: pl.DataFrame | None = None) -> pl.DataFrame` — `noshow/src/noshow/features.py:131`. `candidates` necesita `id`, `patient_id`, `scheduled_start` (UTC), `lead_days`, `specialty_code` (`entry_id` opcional); `history`: `patient_id`, `scheduled_start`, `status`; `specialties`: `code`, `care_type`. Conserva el orden de `candidates`. Para cada par (entry_id, slot) candidato: `scheduled_start = start_at` del bloque, `lead_days = (local_date_b − as_of).days`.
- `load_bundle(path: Path) -> dict[str, Any]` — `noshow/src/noshow/train.py:317`. Artefacto: `models/noshow/<run_id>/noshow_model.joblib` (escrito por `save`, `train.py:297-314`; dir por defecto de la CLI `models/noshow`, `cli.py:47`). El bundle trae `model_version` (va a `noshow_model_version` de la instancia), `primary`, `models`, `columns`.
- `predict_noshow(bundle: dict[str, Any], features: pl.DataFrame) -> np.ndarray` — `train.py:328`. Recorta el resultado a [0,001; 0,95] antes de CP-SAT (formulación §2.2).
- `load_run(run_dir: Path) -> RunData` (`noshow/src/noshow/data.py:70`) y `find_run_dir(data_dir, seed, size, scenario, expected) -> Path` (`data.py:94`) para leer la corrida desde parquet (`data/synthetic/<run_id>/`).
- Restricción dura: `FORBIDDEN_FEATURES` prohíbe `health_service_code`, `establishment_code`, `age_group`, `insurance`, `commune_code` como features (`features.py:39-57`); esos atributos van solo en la tabla `groups` para equidad.

**`shared/`** (base de datos y enums):

- Engine/sesión: `get_engine(url: str | None = None) -> Engine` (cacheado; usa `Settings.sqlalchemy_url` si no hay URL) y `session_factory() -> sessionmaker[Session]` — `shared/src/shared/db/session.py:12-19`. URL: `Settings.sqlalchemy_url` (`postgresql+psycopg://…`) y `get_settings()` — `shared/src/shared/config.py:30-49`.
- Enums (`shared/src/shared/db/enums.py`): `ClinicalPriority` p1-p4, `EntryStatus` (waiting/scheduled/resolved/removed), `ResourceKind` (operating_room/specialist_agenda), `AppointmentStatus` (scheduled/attended/no_show/cancelled), `AppointmentOrigin` (history/scheduler/simulation: las citas del plan usan `SCHEDULER`), `Policy` (fifo/priority/optimized), `ReviewStatus` (pending por defecto). `CareType` (consultation/surgery) está en `shared/src/shared/schemas.py:27`.
- Tabla `schedule_run` (`shared/src/shared/db/models.py:339-365`): `id` (UUID), `run_id` (FK synthetic_run), `policy`, `horizon_start`, `horizon_end` (date), `seed`, `params` (JSONB), `solver_status`, `objective_value`, `review_status` (default `pending`), `code_version`, `created_at`, `finished_at`.
- Tabla `appointment` (`models.py:368-441`): `id`, `run_id`, `patient_id`, `entry_id` (nullable), `slot_id` (obligatorio salvo `origin = 'history'`), `schedule_run_id` (nullable), `origin`, `status`, `scheduled_start` (timestamptz), `duration_min`, `lead_days` (>= 0), `is_overbooked` (default False), `predicted_noshow_prob` (0-1, nullable), `specialty_code`.
- Fuentes de las tablas de entrada: `waitlist_entry` (`models.py:224`: `id`, `patient_id`, `health_service_code`, `establishment_code`, `specialty_code`, `procedure_code`, `care_type`, `clinical_priority`, `is_ges`, `ges_deadline`, `entry_date`, `status`), `slot` (`models.py:310`: `id`, `resource_id`, `specialty_code`, `start_at`, `duration_min`, `unit_min` nulo en pabellón), `resource` (`models.py:289`: `kind`, `establishment_code`, `health_service_code`, `specialty_code`), `procedure.duration_min` (`models.py:131`), `patient` (`models.py:185`: `age_group`, `insurance`, `commune_code` para `groups`). Toda tabla por corrida exige `run_id` en el filtro.

**Formulación (docs/scheduler-formulation.md):** §2.1 define los campos de la instancia (`as_of`, `horizon_start`, `horizon_weeks`, `rules_digest`, `rules_version`, `noshow_model_version`, `seed`); §2.2 las cuatro tablas (`entries`, `blocks`, `noshow`, `groups`) con sus columnas exactas; §14 la interfaz pública del paquete (`SchedulingInstance.from_frames`, `solve`, `greedy_schedule`, `plan.assignments`, `plan.report`) que P8-T1 debe implementar.

- 2026-10-08, Kimi (P8-T0): escaneados `priority/`, `noshow/` (features, train, data), `shared/` (models, enums, session, config, schemas) y docs/scheduler-formulation.md §2/§14. Resumen de interfaces con firmas y archivo:línea escrito arriba, en '### P8-T0: interfaces que consume el programador'. Puntos clave: el núcleo solo ve DataFrames; el adaptador usa `rank_frame` para S y rank, `build_candidate_features`+`predict_noshow` para p (artefacto en `models/noshow/<run_id>/noshow_model.joblib`), `get_engine`/`session_factory` para la base, y persiste en `schedule_run`/`appointment` (origin `scheduler`, review_status `pending`).
- 2026-10-08, Qwen (P8-T3): 8 tests nuevos en `scheduler/tests/` (5 en `test_scheduler_cli.py`, 3+1db en `test_scheduler_persist.py`). CLI: corrida sin sobrecupo `--policy all` escribe JSON con `comparison` de 3 políticas, `disclaimer` y parquet por política; `--run-dir` inexistente y `--data-dir` vacío fallan; sobrecupo sin modelo sugiere `make train-noshow`; optimized con modelo entrenado corre. Persistencia (sesión falsa): `ScheduleRun` con `review_status=PENDING`, horizonte `end = exclusivo - 1 día`, params JSON-serializable; `appointment` con id uuid5 determinista, origin SCHEDULER, status SCHEDULED, `is_overbooked` y `predicted_noshow_prob` copiados; `LookupError` sin corrida sintética. Test db marcado `@pytest.mark.db` contra PostgreSQL real (se omite sin conexión). Suite completa: 37 passed, 1 skipped; lint y format en verde. Sin bugs de producción encontrados.
- 2026-10-08, Tier 1 (P8-T1/T2): `scheduler/` implementado según la formulación; API de CP-SAT consultada en ortools 9.15
  instalado (`cp_model.py`, stubs) y en `sat_parameters.proto` v9.15. 39 tests en `scheduler/tests` (1 `db` omitido sin
  PostgreSQL). El ejemplo §13 coincide (Z0 16.216, Z3 16.787, riesgo 0,2475); la variante con GES infactible del documento
  estaba mal calculada (16.772) y se corrigió a 17.271 (el plazo nuevo sube el puntaje P4 de E). Hallazgos corregidos por
  tests y corridas: S0 no se fijaba en la fase 4, pistas incompletas daban UNKNOWN, el filtro de candidatos dependía del
  interruptor de sobrecupo y no detectaba colas agotadas por R4, regla G^od contradictoria entre §6.2 y §7, choque de
  nombres `scheduler.solve`. Decisiones: modo determinista con un hilo y `linearization_level = 2` (medido). Corrida
  canónica 4 sem: optimized 5.843 agendadas y 1.211/3.866 GES frente a 5.672 y 851 de priority; 143 s reales (objetivo
  120 s no cumplido por poco). Resultados y negativos en `docs/scheduler-formulation.md` §11.3.
- 2026-10-08, Tier 1 (revisión de P8-T3): el test `db` de Qwen insertaba un `synthetic_run` sin campos obligatorios y
  citas con FK inexistentes (fallaría con PostgreSQL arriba); se reescribió cargando una corrida sintética real chica.
  Nombres de tests pasados a inglés (CLAUDE.md).
- Pendiente: revisión de `reviewer` sobre `scheduler/` antes del siguiente prompt (CLAUDE.md); corregir la oferta
  sintética (§11.2) antes de la simulación.

## P9: benchmark y rendimiento del programador (`scheduler/`)

Rama: `feat/scheduler-cpsat` (sigue sobre P8).

- [x] P9-T1 (Asignada a: Tier 1 - Claude) -> Hecha: `scheduler/bench.py` (CLI `prioriza-schedule-bench`),
  técnicas nuevas en `cpsat.py`/`phases.py` (poda de niveles de sobrecupo, cota del objetivo con la pista, pista voraz
  con sobrecupo para 3b, arranque en caliente al expandir la frontera) con interruptores en `SolverConfig` para la
  ablación; `results/scheduler-benchmark.json`.
- [x] P9-T2 (Asignada a: Tier 3 - Kimi) -> Hecha (Kimi): target `make bench-scheduler`.
- [x] P9-T3 (Asignada a: Tier 3 - Kimi) -> Hecha (Kimi): `docs/scheduler-performance.md` desde
  `results/scheduler-benchmark.json`, sin cambiar números.

### P9-T2: instrucciones

Agregar al `Makefile` un target `bench-scheduler` que corra
`uv run --package scheduler prioriza-schedule-bench $(BENCH_ARGS)` (variable `BENCH_ARGS ?=` vacía por defecto,
igual que `SCHEDULE_ARGS`), agregarlo a `.PHONY` y a `make help` ("Benchmark del programador CP-SAT"). La CLI ya
existe: por defecto tamaños 1000,10000,50000, horizontes 2,4, ablación activa, 3 repeticiones, datos en `data/bench/`
y salida `results/scheduler-benchmark.json`. Agregar `data/bench/` a `.gitignore` (datos reproducibles, como
`data/synthetic/`). No correr el benchmark (tarda ~20 min); verificar con `make -n bench-scheduler` y
`uv run --package scheduler prioriza-schedule-bench --help`. No commitear.

### Log

- 2026-10-09, Tier 1 (P9-T1): con la oferta de 26 semanas del generador, las corridas de 1.000 y 10.000 tienen 0-1 y
  25-59 bloques en 2-4 semanas (artefacto §11.2 de la formulación): el benchmark sería trivial. Se generan corridas
  propias con `horizon_weeks` del generador = semanas del plan (oferta repartida en el horizonte) en `data/bench/`.
  Medición previa (código de `6688d66`, 50k × 4 sem): 125 s reales, FEASIBLE, brecha 1,68 %; ~34 s de solver se
  gastaban en componentes que la expansión de frontera re-resolvía desde cero y no salían en el informe.
- 2026-10-09, Tier 3 (P9-T2, Kimi): agregado target `make bench-scheduler` al `Makefile` (con `BENCH_ARGS ?=` vacío,
  en `.PHONY` y en `make help` como "Benchmark del programador CP-SAT") y `data/bench/` al `.gitignore`. Verificado
  con `make -n bench-scheduler` y `uv run --package scheduler prioriza-schedule-bench --help`; no se corrió el
  benchmark (~20 min). Sin commit.
- 2026-10-09, Tier 1 (revisión de P9-T1 por `reviewer`, opus): sin hallazgos ALTOS. Corregidos MEDIO 1 (`canonicalize`
  con simetrías apagadas podía violar R12 en la pista), MEDIO 2 (comparación lexicográfica: ahora con `optimized` sin
  sobrecupo frente a la voraz), MEDIO 3 (dependencia `synthetic` en `docs/decisions.md` §11), MEDIO 4 (métricas de
  tiempo con nombres explícitos: reloj de `solve`, determinista del plan y total), MEDIO 5 (tests: comparación por
  fase y subproblema con conteo de casos comparados, modo de equidad absoluto, expansión de frontera, pista canónica,
  CLI con límite corto), BAJO 6-10. El benchmark en curso se detuvo y se relanzó con los arreglos.

- 2026-10-09, Tier 1 (P9-T1): la ablación `none` (sin pistas) en 50k × 4 sem tumbó el benchmark: `_check_against_greedy`
  lanzaba error porque un subproblema quedó 3 puntos (0,005 %) bajo la voraz con todas las fases en OPTIMAL. Defecto
  previo a P9: OPTIMAL con `relative_gap_limit = 0,001` no es óptimo probado. Ahora es error solo si la pérdida está en
  p1/GES o la fase 3a tiene brecha 0; si no, advertencia `worse_than_baseline` (formulación §9.5 actualizada).
- 2026-10-09, Tier 3 (P9-T3, Kimi): escrito `docs/scheduler-performance.md` (6 secciones, estilo model card, aviso
  obligatorio) solo con números de `results/scheduler-benchmark.json` (máx. 3 cifras significativas en tiempos/brechas,
  enteros exactos). Reportados tal cual: empate total en 1.000 × 2, `sum_coef` −24 sin sobrecupo en 10.000 × 2,
  `without_hints` mejor que `all` en 50.000 × 4 (36.270.505, 70,6 deterministas) y la advertencia
  `worse_than_baseline` de `none`. Sin commit.

- 2026-10-09, Tier 1 (P9-T1, resultados): `results/scheduler-benchmark.json`. 10.000 entradas: OPTIMAL en 0,17 s
  (2 sem) y 0,41 s (4 sem), brecha ≤ 3,6e-7. 50.000 × 4: FEASIBLE, brecha 0,18 %, 76 s reales / 78 det. Frente a la
  voraz `priority`, sin sobrecupo y en orden lexicográfico, nunca peor; en 10.000 × 2 la suma de `c_ib` queda 24 puntos
  bajo la voraz (gana 7 GES). En la ablación de 50.000 × 4, apagar las pistas dio mejor objetivo (+0,05 %) y menos
  tiempo; se informa tal cual. Corrida canónica 100k × 4 rehecha (formulación §11.3): 5.952 agendadas (P8: 5.843),
  144 sobrecupos (P8: 40), exposición al sobrecupo 38-41 % (P8: 10-13 %), 166 s reales (P8: 143 s; sigue sin cumplir
  120 s). Pendiente: presupuesto de tiempo global (hoy es por pasada y la expansión de frontera lo duplica).
- 2026-10-09, Tier 1 (revisión de P9-T3): corregidas en `docs/scheduler-performance.md` la descripción del límite de
  tiempo y de los hilos, la definición de los pares, la frontera (sí sigue alcanzada en 50.000: 3 y 2 colas), la
  afirmación de que en 10.000 todas las variantes dan el mismo objetivo (en 10.000 × 4 varían 129 puntos) y una
  referencia equivocada.
### P9-T3: instrucciones

Escribir `docs/scheduler-performance.md` (español, estilo de `docs/noshow-model-card.md`) solo con números de
`results/scheduler-benchmark.json`, copiados sin redondear de forma que cambie su sentido (máx. 3 cifras significativas
en tiempos y brechas; enteros exactos). Aviso obligatorio al inicio. Secciones:
1. Qué se mide y cómo: celdas (tamaño × horizonte), oferta generada para el horizonte (`docs/decisions.md` §11), semilla,
   límite de tiempo, máquina (`machine`), qué es tiempo real (`solve_wall_s`, mediana de `repeats_all`) y determinista
   (`deterministic_time_plan` y `_total`). Que la corrida de 1.000 no pasa la calibración estricta (`data.calibration_strict_failed`).
2. Tamaño del problema por celda: entradas, bloques CNE/pabellón, `pairs_all`, `pairs_same_queue`, `pairs_compatible`,
   `pairs_in_model`, subproblemas, subproblema mayor, máx. variables, niveles de sobrecupo nominales vs conservados,
   clases de simetría.
3. Tiempo, estado y brecha de `optimized/all` por celda, con `solve_wall_within_time_limit` y
   `deterministic_plan_within_time_limit`. Decir explícitamente si el tamaño medio (10.000) se resuelve dentro del límite y con qué brecha.
4. Comparación con la voraz `priority`: tabla de `optimized_vs_priority.delta` (con sobrecupo) y de
   `optimized_without_overbooking_vs_priority` (delta y `optimized_not_worse_lexicographic`). Reportar tal cual las
   diferencias pequeñas, nulas o negativas (p. ej. `sum_coef` negativo en alguna celda) y explicar que el orden
   lexicográfico prioriza p1 y GES antes que el puntaje.
5. Ablación (celdas de 50.000, y nota de que en 1.000/10.000 todas las variantes dan lo mismo o casi): por variante
   estado, brecha, `deterministic_time_total`, `sum_coef`, `scheduled`, `warnings_worse_than_baseline`. Reportar tal cual
   cuando apagar una técnica da mejor objetivo o menos tiempo (p. ej. `without_hints` en 50.000 × 4).
6. Limitaciones: tiempos de una máquina; brecha de 3b mide en parte la cota; artefactos de la oferta sintética
   (formulación §11.2); el benchmark no corrige el generador.
No inventar cifras ni causas que no estén en el JSON o en `docs/scheduler-formulation.md` §8.6/§11 y `docs/decisions.md` §11.
No tocar otros archivos salvo TASK_PLAN.md (marcar P9-T3 y log). No commitear.
