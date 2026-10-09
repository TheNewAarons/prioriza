# Decisiones arquitectónicas de Prioriza

## 1. Layout del workspace y herramientas de desarrollo

**Fecha**: 2026-10-02

**Decisión**:
- Workspace `uv` con 9 miembros: `shared`, `ingestion`, `synthetic`, `priority`, `noshow`, `scheduler`, `simulation`, `api`, `dashboard`.
- Python 3.12 como única versión soportada.
- Herramientas de desarrollo: `ruff` (lint y format), `mypy --strict` en `shared`, `priority` y `scheduler`, `pytest` con `hypothesis` para tests de propiedad.
- Pre-commit hooks locales (sin repos remotos) para automatizar ruff y mypy en cada commit.

**Justificación**:
- `uv` permite builds reproducibles y gestión de dependencias compartidas sin PyPI.
- Separación de miembros facilita tests independientes, especificaciones de mypy por módulo (solo donde hay lógica crítica), y paralelización.
- Python 3.12: soporte a largo plazo (hasta octubre 2028) y características modernas (type hints mejores, performance).
- `ruff` es 10-100x más rápido que `flake8`+`black`, integra isort y múltiples linters.
- `mypy --strict` en `shared`, `priority` y `scheduler` asegura tipado exhaustivo en núcleo de negocio; otros miembros pueden ser menos estrictos.
- Pre-commit local evita latencia de repos remotos y permite scripts personalizados.

**Alternativas consideradas**:
- Poetry: más lento, menos soporte para workspaces sin setup.py.
- Ruff + Black separados: ruff unifica mejor, más fácil de mantener.
- `--strict` en todos los módulos: no, porque api y dashboard tienen lógica menos crítica.

---

## 2. Dependencias de infraestructura (shared, api, dashboard) y contenedores

**Fecha**: 2026-10-02

**Dependencias agregadas**:
- `pydantic-settings`: configuración tipada desde variables de entorno/`.env`; permite `mypy --strict` con el plugin de pydantic y evita parsear `os.environ` a mano.
- `sqlalchemy>=2`, `alembic`: ORM y migraciones definidos en CLAUDE.md (PostgreSQL 16, sin Django).
- `psycopg[binary]>=3`: driver de PostgreSQL (URL `postgresql+psycopg://`); la variante binaria evita compilar libpq en las imágenes slim.
- `fastapi`, `uvicorn[standard]`: API definida en CLAUDE.md; uvicorn es el servidor ASGI de referencia.
- `dash`, `dash-bootstrap-components`, `plotly`: panel definido en CLAUDE.md.
- `gunicorn` (solo `dashboard`): Dash corre sobre Flask; el servidor de desarrollo de Flask no es apto para producción, y gunicorn (WSGI, multiproceso) es el estándar maduro y simple para servir `dashboard.app:server`. Uvicorn no sirve aquí porque Flask es WSGI, no ASGI.

**Contenedores**:
- Dockerfiles multi-stage: el builder usa la imagen oficial de uv (`uv sync --frozen --no-dev --no-editable --package <m>`) y la imagen final (`python:3.12-slim-bookworm`) solo copia el venv, con usuario no root y HEALTHCHECK en Python (sin instalar curl).
- Se sincronizan primero solo los `pyproject.toml` + `uv.lock` (`--no-install-workspace`) para cachear las dependencias.
- `POSTGRES_HOST` se sobreescribe a `db` dentro de compose; en el host `.env` usa `localhost`, de modo que `make migrate` corre desde la máquina local contra el puerto 5432 publicado.

---

## 3. Control de versiones

**Fecha**: 2026-10-02

- Repositorio público en GitHub: https://github.com/TheNewAarons/prioriza. Se creó privado; la protección de ramas en repos privados requiere GitHub Pro, por lo que se hizo público. CI no corre en ningún caso mientras la cuenta esté bloqueada por facturación (GitHub: "The job was not started because your account is locked due to a billing issue"); en el repo privado se manifestó como `startup_failure`. El repo no contiene datos reales, solo código y datos sintéticos, por lo que publicarlo no expone información sensible.
- Trunk-based con ramas cortas, Conventional Commits en español, `main` protegida: requiere PR y el check `checks` en verde; sin force push ni borrado. Detalle en [version-control.md](version-control.md).
- `uv.lock` se versiona (antes `.gitignore` lo excluía por `*.lock`, lo que rompía `uv sync --frozen` en CI y Docker).
- Solo la sesión principal commitea; los subagentes no hacen commits.

