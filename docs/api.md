# API de Prioriza

**Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.**

## 1. Alcance

La API de Prioriza expone tres funcionalidades:

1. **Lista de espera y puntaje de priorización**: consulta del stock de la corrida sintética configurada, con el puntaje de cada entrada calculado según reglas explícitas (prioridad clínica declarada, días de espera, plazos GES).

2. **Programación asíncrona**: solicitud de un plan de agendamiento (política `fifo`, `priority` u `optimized` con sobrecupo controlado) que el servidor calcula en segundo plano y guarda en estado `pending` requiere aprobación manual antes de usarse.

3. **Simulación de políticas**: resultados comparativos de las cuatro políticas a lo largo de 26 semanas con replicación, incluida equidad por grupo etario, previsión y comuna.

**La API apoya, no decide**: la prioridad clínica es un dato de entrada definido por profesionales, nunca se infiere ni se sobreescribe. Todo plan requiere revisión humana explícita (aprobación o rechazo) antes de poder ser vigente, y cada acción queda registrada en auditoría.

Nota: el servidor calcula el puntaje de prioridad y su explicación al cargar la corrida (`priority.rank_frame` y `priority.explain`), pero no genera la simulación: solo expone `results/simulation.json`. La prioridad se calcula con `priority.rank_frame`, la simulación existe en `results/simulation.json` si se ejecutó `make simulate`, y los modelos de inasistencias en `models/noshow/<run_id>/` si se ejecutó `make train-noshow`.

---

## 2. Cómo levantarla

### Local (sin PostgreSQL)

Precondiciones:
- Python 3.12 con `uv` instalado.
- Corrida sintética generada: `make synth` escribe en `data/synthetic/<run_id>/`.
- Variables de entorno de `.env` (copiar de `.env.example`).

Pasos:

```bash
# 1. Generar población sintética (si no existe)
make synth

# 2. Levantar la API (almacenamiento en memoria por defecto)
uv run --package api uvicorn --factory api.main:create_app --host 127.0.0.1 --port 8000

# 3. Ver la documentación interactiva
# http://127.0.0.1:8000/docs
```

Variables de entorno (`PRIORIZA_API_*`):
- `PRIORIZA_API_USERS_FILE`: Ruta del archivo JSON de usuarios (p. ej. `api/config/users.json`). Sin valor, toda ruta protegida devuelve **401**; no hay claves por defecto en el código.
- `PRIORIZA_API_STORE`: `memory` (por defecto; se pierde al reiniciar) o `sql` (PostgreSQL, requiere `make migrate`).
- `PRIORIZA_API_RUN_DIR`: Ruta explícita de la corrida (p. ej. `data/synthetic/a1b2c3d4`). Si falta, se busca con semilla, tamaño y escenario.
- `PRIORIZA_API_DATA_DIR`: Directorio donde están las corridas (por defecto `data/synthetic`).
- `PRIORIZA_API_SEED`: Semilla para buscar corrida (por defecto `42`).
- `PRIORIZA_API_SIZE`: Tamaño de población (por defecto `100000`).
- `PRIORIZA_API_SCENARIO`: Escenario (por defecto `baseline`).
- `PRIORIZA_API_MODELS_DIR`: Directorio de modelos de inasistencias (por defecto `models/noshow`).
- `PRIORIZA_API_RESULTS_DIR`: Directorio de resultados de simulación (por defecto `results`).
- `PRIORIZA_API_MAX_ACTIVE_JOBS_PER_USER`, `PRIORIZA_API_MAX_ACTIVE_JOBS`: programaciones pendientes o en curso permitidas por usuario (2) y en total (8).
- `PRIORIZA_API_JOB_TTL_HOURS`: horas que se recuerda un trabajo terminado (24).

### Con Docker Compose

```bash
# 1. Copiar archivo de usuarios (cambiar las claves de ejemplo)
mkdir -p api/config
cp api/users.example.json api/config/users.json
# Editar api/config/users.json con las claves reales

# 2. Levantar todo (PostgreSQL, API y panel Dash)
make up

# 3. Migrar la base (solo una vez)
make migrate

# 4. Generar población sintética (solo una vez)
make synth

# 5. Entrenar modelo de inasistencias (solo si se usará policy=optimized)
make train-noshow

# 6. Acceder
# API: http://localhost:8000/docs
# Dash: http://localhost:8050
```

Para detener:
```bash
make down
```

---

## 3. Autenticación

