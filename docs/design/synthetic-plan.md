# Plan de diseño: generador sintético y modelo de datos (P3)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Autor: architect (opus), 2026-10-03. Aprobado por la sesión principal con las decisiones del usuario (sección 10). Es el contrato entre implementer-A (`synthetic/`), implementer-B (`shared/db`), test-writer y docs-writer.

## 0. Hallazgos sobre los datos

- Glosa III-2025 (`glosa06_2025q3.parquet`) es la referencia de calibración.
- No hay cruce servicio × especialidad. Las tablas por especialidad no traen tiempos de espera.
- Media y mediana de espera solo por (servicio, CNE/IQ) y nacional: CNE 341/242 días, IQ 394/264.
- `cne_by_service` e `iq_by_service` son listas no GES (2.576.371 + 417.561 registros) con `persons_count` (razón registros/personas por servicio).
- GES: solo garantías retrasadas (80.022), con retraso sobre el plazo por problema en `ges_delayed_by_problem` (81 de 87 filas con media y mediana) y conteo por servicio en `ges_delayed_by_service`. No hay stock GES dentro de plazo ni plazos legales en los datos.
- Subtipos nacionales: médica 2.051.482, dental 524.889, IQ mayor 302.093, IQ menor 115.468.
- Edad, previsión y egresos no se extrajeron en la ingesta (la Glosa sí trae edad y previsión).
- CNE: 80 especialidades (66 médicas, 14 dentales), 7 con < 100 registros. IQ: 12 especialidades con taxonomía propia (p. ej. "TRAUMATOLOGIA" en IQ vs "TRAUMATOLOGIA Y ORTOPEDIA" en CNE). No se armonizan.
- `sis_ges_cases_2026q1` trae `ytd_new_cases` FONASA 2025 por problema (año completo al 2025-12-31).
- Establecimientos: 345 comunas SNSS; comunas 13101, 13201 y 13123 pertenecen a más de un servicio; Arauco no tiene hospital de alta complejidad.
- 7 filas GES con media ≤ mediana: la lognormal no ajusta en ellas (piso de σ).

## 1. Población y entradas

`--size N` = número de entradas (registros), N ≥ 1.000. Fecha de referencia `as_of` = 2025-09-30 (`--as-of` desplaza todas las fechas sin cambiar los estadísticos).

**Universo real U = CNE ∪ IQ ∪ GES_mapeado.**
- `L_GES = L_retrasadas + L_en_plazo`.
- `L_retrasadas` = suma de `waiting_count` de los problemas mapeados.
- `L_en_plazo,p = ytd_new_cases_fonasa_2025[p] · plazo_p / 365 · 0,5` (ley de Little con resolución uniforme dentro del plazo: tiempo medio en lista = plazo/2). SUPUESTO.
- Solo problemas GES mapeados a (tipo, especialidad) en `assumptions.json` (15-20: cataratas → IQ Oftalmología, colecistectomía → IQ Cirugía digestiva, endoprótesis de cadera → IQ Traumatología, hiperplasia de próstata → IQ Urología, cánceres de mama, colorrectal, etc.). Los de APS se excluyen y se reporta la cobertura sobre los 80.022.

**Asignación determinista con márgenes exactos** (método de Hamilton = resto mayor, luego barajado):
1. N → {CNE, IQ, GES} en proporción a L.
2. Dentro de cada tipo, entradas → servicio (`cne_by_service`, `iq_by_service`, `ges_delayed_by_service`, este último aplicado también a GES en plazo, SUPUESTO).
3. Vector de etiquetas aparte: CNE subtipo → especialidad (`cne_medical_by_specialty`, `cne_dental_by_specialty`), IQ → especialidad (`iq_by_specialty`), GES → problema. Se permuta con el RNG y se une.

Márgenes de servicio y especialidad exactos para cualquier N; cruce aproximadamente independiente (SUPUESTO). Con N chico, especialidades con N·p < 0,5 quedan en 0 y se avisa.

**Variables:**