---

## 4. Fuentes de datos públicos

**Fecha**: 2026-10-02

- Fuentes de entrada y de contexto definidas en [data-sources.md](data-sources.md). Entrada principal: Glosa 06 trimestral del Minsal (PDF, por servicio de salud y especialidad); GES por problema de salud: Superintendencia de Salud; tasas base de inasistencia: literatura chilena (Medwave 2014, tesis U. de Chile 2024) como parámetros explícitos.
- La prensa nunca es dato de entrada.
- Los PDF fuente no se versionan en el repo (licencia no indicada): se guardan URL y sha256; las fixtures de tests serán extractos mínimos.
- CLAUDE.md citaba "más de 2,5 millones de personas según reportes de 2026", cifra no verificable en fuente primaria (corresponde a prensa de dic-2024). Se reemplazó por las cifras verificadas de la Glosa 06 III-2025.

---

## 5. Módulo de ingesta

**Fecha**: 2026-10-03

**Dependencias agregadas**:
- `httpx>=0.27` (ingestion): descargas con timeouts y reintentos; MockTransport permite tests sin red.
- `pdfplumber>=0.11` (ingestion): extrae palabras con coordenadas; `pypdf` no entrega posiciones y `pdfplumber.find_tables()` no reconstruye las tablas de la Glosa 06 (solo detecta encabezado y total).
- `polars>=1.0` (ingestion y shared): transformaciones y parquet sin depender de pyarrow; en shared, esquemas polars compartidos con synthetic.
- `fastexcel>=0.11` (ingestion): lector calamine de polars que lee el XLSX de la Superintendencia (6 MB, ~16.000 columnas declaradas) en ~0,3 s sin openpyxl.
- `typer>=0.12` (ingestion): CLI `prioriza-ingest` para orquestar descargas y transformaciones.

**Dependencias descartadas**:
- `tenacity`: reintentos implementados con bucle propio.
- `pyarrow`, `pypdf`, `openpyxl`: no son dependencias del proyecto (usados solo en `ingestion/tests/fixtures/make_fixtures.py` vía `uv run --with`).

**Decisiones**:
- **Fuentes con descargador**: `glosa06_2025q3`, `glosa06_2025q4`, `glosa06_2026q1` (PDF Minsal, sha256 fijo); `sis_ges_cases_2026q1` (XLSX Superintendencia, sha256 fijo); `minsal_establishments` (datos.gob.cl, dataset establecimientos-de-salud-vigentes, licencia CC0; resolvedor de recurso CKAN porque el CSV cambia de nombre semanalmente; caché máximo 7 días).
- **Literatura (E4)** no tiene descargador: irá a archivo de parámetros versionado cuando synthetic/noshow lo necesiten.
- **Esquemas**: tres en `shared/schemas.py`: `WaitlistRecord` (listas de espera Glosa 06; media y mediana como campos opcionales separados; grano national/health_service/specialty/ges_problem; `wait_basis` distingue espera desde derivación vs retraso sobre plazo GES), `GesCaseRecord` (casos GES acumulados e ingresos por problema de salud y asegurador; no encaja en `WaitlistRecord` porque no tiene tiempos de espera ni servicio), `HealthFacility` (catálogo; excluye dirección y teléfono por minimización).
- **Identidad de servicios**: 29 servicios de salud y sus códigos DEIS en `shared/health_services.py` con resolvedor de variantes de nombre.
- **Detección de tablas en Glosa**: por texto del título (regex), no por número, porque la numeración cambia entre trimestres.
- **Validación**: suma de registros por servicio y especialidad debe igualar la fila Total de cada tabla (se cumple exacto en los 3 trimestres); personas no se validan entre tablas porque no son sumables y el propio informe tiene inconsistencias. Si cambia el formato, `SchemaDriftError` con fuente y tabla en el mensaje.
- **Descartes por minimización**: desglose por sexo (tabla de GES retrasadas por servicio) y tramos de días.
- **Licencias y fixtures**: no se versionan PDF ni XLSX completos; fixtures son extractos mínimos (volcados de palabras de cada tabla, PDF de 1 página, XLSX reducido a 5 problemas, 15 filas del CSV con teléfono/dirección vaciados) con `MANIFEST.json` (URL, sha256 del original, metadatos) y script manual `make_fixtures.py` que no corre en CI.
- **Salidas**: `data/raw/<source_id>/<fecha>/` con `metadata.json` (URL, fecha, sha256) y `data/processed/<source_id>.parquet` + `metadata.json`; ambas ignoradas por git.