Todo endpoint excepto `/healthz` requiere la cabecera `X-API-Key`:

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/me
```

Respuesta (sin clave o inválida: **401**, con rol insuficiente: **403**):
```json
{
  "user": "revisor.ejemplo",
  "role": "revisor"
}
```

**Usuarios y claves**:
- Viven en un archivo JSON fuera del repositorio (nunca versionado): `api/config/users.json`.
- Formato: `{clave_api: {"user": "nombre", "role": "gestor|revisor|lectura"}}`.
- Ejemplo (`api/users.example.json`):
  ```json
  {
    "EJEMPLO-clave-gestor-no-usar-en-produccion": {"user": "gestora.ejemplo", "role": "gestor"},
    "EJEMPLO-clave-revisor-no-usar-en-produccion": {"user": "revisor.ejemplo", "role": "revisor"},
    "EJEMPLO-clave-lectura-no-usar-en-produccion": {"user": "lectura.ejemplo", "role": "lectura"}
  }
  ```
- La comparación usa `hmac.compare_digest` contra todas las claves sin cortar en la primera (resistente a timing attacks).
- Sin archivo definido (`PRIORIZA_API_USERS_FILE` vacío o indefinido): toda ruta protegida responde **401**.
- El archivo se valida al arrancar: se rechazan las claves de ejemplo (prefijo `EJEMPLO`) y las de menos de 32 caracteres (genera claves con `python -c 'import secrets; print(secrets.token_urlsafe(32))'`), y los nombres de usuario vacíos o de más de 64 caracteres. `users.example.json` muestra el formato y no arranca tal cual.
- La regla de cuatro ojos compara nombres sin distinguir mayúsculas ni espacios en los extremos.
- Los ejemplos `curl` de este documento usan las claves de `users.example.json` como marcador: reemplázalas por las de tu `users.json`.

---

## 4. Roles y permisos

Tres roles con control de acceso:

| Acción | `lectura` | `gestor` | `revisor` |
|--------|-----------|----------|-----------|
| Ver lista de espera, pacientes, planes (incluidos exportar, comparar y "por qué este cupo"), simulación | ✓ | ✓ | ✓ |
| Solicitar una programación | ✗ | ✓ | ✗ |
| Aprobar o rechazar un plan pendiente | ✗ | ✗ | ✓ |
| Marcar vigente un plan aprobado | ✗ | ✓ | ✗ |

**Reglas adicionales** (dominio, no en HTTP):

1. **Cuatro ojos**: el revisor no puede aprobar o rechazar un plan que él mismo solicitó. Compara por nombre de usuario.
2. **Transiciones de estado**:
   - `pending` → `approved` o `rejected` (final; no se puede cambiar después).
   - `approved` → `vigente` (solo uno por corrida sintética; activar otro desactiva el anterior).
   - Un plan no aprobado no puede ser vigente (CHECK en la base).
3. **Auditoría**: cada acción (aprobación, rechazo, activación, desactivación) se registra con usuario, rol, hora y nota opcional en la tabla `plan_review`.

---

## 5. Referencia de endpoints

**Prefijo**: todos tienen prefijo `/v1` excepto `/healthz`.

**Paginación**: `limit` (1–500, por defecto 50), `offset` (por defecto 0). Las respuestas incluyen `total` (sin paginar).

### Sistema

#### `GET /healthz`
Sin clave. Sonda de salud para Docker y orquestadores.

```bash
curl http://localhost:8000/healthz
```

Respuesta:
```json
{"status": "ok"}
```

#### `GET /v1/me`
Requiere clave. Devuelve el usuario y rol asociados.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/me
```

Respuesta:
```json
{
  "user": "revisor.ejemplo",
  "role": "revisor"
}
```

### Lista de espera y pacientes

#### `GET /v1/waitlist`
Requiere clave. Entradas en espera de la corrida sintética con puntaje y puesto.

**Filtros** (todos opcionales, AND):
- `health_service_code` (int): código del servicio de salud.
- `specialty_code` (str): código de especialidad.
- `care_type` (str): `consultation` o `surgery`.
- `clinical_priority` (str): `p1`, `p2`, `p3` o `p4`.
- `is_ges` (bool): con garantía GES.
- `tier` (str): nivel GES estricto (`NONE`, `GES_DUE_SOON`, `GES_OVERDUE`).

**Orden** (parámetro `order_by`, por defecto `rank`):
- `rank`: puesto en la cola (recomendado).
- `score`: puntaje de priorización (0–100).
- `entry_date`: fecha de ingreso a espera.

```bash
curl -H "X-API-Key: EJEMPLO-clave-lectura-no-usar-en-produccion" \
  'http://localhost:8000/v1/waitlist?limit=5&health_service_code=1&order_by=rank'
```

Respuesta:
```json
{
  "disclaimer": "Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.",
  "total": 25000,
  "limit": 5,
  "offset": 0,
  "items": [
    {
      "entry_id": "entry-uuid-1",
      "patient_id": "patient-uuid-a",
      "health_service_code": 1,
      "specialty_code": "CNE",
      "care_type": "consultation",
      "clinical_priority": "p2",
      "is_ges": false,
      "ges_deadline": null,
      "entry_date": "2026-09-01",
      "wait_days": 38,
      "score": 75.5,
      "rank": 1,
      "tier": "NONE"
    },
    ...
  ]
}
```

#### `GET /v1/patients/{patient_id}`
Requiere clave. Paciente sintético y sus entradas con explicación del puntaje.

```bash
curl -H "X-API-Key: EJEMPLO-clave-lectura-no-usar-en-produccion" \
  'http://localhost:8000/v1/patients/patient-uuid-a'
```