| Variable | Origen | Regla |
|---|---|---|
| health_service_code | `*_by_service.waiting_count` | Hamilton |
| care_type / care_subtype | `noges_national_by_subtype` | Médica/dental exacto. Mayor/menor según subtipo del procedimiento (catálogo), objetivo blando 72,3 % mayor |
| specialty | `cne_medical/dental_by_specialty`, `iq_by_specialty` | Hamilton + barajado |
| procedure | SUPUESTO (`assumptions.procedures`) | CNE: un procedimiento "consulta nueva" por especialidad. IQ: 1-3 procedimientos genéricos por especialidad con duración (min) y subtipo |
| Pacientes por entrada | `persons_count` por (servicio, tipo) | Pools por (servicio, tipo): P = round(E/r). Primeras P entradas una por paciente; las E−P restantes a pacientes al azar con edad compatible, sin repetir especialidad (hasta 5 reintentos). SUPUESTO: sin solapamiento CNE/IQ |
| commune_code | `minsal_establishments` | Peso por par (comuna, servicio): CESFAM/CGU/CGR × 1 + CECOSF × 0,5 + PSR × 0,1, solo SNSS operativos (SUPUESTO: proxy de población inscrita). Hamilton dentro de cada servicio |
| establishment_code | Hospitales SNSS operativos del servicio | Peso alta = 2, mediana = 1 |
| age_group (`0_14`, `15_19`, `20_44`, `45_64`, `65_plus`) | SUPUESTO (`verified: false`) | Especialidades pediátricas (regex PEDIATR, INFANTIL, DEL NINO, ADOLESCENTE): {0,9, 0,1, 0, 0, 0}. Resto: {0,06, 0,04, 0,25, 0,33, 0,32}. Hamilton por clase |
| insurance (`fonasa_a`, `fonasa_b`, `fonasa_c`, `fonasa_d`, `other`) | SUPUESTO (`verified: false`) | Provisorio 0,25 / 0,33 / 0,17 / 0,23 / 0,02. Hamilton, independiente de la edad (SUPUESTO) |
| clinical_priority (`p1`..`p4`) | SUPUESTO, dato de entrada sintético; el sistema nunca la infiere | CNE {0,05, 0,15, 0,40, 0,40}; IQ {0,08, 0,22, 0,40, 0,30}; GES oncológico {0,4, 0,4, 0,2, 0}. Independiente de la espera |
| is_ges, ges_problem_code, ges_deadline | `ges_delayed_by_problem` + `deadline_days` SUPUESTO / por verificar (Decreto GES) | `ges_deadline = entry_date + plazo` |
| entry_date | Media y mediana por (servicio, tipo) | Fórmula abajo |
| Historial de asistencia | Sección 2 | Filas de `appointment` con origen `history` |

No se generan sexo, etnia ni nacionalidad.

**Fecha de ingreso (espera W, días):**
- Lognormal: μ = ln M; σ = √(2·ln(m/M)) si m > 1,001·M; si no, σ = 0,1 (piso, con aviso). (M = mediana, m = media.)
- Muestreo estratificado por grupo de n entradas: u_i = (π(i) + v_i)/n, π permutación aleatoria, v_i ~ U(0,1); W_i = exp(μ + σ·Φ⁻¹(u_i)), recortado a [1, 3650], redondeado a días.
- Φ⁻¹ vectorizado (AS241) en numpy, testeado contra `statistics.NormalDist`. Sin scipy.
- `entry_date = as_of − W`.
- GES retrasadas: W = plazo + D, D lognormal ajustada a media y mediana del problema (si falta, nacional 136/71). Tope 3650 − plazo.
- GES en plazo: W = U(0, plazo), SUPUESTO.
- La especialidad no modula la espera (sin dato).

## 2. Inasistencias sintéticas (`noshow_truth.py`)

logit p_ij = α_{s,c} + γ_spec(j) + β_age[a_i] + β_ins[ins_i] + β_wait·log2(W_ij / M_{s,c}) + β_lead·log2(1 + lead_días/7) + u_i, con u_i ~ N(0, σ_u²), σ_u = 0,8.