Resultado de `make ingest` (2026-10-03): glosa06_2025q3 274 filas, glosa06_2025q4 278, glosa06_2026q1 278, sis_ges_cases_2026q1 882, minsal_establishments 5.743 (388 sin coordenadas válidas). Cifras verificadas contra Glosa III-2025: CNE nacional 2.576.371 registros, mediana 242 días; GES retrasadas 80.022.


**Correcciones tras la revisión (reviewer, 2026-10-03)**:
- Las cifras de cada tabla de la Glosa se asignan a su columna por posición x del encabezado; un encabezado reordenado, una celda vacía o desplazada, o una etiqueta de problema GES que empieza con minúscula o dígito lanzan `SchemaDriftError`.
- Se valida la consistencia interna con columnas que luego se descartan: tramos de días = total (problemas GES), femenino + masculino + no definido = total (GES por servicio), razón publicada = registros / personas (tablas por servicio).
- Filas con 0 registros: media y mediana de días quedan en `None` (no hay espera que promediar), aunque la fuente imprima "-", "0" o "0,0".
- Descargas: se verifica la firma del archivo (`%PDF`, `PK`, CSV no HTML) antes de guardarlo; un error al parsear una fuente se reporta como fuente fallida sin detener `prioriza-ingest all`.

**Pendientes conocidos**:
- Caché: la carpeta es por día (un `--refresh` el mismo día sobrescribe), `metadata.json` no se escribe de forma atómica y no hay respaldo a caché vencida si falla la red.
- Descarga: los códigos 3xx se aceptan como éxito con un cliente sin redirecciones y no se respeta `Retry-After` en 429.
- Catálogo de establecimientos: hay coordenadas que no corresponden a la región declarada (dato de la fuente); falta un chequeo coordenadas vs región.

---

## 6. Población sintética y modelo de datos

**Fecha**: 2026-10-08

Diseño completo en [design/synthetic-plan.md](design/synthetic-plan.md); supuestos y calibración en [synthetic-data.md](synthetic-data.md).

**Dependencias agregadas**:
- `numpy>=2.0` (synthetic): `Generator`/`SeedSequence` con streams independientes por componente y muestreo vectorizado. No se agrega scipy: Φ⁻¹ (AS241) y la calibración por bisección son implementaciones propias.
- `synthetic` declara además `polars`, `psycopg[binary]`, `pydantic` y `typer`, que ya estaban en el lock.

**Decisiones del usuario** (2026-10-08):
1. Edad y previsión son supuestos no verificados (`verified: false` en `assumptions.json`). La previsión usa los conteos verificados de población inscrita en APS por tramo (FONASA, Cuenta Pública 2025, Tabla N°11), pero que la lista de espera replique esa composición es un supuesto no verificado (`insurance_waitlist_proxy`). Queda pendiente ingerir las tablas de edad y previsión de la Glosa 06.
2. Alcance GES: 20 problemas mapeados a especialidad, que cubren el 68 % de las garantías retrasadas. Los plazos del Decreto 29 (2025) siguen sin verificar.
3. Previsión en el generador de inasistencias: `baseline` sin efecto de previsión; `ses_gradient` solo como análisis de sensibilidad; `neutral` como control obligatorio en todo informe.