Respuesta:
```json
{
  "disclaimer": "Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.",
  "patient_id": "patient-uuid-a",
  "health_service_code": 1,
  "commune_code": "1301",
  "age_group": "45_64",
  "insurance": "fonasa_b",
  "entries": [
    {
      "entry_id": "entry-uuid-1",
      "patient_id": "patient-uuid-a",
      "health_service_code": 1,
      "specialty_code": "CNE",
      "care_type": "consultation",
      "clinical_priority": "p2",
      "is_ges": false,
      "ges_deadline": null,
      "entry_date": "2026-09-01",
      "status": "waiting",
      "wait_days": 38,
      "score": 75.5,
      "rank": 1,
      "tier": "NONE",
      "explanation": {
        "entry_id": "entry-uuid-1",
        "rank": 1,
        "total": 75.5,
        "score": 75.5,
        "tier": "NONE",
        "tier_reason": "no vence en 14 días",
        "lines": ["Prioridad clínica: p2 (50.0 pts)", "Espera: 38 días (26.5 pts)", ...],
        "text": "Puesto 1 de 100; puntaje 75.5..."
      }
    }
  ]
}
```

Códigos de respuesta:
- **200**: Paciente encontrado.
- **401**: Clave faltante o inválida.
- **404**: Paciente no existe.
- **503**: Corrida sintética no disponible.

### Programación asíncrona

#### `POST /v1/schedule-runs`
Requiere rol `gestor`. Encola la programación.

**Cuerpo**:
```json
{
  "policy": "optimized",
  "horizon_weeks": 4,
  "overbooking": true,
  "alpha": 0.10,
  "time_limit_s": 120.0
}
```

- `policy` (obligatorio): `fifo`, `priority` u `optimized`.
- `horizon_weeks` (opcional, por defecto 4): semanas de horizonte (1–52).
- `overbooking` (opcional, por defecto `true`): activar sobrecupo (solo afecta `optimized`).
- `alpha` (opcional, por defecto 0.10): parámetro de sobrecupo (0–1, solo si `overbooking=true`).
- `time_limit_s` (opcional, por defecto 120): presupuesto **global del plan** de CP-SAT (mayor que 0 y hasta 3600; solo afecta a `policy=optimized`): se reparte entre la primera pasada y la expansión de frontera, no se aplica por pasada. En el modo determinista por defecto es tiempo determinista de CP-SAT (`max_deterministic_time`), no segundos de reloj. Si alguna fase termina por el límite, el informe agrega la advertencia `time_budget_exhausted`.

```bash
curl -X POST \
  -H "X-API-Key: EJEMPLO-clave-gestor-no-usar-en-produccion" \
  -H "Content-Type: application/json" \
  -d '{"policy":"optimized","horizon_weeks":4,"overbooking":true,"alpha":0.10,"time_limit_s":120}' \
  http://localhost:8000/v1/schedule-runs
```

Respuesta (status **202 Accepted**):
```json
{
  "disclaimer": "...",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "policy": "optimized",
  "requested_by": "gestora.ejemplo",
  "created_at": "2026-10-09T14:30:00Z",
  "plan_id": null,
  "error": null
}
```

Cabecera de respuesta: `Location: /v1/schedule-runs/550e8400-e29b-41d4-a716-446655440000`.

Códigos de respuesta:
- **202**: Trabajo encolado.
- **401**: Clave faltante o inválida.
- **403**: Rol insuficiente (no es `gestor`).
- **429**: El usuario ya tiene `PRIORIZA_API_MAX_ACTIVE_JOBS_PER_USER` programaciones pendientes o en curso (2 por defecto), o hay `PRIORIZA_API_MAX_ACTIVE_JOBS` en total (8).

Si la corrida sintética o el modelo de inasistencias no están disponibles, la petición igual responde 202 y el trabajo termina `failed` con un mensaje sin rutas internas (el detalle queda en el log del servidor).

#### `GET /v1/schedule-runs/{job_id}`
Requiere clave. Estado de un trabajo de programación.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/schedule-runs/550e8400-e29b-41d4-a716-446655440000
```

Respuesta:
```json
{
  "disclaimer": "...",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "succeeded",
  "policy": "optimized",
  "requested_by": "gestora.ejemplo",
  "created_at": "2026-10-09T14:30:00Z",
  "plan_id": "660f8400-e29b-41d4-a716-446655440111",
  "error": null
}
```

Estados:
- `queued`: en cola.
- `running`: en ejecución.
- `succeeded`: completado; `plan_id` presente.
- `failed`: error; `error` present con el mensaje.

Códigos de respuesta:
- **200**: Trabajo encontrado.
- **401**: Clave faltante o inválida.
- **404**: Trabajo no existe.

### Planes

#### `GET /v1/plans`
Requiere clave. Listar planes del más reciente al más antiguo.

**Filtros** (opcionales):
- `review_status`: `pending`, `approved` o `rejected`.
- `current`: `true` (solo vigentes) o `false` (no vigentes).

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  'http://localhost:8000/v1/plans?limit=10&review_status=pending'
```