- Tasas objetivo t_{s,c}:
  - CNE: 15,6 % nacional (E4b, Sepúlveda), Arica 22 %, Iquique 21 % (E4b); resto escalado con k común para que el promedio ponderado por L dé 15,6 %. Chequeo: todas dentro del rango regional de Salinas (8,8-20,2 %, E4a); Arica (22 %) queda sobre ese techo: se documenta (E4b > E4a), no falla.
  - IQ: 5 % SUPUESTO (suspensión 6,4-12,9 %, E4d, ~50 % por causas del paciente).
  - data-researcher debe traer la tabla por servicio de Sepúlveda.
- Calibración de α_{s,c}: bisección para que la media de p sobre las entradas sintéticas, con lead de referencia de 28 días, sea t_{s,c}. Tolerancia 1e-4.
- Escenarios (`--scenario`):
  - `neutral`: β_age = β_ins = γ = 0. Control obligatorio.
  - `baseline` (por defecto): β_age = {0_14: +0,10; 15_19: +0,35; 20_44: +0,30; 45_64: 0; 65_plus: −0,20}; γ_spec ~ N(0, 0,3²) con stream propio; β_wait = +0,15; β_lead = +0,10; β_ins = 0.
  - `ses_gradient`: baseline + β_ins = {fonasa_a: +0,2; fonasa_b: +0,1; fonasa_c: 0; fonasa_d: −0,1; other: 0}. Solo análisis de sensibilidad.
  - Todos los valores son SUPUESTOS con justificación en el JSON.
- Historial: k ~ Poisson(1,5) citas pasadas por paciente (máx. 6), fecha U[as_of − 730, as_of − 1], especialidad de una de sus entradas, lead U{7..90}; término de espera 0 en el historial; resultado Bernoulli(p) → `attended`/`no_show`. Correlación entre citas solo vía u_i (sin β_hist directo).
- Verdad separada: u_i en `patient_latent.noshow_frailty`, p en `appointment_truth.true_noshow_prob`; prohibidas como feature. La simulación recalcula p futura con los parámetros de `synthetic_run.params`.
- Equidad: el generador usa edad (y previsión solo en `ses_gradient`); la comuna entra solo vía servicio. El futuro modelo no podrá usar comuna ni previsión. La evaluación debe medir por comuna, grupo etario y previsión: (a) calibración (p predicha vs `appointment_truth`), (b) daño (tasa de sobreagendamiento con colisión y espera adicional). `neutral` comprueba que la tubería no crea disparidad sola; puede haber disparidad por servicio (Arica e Iquique) y se reporta.
- Chequeo blando: E[p²] en CNE ≈ 82.420 / 2.707.426 = 3,0 % ± 1,5 pp (egresos por "dos inasistencias"); solo aviso.

## 3. Oferta (`capacity.py`)

- Throughput por ley de Little: θ_{s,c} = 7·L_{s,c} / m_{s,c} (entradas/semana). Nacional ≈ CNE 52.900/sem, IQ 7.420/sem (chequeo cruzado con egresos de la Glosa). GES: θ = ytd_new_cases_p / 52 × participación del servicio.
- Escala: θ̃ = θ · N / L_U · `capacity_multiplier` (1,0). θ̃ se reparte entre especialidades en proporción a las entradas sintéticas de (servicio, especialidad).
- Minutos/semana: CNE θ̃ / (1 − t_s) × `consult_min` (20, SUPUESTO por especialidad); IQ θ̃ / (1 − t_IQ) × E[duración + 30 recambio] / 0,85 (utilización).
- Sesiones: CNE 240 min (08:30-12:30 / 14:00-18:00); pabellón bloques de 360 min (08:00-14:00), lunes a viernes, America/Santiago (`zoneinfo`). Total en horizonte H (`--horizon-weeks`, 26): S = Hamilton sobre (servicio, especialidad) de H·min/sesión. Sesión k en semana ⌊k·H/S⌋, día y AM/PM rotativos, sin RNG. Con N chico algunas especialidades quedan sin sesiones: se reporta.
- Recursos: `specialist_agenda` por (hospital, especialidad); `operating_room` por hospital con n = max(1, ⌈bloques semanales / 5⌉); bloque asignado a especialidad con Hamilton por minutos.
- Targets guardan λ_in = θ + ΔL/semana (tendencia III-2025 → I-2026) para la simulación.

## 4. Modelo de datos (`shared/src/shared/db/`)