**Modelo de datos**:
- Enums como VARCHAR + CHECK (`native_enum=False`), más fáciles de migrar que tipos nativos de PostgreSQL.
- Cada población es una fila de `synthetic_run` con id uuid5 determinista (seed, tamaño, escenario, horizonte, fecha de referencia, hashes de objetivos y parámetros). Varias poblaciones conviven; `--replace` reemplaza una corrida en una sola transacción (si falla, la anterior queda intacta).
- La verdad sintética (`patient_latent`, `appointment_truth`) vive en tablas separadas y está prohibida como variable de cualquier modelo.
- Índices en todas las columnas FK (migración 0003): sin ellos el borrado en cascada de una corrida de 100.000 entradas no terminaba en minutos; con ellos tarda ~2 s.
- `appointment.specialty_code` (migración 0004) para que el historial sintético registre la especialidad atendida.

**Calibración**: la muestra estratificada de esperas se reescala para fijar la media y la mediana por grupo, lo que deforma levemente la lognormal; por eso C2 se cumple por construcción y no valida la forma de la distribución. Los objetivos se derivan de `data/processed` y se versionan en `synthetic/src/synthetic/targets/calibration_targets.json` con su procedencia (sha256), para que los tests no dependan de red ni de los parquet. Métrica categórica: distancia de variación total con la cota de redondeo del método de Hamilton (los márgenes son deterministas, por eso no se usa chi-cuadrado). Tolerancias en `synthetic-data.md`.

**Decisiones diferidas a P4 (modelo de inasistencias)**, según la revisión de ml-engineer ([design/synthetic-noshow-review.md](design/synthetic-noshow-review.md)):
- Techo práctico de AUC ~0,63-0,65 con variables observables frente a 0,74 del oráculo: casi toda la señal está en la fragilidad latente y el historial (Poisson λ = 1,5) aporta poco. Decidir si se sube λ o se amplía la ventana, y reportar el techo.
- El historial no tiene término de espera (no hay episodios pasados); el efecto de la espera no se puede aprender desde el historial.
- Separación técnica de la verdad sintética (lista de tablas permitidas y test en `noshow/`).
- Si el modelo puede usar `age_group`; por defecto se excluyen comuna y previsión y el servicio se permite como efecto fijo.
- El proceso es estacionario: un split temporal no prueba robustez a deriva; evaluar un parámetro de deriva.
- Para medir equidad por comuna se necesita N ≥ 100.000, un n mínimo por comuna y estimadores con contracción; el generador no tiene efecto propio de comuna.

---

## 7. Puntaje de priorización

**Fecha**: 2026-10-08

Diseño en [design/priority-plan.md](design/priority-plan.md); fórmula, reglas y ejemplos en [priority.md](priority.md).

**Dependencias agregadas**:
- `pyyaml>=6.0` (priority): reglas declarativas en YAML con `safe_load`; ya estaba en el lock como dependencia transitiva. Se usa un cargador que rechaza claves duplicadas, porque PyYAML las sobrescribe en silencio.
- `types-PyYAML` (dev): stubs para `mypy --strict`.
- Se descartó `ruamel.yaml` (solo aportaría preservar comentarios).

**Decisiones**:
- Puntaje determinista sin ML: suma ponderada de componentes normalizados a [0, 1], escalada a 0-100. Componentes por defecto: prioridad clínica declarada (50), días de espera lineal saturada en 730 días (35) y cercanía al plazo GES con rampa de 60 días (15). Los pesos son una propuesta de ejemplo, no una norma clínica validada.
- La prioridad clínica es un dato de entrada: el módulo la lee y la devuelve sin modificarla.
- Lista blanca de campos (`clinical_priority`, `wait_days`, `days_to_ges_deadline`). Sexo, etnia, nacionalidad, comuna, previsión, grupo etario, servicio, establecimiento, especialidad, procedimiento, problema GES y la probabilidad de inasistencia están prohibidos como factores, con el motivo en el mensaje de error. Comuna, previsión y grupo etario solo se usan para medir equidad. La entrada del cálculo (`PriorityInput`) no tiene esos campos.
- El servicio, la especialidad y el tipo de atención solo definen la cola en la que compite cada entrada (partición), nunca el puntaje.
- Regla dura GES (decisiones del usuario, 2026-10-08): las garantías vencidas y las que vencen en 14 días o menos van antes que el resto, ordenadas por plazo (EDF); los casos p1 van antes que todo (`yield_to_priorities: [p1]`). Configurable y desactivable en el YAML.
- Orden total y estable: grupo de cesión, nivel estricto, plazo, puntaje, fecha de ingreso, id.
- `yield_to_priorities` solo puede ser vacío o un prefijo contiguo de p1..p4, para que ninguna configuración anteponga una prioridad clínica a otra mejor; y solo puede no estar vacío con la regla GES activa (sin ella no hay nivel estricto al que ceder). Decisión de la sesión principal tras la revisión ([design/priority-review.md](design/priority-review.md)).
- El cargador YAML rechaza claves duplicadas, merge keys y alias; los números son estrictos y los pesos tienen cota superior; las etiquetas no pueden nombrar atributos prohibidos.
- Fecha de referencia `as_of` siempre explícita.
- Cada conjunto de reglas tiene `rules_version` y un `digest` sha256, que se registran con cada ranking.
- Riesgo conocido: la longitud del plazo GES depende del problema de salud y por eso se correlaciona con el sexo; no se puede quitar sin ignorar la garantía legal. Se mitiga no usando el problema como factor y reportando diferencias de puesto por grupo.