Respuesta:
```json
{
  "disclaimer": "...",
  "total": 5,
  "limit": 10,
  "offset": 0,
  "items": [
    {
      "plan_id": "660f8400-e29b-41d4-a716-446655440111",
      "run_id": "a1b2c3d4",
      "policy": "optimized",
      "review_status": "pending",
      "is_current": false,
      "requested_by": "gestora.ejemplo",
      "created_at": "2026-10-09T14:35:00Z",
      "solver_status": "OPTIMAL",
      "objective_value": 16787.5,
      "horizon_start": "2026-10-13",
      "horizon_end": "2026-11-10"
    },
    ...
  ]
}
```

Códigos de respuesta:
- **200**: Planes encontrados (puede estar vacío).
- **401**: Clave faltante o inválida.

#### `GET /v1/plans/current`
Requiere clave. Plan vigente de la corrida configurada.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/plans/current
```

Respuesta (igual que `/plans/{plan_id}` abajo, con detalle completo):
```json
{
  "disclaimer": "...",
  "plan_id": "660f8400-e29b-41d4-a716-446655440111",
  "run_id": "a1b2c3d4",
  "policy": "optimized",
  "review_status": "approved",
  "is_current": true,
  "requested_by": "gestora.ejemplo",
  "created_at": "2026-10-09T14:35:00Z",
  "solver_status": "OPTIMAL",
  "objective_value": 16787.5,
  "horizon_start": "2026-10-13",
  "horizon_end": "2026-11-10",
  "summary": {
    "entries_waiting": 25000,
    "scheduled": 5952,
    "scheduled_cne": 3200,
    "scheduled_or": 2752,
    "overbooked_flags": 144,
    "added_by_overbooking": 100,
    "by_status": {"scheduled": 5952, "no_compatible_block": 19048}
  },
  "ges": {
    "obligated": 3866,
    "met": 3833,
    "unmet": 33,
    "unmet_by_cause": {...}
  },
  "equity": [
    {
      "dimension": "age_group",
      "value": "0-14",
      "entries": 2500,
      "scheduled": 1200,
      "scheduled_rate": 0.48,
      "exposure_share": 0.25,
      "flagged_share": 0.02
    },
    ...
  ],
  "warnings": ["capacidad insuficiente", ...],
  "config": {"policy": "optimized", "horizon_weeks": 4, "overbooking": true, "alpha": 0.10, ...}
}
```

Códigos de respuesta:
- **200**: Plan vigente encontrado.
- **401**: Clave faltante o inválida.
- **404**: No hay plan vigente.

#### `GET /v1/plans/{plan_id}`
Requiere clave. Resumen del informe de un plan específico.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111
```

Respuesta: igual que `/plans/current`.

#### `GET /v1/plans/{plan_id}/assignments`
Requiere clave. Citas propuestas (asignaciones) de un plan.

**Paginación**: `limit` (por defecto 50), `offset` (por defecto 0).

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  'http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/assignments?limit=5'
```

Respuesta:
```json
{
  "disclaimer": "...",
  "total": 5952,
  "limit": 5,
  "offset": 0,
  "items": [
    {
      "entry_id": "entry-uuid-1",
      "patient_id": "patient-uuid-a",
      "slot_id": "slot-uuid-x",
      "specialty_code": "CNE",
      "scheduled_start": "2026-10-14T09:00:00Z",
      "duration_min": 20,
      "lead_days": 5,
      "is_overbooked": false,
      "predicted_noshow_prob": 0.15
    },
    ...
  ]
}
```

Ordenadas por fecha de inicio y entrada.

Códigos de respuesta:
- **200**: Asignaciones encontradas.
- **401**: Clave faltante o inválida.
- **404**: Plan no existe.

#### `GET /v1/plans/{plan_id}/export`
Requiere clave (cualquier rol). Descarga las asignaciones del plan en CSV. Lo usa el botón "Descargar CSV" de la vista Programación.

**Parámetros**: `format` (solo `csv`, por defecto `csv`; otro valor es 422), `limit` (filas a exportar; por defecto y como máximo `PRIORIZA_API_MAX_EXPORT_ROWS`, 50.000; un valor mayor es 422) y `offset` (por defecto 0, para continuar un archivo recortado).

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  'http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/export?format=csv'
```

Respuesta (`text/csv; charset=utf-8`, `Content-Disposition: attachment`, sin `disclaimer` JSON: el aviso va en el archivo):
```csv
# aviso: Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.
# plan: 660f8400-e29b-41d4-a716-446655440111; estado de revisión: pending; todo plan requiere revisión humana antes de usarse
Entrada,Paciente sintético,Cupo,Especialidad,Inicio (UTC),Duración (min),Anticipación (días),Sobrecupo,Probabilidad de inasistencia
entry-uuid-1,patient-uuid-a,slot-uuid-x,cne_medical:medicina_interna,2026-10-14T09:00:00+00:00,20,5,no,0.15
```