Convenciones: enums `StrEnum` en `enums.py`, mapeados con `sa.Enum(..., native_enum=False, create_constraint=True, length=32)`. Reutilizar `CareType` y `CareSubtype` de `shared.schemas`. PK `sa.Uuid`. Tablas por corrida con `run_id` FK → `synthetic_run.id` ON DELETE CASCADE. Timestamps `timestamptz`. JSONB solo en `params`.

**Enums nuevos** (valores en minúscula):
- `AgeGroup`: `0_14`, `15_19`, `20_44`, `45_64`, `65_plus` (nombres de miembro válidos en Python, p. ej. `AGE_0_14 = "0_14"`)
- `Insurance`: fonasa_a, fonasa_b, fonasa_c, fonasa_d, other
- `ClinicalPriority`: p1, p2, p3, p4
- `EntryStatus`: waiting, scheduled, resolved, removed
- `ResourceKind`: operating_room, specialist_agenda
- `AppointmentStatus`: scheduled, attended, no_show, cancelled
- `AppointmentOrigin`: history, scheduler, simulation
- `Policy`: fifo, priority, optimized
- `RunStatus`: loading, ready, failed
- `ReviewStatus`: pending, approved, rejected
- `NoShowScenario`: neutral, baseline, ses_gradient

**Catálogos globales** (upsert `on_conflict_do_update`):
- `HealthService` → `health_service`: code SmallInt PK; name String(80) único.
- `Commune` → `commune`: code String(5) PK; name; region_code SmallInt.
- `Establishment` → `establishment`: code String(16) PK; name; health_service_code FK; commune_code FK; complexity String(32) nulo.
- `Specialty` → `specialty`: code String(80) PK (slug, p. ej. `cne_medical:oftalmologia`); name String(160); care_type; care_subtype nulo. Único (name, care_type, care_subtype) con `postgresql_nulls_not_distinct=True`.
- `GesProblem` → `ges_problem`: code SmallInt PK; name; deadline_days SmallInt nulo; specialty_code FK nulo; care_type nulo.
- `Procedure` → `procedure`: code String(80) PK; specialty_code FK; name; care_subtype nulo; duration_min SmallInt CHECK > 0; ges_problem_code FK nulo.

**Versionado:**
- `SyntheticRun` → `synthetic_run`: id = uuid5(NS, "seed:size:scenario:horizon:as_of:targets_sha:params_sha") (determinista); seed BigInt; size Int; scenario; as_of Date; horizon_weeks; reference_source_id; targets_sha256, params_sha256, dataset_sha256 Char(64); generator_version; params JSONB; status; created_at.
- Reemplazar = DELETE de la corrida (cascada) + carga nueva con `--replace`. Sin `--replace`, si la id existe, falla. Varias poblaciones conviven. La API usa la última con status = ready.