---

## 8. Routing de modelos por niveles

**Fecha**: 2026-10-08

**Decisión** (del usuario):
- Se adopta un routing de modelos en 3 niveles (secciones 2 a 4 de [CLAUDE.md](../CLAUDE.md)): Tier 1 en Claude nativo (`claude`), Tier 2 en `claude-ds` / `claude-qwen` y Tier 3 en `claude-kimi` / `claude-qwen`, vía LiteLLM local.
- Ante conflicto, el routing por niveles manda sobre la tabla de subagentes (opus/sonnet/haiku) y sobre la sección "Metodología de Selección de Modelos".
- `TASK_PLAN.md` es el tablero de transferencia entre agentes; cada agente actualiza el estado de su paso y deja un log breve antes de ceder el control.

**Justificación**:
- Preservar el presupuesto de tokens de Claude nativo para arquitectura, optimización y lógica crítica, y mover tareas de volumen (tests, documentación, escaneo) a modelos más baratos.

---

## 9. Modelo de inasistencias

**Fecha**: 2026-10-08

**Dependencias agregadas** (solo en `noshow`):
- `scikit-learn`: definido en CLAUDE.md para el modelo de inasistencias (pipelines, regresión logística, `HistGradientBoostingClassifier`, `CalibratedClassifierCV` con `FrozenEstimator`, que exige >= 1.6).
- `joblib`: persistencia de los pipelines ajustados; ya es dependencia de scikit-learn y es su formato recomendado. Usa pickle: solo se cargan artefactos propios.
- `numpy`, `polars`, `typer`: ya usados en el workspace (`synthetic`); se declaran porque `noshow` los importa directamente. scikit-learn >= 1.4 acepta DataFrames de polars, así que no se agrega pandas.
- `synthetic` (miembro del workspace): la CLI calcula las huellas vigentes de objetivos y supuestos del generador para entrenar solo con corridas generadas con ellos. `noshow` no importa nada más de `synthetic`.