- **Formato**: UTF-8 sin BOM, coma como separador, `\n` como fin de línea. Las columnas y sus encabezados (en español) son estables: Entrada, Paciente sintético, Cupo, Especialidad, Inicio (UTC), Duración (min), Anticipación (días), Sobrecupo (`sí`/`no`), Probabilidad de inasistencia.
- **Líneas de comentario**: las líneas que empiezan con `#` (aviso, plan y estado de revisión, y `# truncado` si se recortó por el tope) no son datos. **El lector CSV debe saltarlas** (en pandas, `comment="#"`; en polars, `comment_prefix="#"`).
- **Sin datos personales**: solo ids sintéticos y columnas operativas; nada de edad, comuna, previsión ni sexo.
- **Fórmulas**: las celdas de texto que empiezan con `=`, `+`, `-`, `@`, tabulación o retorno de carro se prefijan con `'` para que una hoja de cálculo no las ejecute.
- **Tamaño**: si el plan tiene más filas que el tope, el archivo trae la línea `# truncado: ...` y las cabeceras `X-Total-Rows` y `X-Exported-Rows` dicen cuántas filas hay y cuántas se enviaron; se continúa con `offset`.

Códigos de respuesta: **200**, **401**, **404** (plan no existe), **422** (`format` distinto de `csv` o `limit` sobre el tope).

#### `GET /v1/plans/compare`
Requiere clave (cualquier rol). Compara dos planes **de la misma corrida** lado a lado: `?a={plan_id}&b={plan_id}`.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  'http://localhost:8000/v1/plans/compare?a=660f8400-e29b-41d4-a716-446655440111&b=770f8400-e29b-41d4-a716-446655440222'
```

Respuesta:
```json
{
  "disclaimer": "...",
  "run_id": "d7a0c251-...",
  "a": {"plan_id": "660f8400-...", "policy": "fifo", "review_status": "pending", "is_current": false, "created_at": "...", "requested_by": "gestora.test", "solver_status": "NOT_APPLICABLE"},
  "b": {"plan_id": "770f8400-...", "policy": "optimized", "review_status": "approved", "is_current": true, "created_at": "...", "requested_by": "gestora.test", "solver_status": "OPTIMAL"},
  "metrics": [
    {"key": "scheduled", "label": "Citas agendadas", "direction": "higher_is_better", "a": 5952, "b": 6100, "diff": 148, "better": "b"},
    {"key": "ges_unmet", "label": "GES no cumplidas", "direction": "lower_is_better", "a": 10, "b": 12, "diff": 2, "better": "a"}
  ],
  "equity": [
    {"key": "exposure_share", "label": "Exposición al sobrecupo", "direction": "lower_is_better", "dimension": "age_group", "value": "0_14", "a": 0.0, "b": 0.31, "diff": 0.31, "better": "a"}
  ]
}
```

- `diff` es siempre `b - a` (absoluta; en fracciones para tasas y riesgos). `better` es `a`, `b`, `tie` o `none` (métrica solo informativa, como los sobrecupos, o dato faltante en un plan).
- Métricas globales (`key`): `scheduled`, `q1_scheduled` (máxima prioridad), `ges_met`, `ges_unmet`, `ges_on_time`, `overbooked_flags`, `added_by_overbooking`, `max_overflow_risk`. Equidad: `scheduled_rate`, `exposure_share` y `flagged_share` por cada grupo del informe (la unión de los grupos de ambos planes).
- **Los resultados desfavorables se muestran tal cual**: si el plan B es peor en una métrica o en un grupo, `better` vale `a`.
- Códigos de respuesta: **200**, **401**, **404** (un plan no existe), **422** (`a` igual a `b`, id mal formado o planes de corridas distintas: "los planes son de corridas distintas; no se pueden comparar").

#### `GET /v1/plans/{plan_id}/entries/{entry_id}/reason`
Requiere clave (cualquier rol). "Por qué este cupo": reúne en una respuesta lo que el plan y la lista de espera ya saben de una entrada; no calcula nada nuevo.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/entries/entry-uuid-1/reason
```

Campos de la respuesta (además de `disclaimer`): `plan_id`, `entry_id`, `policy`; `status`, `detail` y `text` (la explicación de `/explanations`); `phase` (`3a` agendada sin sobrecupo o `3b` entró gracias al sobreagendamiento en la política optimizada; el nombre de la política en `fifo` y `priority`; `null` si no quedó agendada; se deduce de `detail`); `assignment` (la cita: cupo, inicio, `is_overbooked`, `predicted_noshow_prob`; `null` si no quedó agendada); `block_load` (capacidad, citas, sobrecupos y `risk_exact` de desborde de la sesión con sobrecupo donde quedó la cita; `null` si el plan no lo informa); `ges` (la garantía GES del plan: plazo, cumplimiento, atraso, causa; `null` si no tiene obligación en el horizonte); y `score` (puntaje, puesto, nivel, prioridad clínica como dato de entrada, espera, `components` y `explanation` de la lista de espera; `null` si la entrada ya no está en espera o la corrida no está disponible).

Códigos de respuesta: **200**, **401**, **404** (el plan no existe o no tiene explicación para esa entrada; los planes escritos por la CLI con `--persist` no guardan explicaciones). El id de la entrada se redacta en los logs (`/entries/[REDACTADO]`).