**Tablas por corrida:**
- `Patient` → `patient`: id Uuid PK = uuid5(run_id, "patient:i"); run_id; health_service_code FK; commune_code FK; age_group; insurance. Índices (run_id, health_service_code), (run_id, commune_code), (run_id, age_group, insurance). Sin nombre, RUT, fecha de nacimiento ni sexo.
- `PatientLatent` → `patient_latent`: patient_id PK FK CASCADE; run_id; noshow_frailty Float. Comentario: "verdad sintética, prohibido como feature".
- `WaitlistEntry` → `waitlist_entry`: id; run_id; patient_id FK CASCADE; health_service_code; establishment_code; specialty_code; procedure_code; care_type; care_subtype nulo; clinical_priority; is_ges Bool; ges_problem_code nulo; ges_deadline Date nulo; entry_date Date; status (default waiting); resolved_on nulo. CHECK is_ges ⇔ (ges_problem_code y ges_deadline no nulos). Índices (run_id, status), (run_id, health_service_code, specialty_code), (patient_id), (run_id, ges_deadline) WHERE is_ges.
- `Resource` → `resource`: id; run_id; kind; establishment_code; health_service_code; specialty_code nulo (nulo en pabellón); label String(64). Índice (run_id, health_service_code, kind).
- `Slot` → `slot`: id; run_id; resource_id FK CASCADE; specialty_code; start_at timestamptz; duration_min CHECK > 0; unit_min SmallInt nulo (minutos por consulta en CNE; nulo en pabellón). Un slot es un bloque de sesión. Único (resource_id, start_at). Índice (run_id, specialty_code, start_at).
- `Appointment` → `appointment`: id; run_id; patient_id FK; entry_id FK nulo; slot_id FK nulo; schedule_run_id FK nulo; origin; status; scheduled_start timestamptz; duration_min; lead_days nulo; is_overbooked Bool (default false); predicted_noshow_prob Float nulo CHECK 0..1. CHECK (origin = 'history' OR slot_id IS NOT NULL). Índices (run_id, patient_id, scheduled_start), (slot_id), (schedule_run_id), (entry_id).
- `AppointmentTruth` → `appointment_truth`: appointment_id PK FK CASCADE; run_id; true_noshow_prob Float. Comentario: "verdad sintética, prohibido como feature".
- `ScheduleRun` → `schedule_run`: id; run_id; policy; horizon_start; horizon_end; seed; params JSONB; solver_status nulo; objective_value nulo; review_status (default pending: todo plan requiere revisión humana); code_version; created_at; finished_at nulo.
- `PolicyResult` → `policy_result`: id; run_id; experiment_id Uuid (indexado); schedule_run_id nulo; policy; metric String(64); group_dimension nulo; group_value nulo; value Float; n Int; ci_low, ci_high nulos; created_at. Único (experiment_id, policy, metric, group_dimension, group_value) nulls not distinct.

**Archivos:** `session.py` con `get_engine(url: str | None = None) -> Engine` (lru_cache) y `session_factory() -> sessionmaker[Session]`. Migración `versions/0002_core_model.py` (down_revision "0001"), revisada a mano; downgrade borra todo.

## 5. Validación de calibración

Objetivos versionados en `synthetic/src/synthetic/targets/calibration_targets.json`, generados con `prioriza-synth build-targets --processed-dir data/processed`. JSON canónico (claves ordenadas, sin timestamp). Contenido: `sources[]` {source_id, period, parquet_sha256, raw_sha256 de metadata.json, tablas}; filas por (servicio, tipo): L, personas, m, M; participaciones por especialidad y subtipo; GES por servicio y por problema (n, media, mediana); casos nuevos FONASA 2025; hospitales (código, nombre público, comuna, complejidad), comunas y pesos; serie nacional III-2025 / IV-2025 / I-2026 y arribos. < 150 KB. Aparte, `targets/assumptions.json` a mano: cada parámetro con `value`, `source`, `justification`, `verified`. Los tests solo leen estos JSON (sin red ni parquet).

Tolerancias (S = estricta, falla; B = blanda, avisa):

| ID | Chequeo | Tolerancia |
|---|---|---|
| C1 (S) | TVD = ½Σ\|p̂−p\| de servicio\|tipo, especialidad\|subtipo, tipo, problema\|GES, servicio\|GES, comuna\|servicio, edad\|clase, previsión | ≤ K/(2n) + 1e-9 (cota de redondeo de Hamilton; sin chi-cuadrado porque el margen es determinista) |
| C2 (S) | Media y mediana de espera por (servicio, tipo), grupos con n ≥ 30 | Mediana ±max(2 %, 1 día); media ±3 % |
| C3 (S) | Mezcla nacional CNE e IQ | Media y mediana ±5 % vs 341/242 y 394/264 |
| C4 (S) | Razón registros/personas por (servicio, tipo) | ±(0,01 + 1/P) |
| C5 (S) | Retraso GES por problema (n ≥ 30) y nacional | Como C2; nacional ±5 % vs 136/71 |
| C6 (S) | Media de p verdadera por (servicio, tipo); tasa realizada del historial global y por servicio con n_h ≥ 200 | ±1e-4; ±(3·√(t(1−t)/n_h) + 0,5 pp) |
| C7 (S) | Participación IQ mayor | ±3 pp |
| C8 (S) | Minutos programados / H vs objetivo por (servicio, tipo) | ±max(5 %, 1 sesión/H) |
| C9 (B) | E[p²] CNE; cobertura GES mapeada; V de Cramér servicio × especialidad | 3,0 % ± 1,5 pp; solo informe; solo informe |