**Decisiones**:
- **Variables**: especialidad, tipo de atención, día de la semana, franja horaria local, `lead_days` y conteos de asistencias e inasistencias previas del paciente. Los conteos solo usan citas con `scheduled_start` estrictamente anterior a la fecha de agendamiento (`scheduled_start - lead_days`), para que ninguna variable use información posterior a la decisión. Las variables constantes en entrenamiento se descartan y se registran (la franja horaria es constante en el historial sintético).
- **Excluidas**, con motivo en `noshow.features.EXCLUDED_FEATURES` y en `results/noshow.json`: sexo, etnia y nacionalidad (protegidas; no existen en el sintético), `age_group` (no está en la lista permitida; concentraría el sobreagendamiento en 15-44 años), previsión, comuna y servicio de salud (proxies de nivel socioeconómico, etnia y nacionalidad), `duration_min` (delata el procedimiento solo en IQ), prioridad clínica y la verdad sintética. `wait_days` y distancia están permitidas pero no existen en el historial (A2 de la revisión del generador); `wait_days` entra automáticamente cuando tenga valores en entrenamiento.
- **Lista de tablas permitidas** (`noshow.data.FEATURE_TABLES`): las features solo leen `appointment`, `waitlist_entry` y `catalog_specialty`. `patient` se lee solo para equidad y `appointment_truth` solo para la referencia del oráculo, con funciones separadas y tests que lo verifican (cierra M1).
- **Split temporal en tres bloques**: entrenamiento hasta `calibración`, calibración 120 días y prueba los últimos 180 días del historial. Los hiperparámetros son fijos (sin búsqueda). `early_stopping` del boosting queda apagado porque usaría una validación aleatoria.
- **Calibración**: isotónica si la clase minoritaria del conjunto de calibración tiene >= 1000 casos; sigmoide si no. La isotónica no impone forma y con miles de eventos no sobreajusta; con pocos, Platt es más estable. Se reportan también las métricas sin calibrar, aunque la calibración empeore alguna.
- **Modelo principal**: el de menor Brier en el conjunto de calibración entre cuatro candidatos: logística y boosting, con y sin calibrar. Los sin calibrar no vieron ese conjunto, así que su Brier ahí es honesto; los calibrados se miden con predicciones fuera de pliegue (5 bloques contiguos). Así la calibración se aplica solo si mejora. Con seed 42 y n 100.000 ganó la logística sin calibrar (la isotónica absorbe la tasa del bloque de calibración, 15,2 %, y sobrepredice en prueba, 14,5 %). El usuario confirmó (2026-10-08) dejar el modelo sin calibrar como principal en vez de forzar la calibración. El conjunto de prueba no participa en ninguna elección.
- **Especialidad como proxy**: se mantiene porque está en la lista permitida, aunque las especialidades pediátricas delatan el grupo 0-14 (V de Cramér 0,32 en entrenamiento) y en datos reales algunas delatarían el sexo. La fuerza de cada variable como proxy de cada atributo de equidad se publica en `results/noshow.json` (`features.proxy_strength_train`).
- **Predicción de citas futuras**: `build_candidate_features(candidatas, historial, ...)` arma las variables de citas sin resultado (las que propone el programador) con el historial observado; `build_features` es el mismo cálculo aplicado a las citas observadas, más la etiqueta.
- **Comparación con el baseline** (tasa histórica por especialidad, contraída con m = 20 hacia la tasa global): diferencia de Brier con IC 95 % por bootstrap de pacientes, porque las citas de un mismo paciente comparten la fragilidad latente.
- **Persistencia**: `models/noshow/<run_id>/noshow_model.joblib` + `metadata.json` (versión del modelo = huella de configuración, columnas e hiperparámetros de los pipelines + `dataset_sha256`; versión de datos, límites del split y versiones de librerías). `models/` no se versiona; `results/noshow.json` sí.
- **Selección de corrida**: `prioriza-noshow train` usa la única corrida de `data/synthetic/` con esa semilla, tamaño y escenario y con las huellas vigentes del generador (`targets_sha256`, `params_sha256`). Si no hay ninguna o hay varias, falla (`--run-dir` la fija); nunca elige por fecha de archivo.

**Limitaciones aceptadas** (ver `docs/noshow-model-card.md`): techo de AUC ~0,63-0,65 por la poca historia por paciente (A3, λ = 1,5 sin cambios); el modelo no ve servicio ni edad, por lo que subestima Arica (−4,9 pp) e Iquique (−4,3 pp) y sobreestima 65+ (+2,3 pp) frente a la verdad sintética.

---

## 10. Programador CP-SAT

**Fecha**: 2026-10-08

Formulación completa en [scheduler-formulation.md](scheduler-formulation.md); esta sección registra las dependencias y las decisiones tomadas al implementarla.

**Dependencias agregadas** (solo en `scheduler`):
- `ortools>=9.15`: CP-SAT, definido en CLAUDE.md. La API de Python se consultó en la versión instalada (`cp_model.py` y sus stubs `cp_model_helper.pyi`, que traen `py.typed` y pasan `mypy --strict`) y en `sat_parameters.proto` de la etiqueta v9.15. Trae como dependencias `protobuf`, `numpy`, `absl-py`, `immutabledict`, `typing-extensions` y `pandas` (esta última solo por su API de series; el programador no la usa).
- `polars`, `pydantic`, `typer`, `numpy`: ya estaban en el lock; se declaran porque `scheduler` los importa.
- `priority` y `noshow` (miembros del workspace): `priority` para el puntaje y el orden de P4; `noshow` solo en los módulos de borde (`adapters`, `cli`) para la probabilidad de inasistencia. `noshow` no tiene `py.typed`, así que esos imports llevan `# type: ignore[import-untyped]`. El núcleo (`instance`, `prepare`, `cpsat`, `solve`, `plan`, `greedy`, `risk`) no importa ni `noshow` ni scikit-learn.