#### `GET /v1/plans/{plan_id}/explanations`
Requiere clave. Por qué cada entrada quedó (o no) en el plan.

**Filtro** (opcional):
- `status`: estado de la explicación (p. ej. `scheduled`, `capacity_taken`, `no_compatible_block`, `not_candidate`, `patient_conflict`, `not_selected`).

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  'http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/explanations?status=scheduled&limit=5'
```

Respuesta:
```json
{
  "disclaimer": "...",
  "total": 5952,
  "limit": 5,
  "offset": 0,
  "items": [
    {
      "entry_id": "entry-uuid-1",
      "status": "scheduled",
      "detail": null,
      "text": "Agendada en CNE el 2026-10-14; p=0.15."
    },
    {
      "entry_id": "entry-uuid-2",
      "status": "capacity_taken",
      "detail": "CNE, 2026-10-14–2026-10-21",
      "text": "Sin cupo compatible: la capacidad se tomó con pacientes de mayor prioridad."
    },
    ...
  ]
}
```

Códigos de respuesta:
- **200**: Explicaciones encontradas.
- **401**: Clave faltante o inválida.
- **404**: Plan no existe.

#### `GET /v1/plans/{plan_id}/reviews`
Requiere clave. Auditoría de todas las acciones sobre un plan.

```bash
curl -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/reviews
```

Respuesta (en orden cronológico):
```json
{
  "disclaimer": "...",
  "plan_id": "660f8400-e29b-41d4-a716-446655440111",
  "items": [
    {
      "id": "audit-uuid-1",
      "action": "approve",
      "user_name": "revisor.ejemplo",
      "role": "revisor",
      "note": "Verificado con criterios clínicos",
      "created_at": "2026-10-09T14:40:00Z"
    },
    {
      "id": "audit-uuid-2",
      "action": "activate",
      "user_name": "gestora.ejemplo",
      "role": "gestor",
      "note": null,
      "created_at": "2026-10-09T14:41:00Z"
    }
  ]
}
```

Acciones: `approve`, `reject`, `activate`, `deactivate`.

Códigos de respuesta:
- **200**: Auditoría encontrada (puede estar vacía si el plan es muy nuevo).
- **401**: Clave faltante o inválida.
- **404**: Plan no existe.

#### `POST /v1/plans/{plan_id}/review`
Requiere rol `revisor`. Aprobar o rechazar un plan pendiente.

**Cuerpo**:
```json
{
  "decision": "approved",
  "note": "Plan validado; mediana de espera 295 días, ganancia vs fifo 25 días."
}
```

- `decision` (obligatorio): `approved` o `rejected`.
- `note` (opcional): texto libre, máx. 2000 caracteres.

```bash
curl -X POST \
  -H "X-API-Key: EJEMPLO-clave-revisor-no-usar-en-produccion" \
  -H "Content-Type: application/json" \
  -d '{"decision":"approved","note":"Plan validado"}' \
  http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/review
```

Respuesta (status **200**):
```json
{
  "disclaimer": "...",
  "plan_id": "660f8400-e29b-41d4-a716-446655440111",
  "run_id": "a1b2c3d4",
  "policy": "optimized",
  "review_status": "approved",
  "is_current": false,
  "requested_by": "gestora.ejemplo",
  "created_at": "2026-10-09T14:35:00Z",
  "solver_status": "OPTIMAL",
  "objective_value": 16787.5,
  "horizon_start": "2026-10-13",
  "horizon_end": "2026-11-10"
}
```

Códigos de respuesta:
- **200**: Plan revisado.
- **401**: Clave faltante o inválida.
- **403**: Rol insuficiente (no es `revisor`) o cuatro ojos (revisor pidió el plan).
- **404**: Plan no existe.
- **409**: El plan no está `pending` (la decisión es final).
- **422**: Cuerpo inválido (por ejemplo, `decision` distinta de `approved` o `rejected`).

#### `POST /v1/plans/{plan_id}/activate`
Requiere rol `gestor`. Marcar un plan aprobado como vigente.

**Cuerpo** (opcional):
```json
{
  "note": "Implementación iniciada en centro quirúrgico 3"
}
```

- `note` (opcional): texto libre, máx. 2000 caracteres.

```bash
curl -X POST \
  -H "X-API-Key: EJEMPLO-clave-gestor-no-usar-en-produccion" \
  -H "Content-Type: application/json" \
  -d '{"note":"Implementación iniciada"}' \
  http://localhost:8000/v1/plans/660f8400-e29b-41d4-a716-446655440111/activate