Con N chico, grupos bajo el umbral de n → `skipped`. Informe en `results/synthetic_calibration_seed{S}_n{N}.json`; se versiona la corrida canónica (seed 42, N = 100.000).

**Determinismo:** cada componente usa `np.random.SeedSequence(seed, spawn_key=(stream_id,))` con `Stream(IntEnum)`: ALLOCATION=1, ATTRS=2, WAIT=3, PRIORITY=4, GES=5, LATENT=6, HISTORY=7, SPEC_EFFECTS=8, PATIENT_LINK=9. Prohibido: `random`, `uuid4`, `datetime.now` en los datos, iterar sets. En polars `group_by(maintain_order=True)` y orden explícito. `dataset_digest` = sha256 de (nombre de tabla + CSV ordenado por id, `float_precision=6`) por tabla, sin created_at.

## 6. Interfaces

```python
# config.py
@dataclass(frozen=True)
class RunConfig: size: int; seed: int; scenario: NoShowScenario = NoShowScenario.BASELINE
                 horizon_weeks: int = 26; as_of: date | None = None
# targets.py
def build_targets(processed_dir: Path, reference_source_id: str = "glosa06_2025q3") -> CalibrationTargets
def load_targets(path: Path | None = None) -> CalibrationTargets      # importlib.resources por defecto
def load_assumptions(path: Path | None = None) -> Assumptions
def write_json_canonical(model: BaseModel, path: Path) -> str          # devuelve sha256
# rng.py
def rng_for(seed: int, stream: Stream) -> np.random.Generator
def entity_uuid(run_id: UUID, kind: str, index: int) -> UUID           # uuid5
# allocation.py
def hamilton(weights: Mapping[K, float], total: int) -> dict[K, int]
def labels(counts: Mapping[K, int], order: Sequence[K]) -> np.ndarray
# distributions.py
@dataclass(frozen=True) class LogNormal: mu: float; sigma: float
def fit_lognormal(mean: float, median: float, sigma_floor: float = 0.1) -> LogNormal
def norm_ppf(u: np.ndarray) -> np.ndarray
def stratified_lognormal(d: LogNormal, n: int, rng: Generator, cap: float) -> np.ndarray
# catalog.py
def build_catalogs(t, a) -> dict[str, pl.DataFrame]   # health_service, commune, establishment, specialty, ges_problem, procedure
# population.py
def generate_population(t, a, cfg, run_id) -> tuple[pl.DataFrame, pl.DataFrame]  # patient, waitlist_entry
# noshow_truth.py
@dataclass(frozen=True) class NoShowParams: ...
def calibrate_intercepts(entries, patients, params, rates) -> dict[tuple[int, CareType], float]
def true_noshow_prob(features: pl.DataFrame, frailty: np.ndarray, params) -> np.ndarray
def generate_history(patients, entries, params, cfg, run_id) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]
    # appointment, appointment_truth, patient_latent
# capacity.py
def generate_capacity(t, a, cfg, entries, run_id) -> tuple[pl.DataFrame, pl.DataFrame]  # resource, slot
# pipeline.py
@dataclass(frozen=True) class SyntheticDataset: run: dict[str, object]; catalogs: dict[str, pl.DataFrame]
                                                tables: dict[str, pl.DataFrame]; digest: str
def generate(cfg: RunConfig, targets=None, assumptions=None) -> SyntheticDataset   # puro, sin E/S
# digest.py
def dataset_digest(tables: Mapping[str, pl.DataFrame]) -> str
# validate.py
class Check(BaseModel): name; group; metric; observed; target; tolerance; n; passed; severity
class CalibrationReport(BaseModel): run_id; digest; checks: list[Check]; passed: bool
def calibration_report(ds, targets, assumptions) -> CalibrationReport
# io.py
def write_parquet(ds, out_dir: Path) -> Path          # data/synthetic/<run_id>/*.parquet + manifest.json
# load.py
def load_dataset(ds, engine: Engine, replace: bool = False) -> None
# cli.py (typer): prioriza-synth build-targets | generate | validate
```

Contrato de columnas: claves de `tables` y columnas de cada frame idénticas a tablas y columnas de la sección 4 (patient, patient_latent, waitlist_entry, resource, slot, appointment, appointment_truth).