**Decisiones de implementación** (cambian o precisan la formulación; el documento ya está actualizado):
- **Modo determinista con un solo hilo.** Con `solver.deterministic = true` (por defecto) se usa `num_workers = 1` y `max_deterministic_time`. La formulación proponía `interleave_search` con 8 hilos, que también es determinista, pero en el subproblema mayor de la corrida canónica llegó a la brecha de 0,1 % después que la búsqueda secuencial (2,4 s frente a 0,35 s) y excedió su límite determinista (2,3 frente a 0,5), porque solo lo revisa entre lotes. Con `deterministic = false` se usan 8 hilos con límite de tiempo real.
- **`linearization_level = 2`** (configurable). En los dos subproblemas mayores de la corrida canónica, la fase 3a pasó de `FEASIBLE` a los 9-11 s reales a `OPTIMAL` en 1,3-2,2 s, y la fase 3b obtuvo mejor cota con menos tiempo real. La relajación LP más fuerte ayuda a las restricciones de capacidad tipo mochila y a las de sobrecupo con indicador.
- **En modo determinista, el tiempo límite está en unidades deterministas**, no en segundos de reloj; el tiempo real puede excederlo. El informe registra ambos por fase y subproblema.
- **`S0` queda fijo también en la fase 4** cuando no hay fase 3b: el equilibrio solo cambia bloques, no quién tiene cupo. Antes de esta corrección la fase 4 podía cambiar entradas con igual puntaje total, y la verificación §9.3 lo detectó en la corrida canónica.
- **Pistas completas y canónicas.** Cada fase recibe una pista para todas las variables (también `w`, `util` y máximo/mínimo), llevada a la forma que exigen las restricciones de simetría; sin eso, CP-SAT terminaba en `UNKNOWN` en la segunda pasada de 3b y en la fase 4.
- **Clases de simetría sin `p`** en las fases sin sobrecupo, para que las fases 1-3a no dependan de la probabilidad de inasistencia.
- **Filtro de candidatos**: `O_b` nominal en `K_q` aunque el sobrecupo esté apagado, y una segunda señal de frontera (capacidad libre usable por una entrada descartada) que detecta colas donde varias entradas de un mismo paciente agotan los candidatos. Ambas las encontraron los tests de propiedad.
- **GES `G^od` con `as_of ≤ D_g < horizon_start`**: se informa como incumplida (`deadline_before_first_block`) aunque se agende, porque el plazo legal ya no se puede cumplir. La formulación tenía dos reglas contradictorias (§6.2 y §7) y quedó la de §7.
- **Causas posteriores `decomposition` y `overbooking_interaction`** (§7): casos con cupo libre que no son error porque el respaldo de descomposición o el plan con sobrecupo no son exactos para GES.
- **Respaldo por semana** cuando una especialidad supera `max_pairs_per_subproblem` (pedido del usuario), con obligación GES de "última oportunidad". En la corrida canónica de 4 semanas no se activa.
- **Persistencia sin tocar la lista**: `--persist` guarda `schedule_run` (pendiente de revisión) y sus `appointment`, pero no cambia `waitlist_entry.status`, porque el plan no está aprobado.
- **Corrección del ejemplo §13**: la variante con GES infactible tenía mal el objetivo (16.772). Cambiar el plazo de E cambia su puntaje P4, y el objetivo correcto es 17.271.


## 11. Benchmark y rendimiento del programador

**Fecha**: 2026-10-09