```

Respuesta (status **200**):
```json
{
  "disclaimer": "...",
  "plan_id": "660f8400-e29b-41d4-a716-446655440111",
  "run_id": "a1b2c3d4",
  "policy": "optimized",
  "review_status": "approved",
  "is_current": true,
  "requested_by": "gestora.ejemplo",
  "created_at": "2026-10-09T14:35:00Z",
  "solver_status": "OPTIMAL",
  "objective_value": 16787.5,
  "horizon_start": "2026-10-13",
  "horizon_end": "2026-11-10"
}
```

Efecto: se desactiva el plan vigente anterior de la misma corrida (si existe) y se registran ambos cambios en auditoría.

Códigos de respuesta:
- **200**: Plan activado.
- **401**: Clave faltante o inválida.
- **403**: Rol insuficiente (no es `gestor`).
- **404**: Plan no existe.
- **409**: Plan no está en estado `approved` o ya es vigente.

### Simulación

#### `GET /v1/simulation`
Requiere clave. Resumen de `results/simulation.json`.

**Filtro** (opcional):
- `policy`: devuelve solo esta política y sus variantes (p. ej. `optimized` incluye `optimized` y `optimized_overbooking`).

```bash
curl -H "X-API-Key: EJEMPLO-clave-lectura-no-usar-en-produccion" \
  'http://localhost:8000/v1/simulation?policy=optimized'