CLI: `prioriza-synth generate --size N --seed S [--scenario] [--horizon-weeks] [--as-of] [--load/--no-load] [--replace] [--out data/synthetic]`. Siempre escribe parquet y `manifest.json` (configuración, hashes, versiones, informe de calibración). Con `--load`: verifica conexión y `alembic_version` en head (si no: "ejecuta make up && make migrate"); upsert de catálogos; en una transacción: corrida con status `loading`, COPY en orden de FKs (`cursor.copy("COPY t (cols) FROM STDIN")` de psycopg 3 con CSV de polars en lotes de 50.000), status `ready`.

`make synth`: `uv run --package synthetic prioriza-synth generate --size $(SIZE) --seed $(SEED) --load` con `SIZE ?= 100000`, `SEED ?= 42`. Agregar `data/synthetic/` a `.gitignore`.

## 7. Trabajo en paralelo

| Rol | Archivos exclusivos | Depende de |
|---|---|---|
| implementer-B | `shared/src/shared/db/{enums,models,session,__init__}.py`, `migrations/versions/0002_core_model.py`, `shared/tests/test_db_models.py` (render offline `alembic upgrade head --sql` + test real marcado `db`, omitido sin PG), marker `db` en el pyproject raíz | Nada |
| implementer-A | `synthetic/**` salvo `tests/`, incl. `targets/*.json`, `synthetic/pyproject.toml`; `uv.lock`, target `synth` del Makefile, `.gitignore` | Importa `shared.db.enums` y `shared.db.models` con los nombres de la sección 4; entrega primero `calibration_targets.json` y `assumptions.json` |
| test-writer | `synthetic/tests/**` | Firmas de la sección 6 y JSON versionados |
| docs-writer | `docs/synthetic-data.md` | Este plan; se reconcilia con `assumptions.json` final |
| Sesión principal | `docs/decisions.md`, `CLAUDE.md` | — |

Tests: determinismo (mismo seed ⇒ mismo digest, distinto ⇒ distinto, N = 5.000); calibración C1-C8 con N = 20.000 (< 5 s); N = 1.000 respeta C1; hypothesis para `hamilton`, `fit_lognormal`, `norm_ppf`; privacidad (sin name, rut, sex, ethnicity, nationality); columnas = `Base.metadata`; targets con esquema y procedencia y reconstrucción idéntica si existe `data/processed`; carga a DB marcada `db`.

Proceso: ml-engineer revisa `noshow_truth.py` y escenarios; data-researcher trae FONASA por tramo, plazos GES y tabla por servicio de Sepúlveda; reviewer al final.

## 8. Dependencias nuevas

- `numpy>=2.0` (synthetic): `Generator`/`SeedSequence` con streams independientes y muestreo vectorizado.
- `typer` (ya en el lock): CLI `prioriza-synth`.
- Sin scipy: Φ⁻¹ con AS241 y bisección propia.

## 9. Riesgos

1. Edad y previsión son supuestos hasta ingerir esas tablas de la Glosa.
2. Alcance GES limitado a problemas mapeados con plazos por verificar.
3. Efecto de previsión en el generador es éticamente sensible (ver decisión).
4. Supuestos de independencia: servicio × especialidad, espera independiente de especialidad y prioridad, pools CNE/IQ disjuntos. Se declaran en todo informe.
5. Capacidad por ley de Little con lista no estacionaria; se mitiga con `capacity_multiplier` y sensibilidad.

## 10. Decisiones aprobadas por el usuario (2026-10-08) — obligatorias

1. Edad y previsión: supuestos ahora, `verified: false` en `assumptions.json`; pendiente extender la ingesta con esas tablas de la Glosa (fuera de este prompt).
2. Alcance GES: solo 15-20 problemas mapeados a especialidad, plazos del Decreto GES (data-researcher; mientras, provisorios `verified: false`); se reporta cobertura sobre las 80.022 retrasadas.
3. Previsión en inasistencias: `baseline` SIN efecto de previsión; `ses_gradient` solo como análisis de sensibilidad; `neutral` como control obligatorio en informes. Escenario por defecto de la CLI: `baseline`.