Técnicas en [scheduler-formulation.md §8.6](scheduler-formulation.md#86-técnicas-de-rendimiento-p9); resultados en [scheduler-performance.md](scheduler-performance.md) y `results/scheduler-benchmark.json` (`make bench-scheduler`).

**Dependencias**: `synthetic` (miembro del workspace) pasa a ser dependencia directa de `scheduler`, solo para `scheduler.bench`, que genera las poblaciones del benchmark con `synthetic.pipeline.generate`. No agrega nada al entorno: `scheduler` ya dependía de `noshow`, que depende de `synthetic`. Sin `py.typed`, sus imports llevan `# type: ignore[import-untyped]`. El núcleo del programador sigue sin importarlo.

**Decisiones**:
- **Oferta del benchmark generada para el horizonte.** Con la oferta de 26 semanas del generador, las corridas de 1.000 y 10.000 entradas tienen 0-1 y 25-59 bloques en las primeras 2-4 semanas (artefacto de `_week_slots`, formulación §11.2): el benchmark mediría problemas triviales. El benchmark genera sus propias corridas con `horizon_weeks` del generador igual a las semanas del plan (la misma oferta semanal, repartida en el horizonte), en `data/bench/` para no crear corridas ambiguas en `data/synthetic/` (`find_run_dir` exige una por semilla, tamaño y escenario). No corrige el generador; esa corrección sigue pendiente antes de la simulación.
- **La corrida de 1.000 no pasa la calibración estricta del generador** (dos chequeos de medianas nacionales, por tamaño de muestra). Se usa igual, porque el benchmark mide al programador y no la calibración; el JSON registra los chequeos que fallan.
- **Técnicas activas por defecto, con interruptores solo para medir.** Ninguna cambia el valor óptimo de una fase (lo prueba `test_techniques_do_not_change_optimum` con brecha 0). Con brecha positiva o límite de tiempo, sí pueden cambiar el plan entregado, en cualquier dirección: el benchmark lo reporta por variante.
- **`canonicalize` no hace nada si `symmetry_breaking` está apagado**: con simetrías apagadas, permutar entradas idénticas podía sacar de la pista a una entrada de `S0` (hallazgo de la revisión).
- **Comparación con la voraz sin sobrecupo.** El orden lexicográfico de §9.5 (p1 agendados, GES cumplidas, suma de `c_ib`) se evalúa con `optimized` sin sobrecupo, igual que la voraz; las diferencias del plan con sobrecupo se informan una a una, sin agregarlas.
- **Tiempo determinista como medida principal.** El tiempo real de un mismo plan determinista varió entre 63 y 98 s en la celda mayor durante el desarrollo (M1 con otros procesos activos). El benchmark registra el tiempo real de todo `solve` (mediana de 3 repeticiones de la variante completa; las ablaciones corren una vez) y el tiempo determinista de CP-SAT, del plan y total con las pasadas descartadas por la frontera.

## 12. Simulación de políticas

**Fecha**: 2026-10-09

Diseño en [simulation-design.md](simulation-design.md); resultados en `results/simulation.json` (`make simulate`).

**Dependencias**: `simpy` en `simulation`: motor de eventos discretos del stack declarado en CLAUDE.md; sin dependencias propias. `simulation` depende además de los miembros `synthetic` (verdad de inasistencia, celdas de llegada y oferta), `priority`, `noshow` y `scheduler`.

**Decisiones**:
- **Asistencia con la probabilidad verdadera del generador**, nunca con la predicha: el programador decide con la predicha y el mundo responde con la verdadera. La verdad se calcula solo en `simulation/truth.py`.
- **Llegadas por la ley de Little** (θ del generador por celda) a falta de series públicas de ingresos; los atributos se copian de filas del stock de la misma celda y condición GES, con paciente y fragilidad nuevos.
- **Oferta estacionaria propia** con los minutos por semana de cada celda del generador, en vez de los `slot` del generador (artefacto §11.2). El generador sigue sin corregirse; la simulación ya no depende de esa corrección.
- **Números aleatorios comunes** entre políticas (llegadas y un uniforme por entrada e intento de asistencia) para comparar por réplica de forma pareada.
- **Horizonte deslizante** de 4 semanas con una semana confirmada (formulación §8.3); anticipación de las citas de 7 a 11 días.
- **Dos inasistencias = egreso** (causal de la Glosa 06); sin abandono por defecto.

---

## Referencias
- [CLAUDE.md](../CLAUDE.md): Stack y convenciones del proyecto.