```

Respuesta (extracto real con `results/simulation.json` de 10.000 entradas; "…" marca lo omitido):
```json
{
  "disclaimer": "Herramienta de investigación con datos sintéticos. …",
  "generated_at": "2026-10-09T13:56:29+00:00",
  "run": {
    "as_of": "2025-09-30",
    "id": "a0386f24-5378-5fee-add8-5c1e1c81fa7e",
    "scenario": "baseline",
    "seed": 42,
    "size": 10000
  },
  "noshow_model_version": "noshow-4f0429cd-e8a25faf",
  "config": {
    "weeks": 26,
    "horizon_weeks": 4,
    "policies": [
      "fifo",
      "priority",
      "optimized",
      "optimized_overbooking"
    ],
    "replica_seeds": [
      101,
      102,
      103,
      104,
      105
    ]
  },
  "supply_coverage": {
    "consultation": {
      "blocks": 674,
      "cells": 1246,
      "cells_with_block": 466,
      "stock": 8559,
      "stock_in_cells_with_block": 6537
    },
    "surgery": {
      "blocks": 423,
      "cells": 304,
      "cells_with_block": 219,
      "stock": 1441,
      "stock_in_cells_with_block": 1293
    }
  },
  "aggregate": {
    "optimized_overbooking": {
      "resolved_total": {
        "ci95_high": 6654.2141,
        "ci95_low": 6577.7859,
        "max": 6661.0,
        "mean": 6616.0,
        "min": 6584.0,
        "n": 5,
        "sd": 30.7815
      },
      "wait_attended_median": {
        "ci95_high": 296.6775,
        "ci95_low": 293.1225,
        "max": 297.0,
        "mean": 294.9,
        "min": 293.0,
        "n": 5,
        "sd": 1.4318
      }
    },
    "…": "…"
  },
  "comparisons": {
    "optimized_overbooking_vs_optimized": {
      "resolved_total": {
        "better_in": 5,
        "ci95_high": 106.8438,
        "ci95_low": 94.7562,
        "direction": 1,
        "mean_diff": 100.8
      },
      "overflow_affected_patients": {
        "better_in": 0,
        "ci95_high": 226.8282,
        "ci95_low": 79.9718,
        "direction": -1,
        "mean_diff": 153.4
      }
    },
    "…": "…"
  },
  "equity": {
    "optimized_overbooking": {
      "age_group": {
        "min_n": 30,
        "groups": {
          "0_14": {
            "attention_rate": {
              "mean": 0.3064,
              "min": 0.2977,
              "max": 0.312,
              "n": 5
            },
            "overbooking_exposure": {
              "mean": 0.2685,
              "min": 0.2556,
              "max": 0.2892,
              "n": 5
            }
          },
          "…": "…"
        },
        "max_gap_overbooking_exposure": {
          "mean": 0.0433,
          "min": 0.028,
          "max": 0.0626,
          "n": 5
        }
      },
      "…": "…"
    },
    "…": "…"
  },
  "limitations": [
    "Granularidad de la oferta: cada sesión atiende una sola celda (servicio x especialidad); a tamaños chicos muchas celdas no reciben ninguna sesión en el periodo simulado y su stock no puede atenderse con ninguna política (ver supply_coverage).",
    "Llegadas por Little en estado estacionario: sin estacionalidad, sin tendencia y con la espera media de un solo corte.",
    "…"
  ]
}
```

`equity` resume entre réplicas, por política, dimensión (`age_group`, `insurance`, `commune_code`) y grupo, las métricas de `replicas[i].policies[p].groups` de la simulación (tasa de atención, mediana de espera, GES incumplidas, egresos por dos inasistencias, inasistencia realizada, exposición al sobrecupo y desborde), con media, mínimo, máximo y número de réplicas, más la brecha máxima entre grupos. Se informa tal cual, también cuando un grupo queda más expuesto.

Códigos de respuesta:
- **200**: Resultados encontrados.
- **401**: Clave faltante o inválida.
- **404**: No hay archivo `results/simulation.json`; ejecutar `make simulate`.

---

## 6. Campo `disclaimer`

**Todas las respuestas de lista, paciente, plan, trabajo, revisión y simulación incluyen el campo `disclaimer`** con el aviso obligatorio. Se devuelve en la respuesta JSON (no en cabecera HTTP) porque:

- El texto incluye tildes y caracteres especiales; las cabeceras HTTP son ASCII (latin-1), lo que requeriría codificación RFC 2047 y sería incómodo de parsear.
- El aviso es parte del contenido, no un metadato de protocolo, por lo que pertenece al cuerpo.

---

## 7. Almacenamiento y persistencia

### Almacén de planes: memoria vs SQL

**Por defecto (`PRIORIZA_API_STORE=memory`)**: Los planes se guardan en memoria y se pierden al reiniciar el servidor. Adecuado para desarrollo y experimentación.

**Con PostgreSQL (`PRIORIZA_API_STORE=sql`)**: Los planes, auditoría y explicaciones se persisten en la base.

Tablas (migración `0006_plan_review`):
- `schedule_run`: id (uuid), run_id (FK), policy, horizon_start, horizon_end, review_status (`pending`, `approved`, `rejected`), is_current (bool, default false), requested_by (usuario), created_at, solver_status, objective_value.
- `appointment`: citas propuestas (id, schedule_run_id FK, entry_id, patient_id, slot_id, scheduled_start, duration_min, lead_days, is_overbooked, predicted_noshow_prob, specialty_code, origin, status).
- `plan_review`: auditoría (id, schedule_run_id FK, action, user_name, role, note, created_at).

**Restricciones**:
- `NOT is_current OR review_status = 'approved'`: un plan solo puede ser vigente si está aprobado.
- Índice único parcial: un solo plan vigente por `run_id`.

### Limitaciones conocidas

1. **Memoria**: la corrida sintética se carga completa en memoria la primera vez que una ruta la necesita (`CatalogProvider`); la app arranca sin datos. Si la corrida no existe o no se puede leer, las rutas que la usan responden 503.

2. **Sobrecupo y modelo de inasistencias**: la política `optimized` con `overbooking=true` requiere que el modelo de inasistencias esté entrenado (`models/noshow/<run_id>/noshow_model.joblib`). Sin él, el trabajo falla con un mensaje de error descriptivo. Las políticas `fifo` y `priority` no lo necesitan.

3. **Tiempo de programación**: `optimized` con 100.000 entradas y 4 semanas tardó 74,3 s de reloj en la corrida canónica (55,5 s del plan final más 18,8 s de una primera pasada descartada) y gastó 103,0 de las 120 unidades de tiempo determinista del presupuesto global `time_limit_s`; en esa corrida el presupuesto se agotó (53 fases terminaron por el límite). Ver `docs/scheduler-formulation.md` §11.3. Más semanas o más entradas lo alargan. Un `time_limit_s` menor no deja el problema infactible: el programador siempre entrega un plan factible (parte de la solución voraz), pero puede quedar más lejos del óptimo (`solver_status` `FEASIBLE` o `UNKNOWN`).

4. **Usuarios sin identidad**: la autenticación es por clave API estática en un archivo JSON. No hay integración con proveedor de identidad (LDAP, OAuth). Cambiar las claves requiere editar el archivo y reiniciar.

5. **Generación de resultados**: la simulación (`/v1/simulation`) no se genera desde la API; es un artefacto de `make simulate` (unos 6 min con la configuración por defecto; se guarda en `results/simulation.json`).

6. **Trabajos volátiles**: los trabajos de programación viven en memoria aunque `PRIORIZA_API_STORE=sql`; al reiniciar el proceso se pierde el estado de los pendientes o en curso (`GET /v1/schedule-runs/{job_id}` da 404), no los planes ya guardados. Una programación `optimized` en curso no se interrumpe al detener el servidor.
7. **Planes sin solicitante**: los planes escritos por la CLI (`make schedule SCHEDULE_ARGS=--persist`) no registran solicitante; la API no permite revisarlos (la regla de cuatro ojos falla cerrada) y no trae sus explicaciones (`/explanations` devuelve `total: 0`).
8. **Vigencia**: un plan vigente solo deja de serlo al activar otro plan aprobado de la misma corrida; no hay una acción para retirarlo sin reemplazo. `/v1/plans/current` responde 503 si la corrida configurada no está disponible (nunca devuelve el vigente de otra corrida).
9. **Explicaciones en SQL**: van dentro de `schedule_run.params` y se paginan en memoria; los listados de planes no las leen.

---

## 8. OpenAPI y documentación interactiva

La API expone una especificación **OpenAPI 3.1** en `/openapi.json`:

```bash
curl http://localhost:8000/openapi.json | jq . | head -50
```

Documentación interactiva: **Swagger UI** en `/docs` y **ReDoc** en `/redoc`.

```bash
# Swagger UI (recomendado para probar endpoints)
http://localhost:8000/docs

# ReDoc (visualización más limpia)
http://localhost:8000/redoc
```

Cada operación documenta sus códigos de error con ejemplos (401, y según la ruta 403, 404, 409, 429 o 503).
