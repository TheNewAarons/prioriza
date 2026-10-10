# Seguridad

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Este documento describe los controles implementados en P16-T1 y lo que falta antes de tocar datos reales. **No afirma cumplimiento legal** de ninguna norma de protección de datos personales.

## Modelo de amenazas (breve)

| Activo | Amenaza | Control principal |
|---|---|---|
| Lista de espera y planes | Acceso sin autenticar o con rol insuficiente | Claves por usuario (`X-API-Key`), roles `gestor`/`revisor`/`lectura`, cuatro ojos en la revisión |
| Disponibilidad de la API | Cuerpos enormes, ráfagas de peticiones, programaciones gigantes | Límites de cuerpo, de parámetros, de peticiones por clave y de tiempo de trabajo |
| Claves de API y datos personales | Filtración por logs | Redacción central de logs (`shared.logging`) |
| Superficie expuesta | Documentación interactiva, CORS abierto, cabeceras Host falsas | Valores por defecto cerrados, `production` sin `/docs`, lista blanca de hosts y orígenes |
| Navegador del panel | Clickjacking, sniffing de tipos, caché de datos | Cabeceras de seguridad y CSP en Flask, `debug` apagado |
| Dependencias | Vulnerabilidades conocidas | `pip-audit` sobre el lock exportado |

Fuera de alcance hoy: atacantes con acceso al host, ataques de denegación de servicio distribuidos, robo de las claves desde el navegador del usuario (la sesión del panel vive en `sessionStorage`).

## Controles implementados

Todos los valores viven en `ApiSettings` (`PRIORIZA_API_*`) o `DashboardSettings` (`PRIORIZA_DASHBOARD_*`).

### API (`api/src/api/security.py`, `settings.py`, `main.py`)

| Control | Variable | Defecto | Respuesta | Test |
|---|---|---|---|---|
| Tamaño máximo del cuerpo (revisa `Content-Length` y corta el flujo si no viene) | `MAX_BODY_BYTES` | 65536 (64 KiB) | 413 | `test_body_too_large_by_content_length_is_413`, `..._without_content_length_...` |
| Largo de ids y parámetros de ruta o consulta | `MAX_ID_LENGTH` | 64 | 422 | `test_long_path_id_is_422`, `test_long_query_param_is_422` |
| Largo de notas de revisión y activación | `MAX_NOTE_LENGTH` | 1000 | 422 | `test_long_review_note_is_422` |
| Tope de `horizon_weeks` | `MAX_HORIZON_WEEKS` | 12 | 422 | `test_schedule_horizon_and_time_limit_caps` |
| Tope de `time_limit_s` | `MAX_TIME_LIMIT_S` | 600 | 422 | `test_schedule_horizon_and_time_limit_caps` |
| Tope de filas de `GET /v1/plans/{id}/export` (el archivo avisa con `# truncado`; `limit` mayor es 422) | `MAX_EXPORT_ROWS` | 50000 | 422 | `test_export_cap_is_enforced`, `test_export_limit_offset_and_truncation_notice` |
| Inyección de fórmulas en el CSV exportado (celdas de texto que empiezan con `=`, `+`, `-`, `@`, tab o CR se prefijan con `'`) | (fija) | siempre | `'` delante | `test_formula_neutralization`, `test_export_neutralizes_formulas_in_stored_rows` |
| Peticiones por usuario (ventana deslizante de 60 s, en memoria; sin clave válida, por IP); `/healthz` exento | `RATE_LIMIT_PER_MINUTE` | 120 | 429 + `Retry-After` | `test_rate_limit_429_with_retry_after_and_healthz_exempt`, `test_rate_limit_window_slides`, `test_rate_limit_fake_keys_share_ip_bucket` |
| Tiempo máximo de un trabajo: `time_limit_s * JOB_TIMEOUT_FACTOR + JOB_TIMEOUT_GRACE_S` | `JOB_TIMEOUT_FACTOR`, `JOB_TIMEOUT_GRACE_S` | 2.0 y 30 s | trabajo `failed` | `test_job_timeout_marks_failed` |
| Cabeceras `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, CSP (`default-src 'none'`; `/docs` y `/redoc` con su propia CSP) | (fijas) | siempre | todas las respuestas, incluidas 413, 422 y 429 | `test_security_headers_on_every_response`, `test_docs_have_their_own_csp` |
| Entorno: en `production` se apagan `/docs`, `/redoc` y `/openapi.json` | `ENVIRONMENT`, `DOCS_ENABLED` | `development`, `null` | 404 | `test_production_disables_docs_unless_enabled` |
| Producción exige archivo de usuarios definido, existente y con permisos 600 o más estrictos (en desarrollo solo advierte) | `USERS_FILE` | sin archivo | la app no arranca | `test_production_requires_users_file`, `..._rejects_open_permissions`, `..._development_only_warns_...` |
| CORS desactivado; lista blanca explícita si se configura | `CORS_ORIGINS` | vacío | sin cabeceras CORS | `test_no_cors_by_default_and_allowlist_when_set` |
| Lista blanca de cabecera Host | `TRUSTED_HOSTS` | `localhost`, `127.0.0.1`, `api` | 400 | `test_untrusted_host_is_rejected` |

Limitación conocida del tiempo máximo de trabajos: un hilo de Python no se puede matar. Al vencer el plazo el trabajo se marca `failed` con un mensaje, pero CP-SAT sigue hasta terminar su propio `time_limit_s`; si llega a guardar un plan, queda `pending` (requiere revisión humana) y el trabajo no se reporta exitoso. El límite de trabajos activos (`MAX_ACTIVE_JOBS*`) sigue contando solo trabajos `queued`/`running`, así que un trabajo vencido libera su cupo aunque su hilo siga ocupado; hay un solo hilo de ejecución, por lo que las siguientes programaciones esperan en cola.

El limitador de peticiones es por proceso: con varias réplicas el tope efectivo se multiplica. Detrás de un proxy, la IP vista es la del proxy (afecta solo a peticiones sin clave válida).

### Panel (`dashboard/src/dashboard/app.py`, `config.py`, `cli.py`)

| Control | Defecto | Test |
|---|---|---|
| `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` y CSP compatible con Dash (`'unsafe-inline'`/`'unsafe-eval'` para scripts, Google Fonts para la tipografía) en cada respuesta; `PRIORIZA_DASHBOARD_CONTENT_SECURITY_POLICY` la reemplaza | activas | `test_security_headers_on_pages_and_healthz` |
| `debug` apagado y rechazo de `--debug` con un host no local | apagado | `test_debug_is_off_by_default`, `test_cli_refuses_debug_on_public_host` |
| La clave de API no se registra: se añade al redactor al iniciar sesión | siempre | `test_api_key_never_appears_in_logs` |

La CSP del panel incluye `'unsafe-inline'` y `'unsafe-eval'` porque Dash y plotly lo requieren; es más débil que la de la API.

### Logs sin datos personales (`shared/src/shared/logging.py`)

`install_redaction()` (llamado por `create_app` de la API y del panel) instala una fábrica de `LogRecord` que limpia el mensaje y cada argumento textual antes de que lo vea cualquier manejador. Cubre todos los loggers, incluidos el access log de uvicorn y werkzeug. Conserva la estructura de `args`, por lo que el `AccessFormatter` de uvicorn sigue funcionando.

Se redactan: ids tras `/patients/`, `/entries/` y variantes; `patient_id=`/`entry_id=`; "paciente X" cuando X lleva dígitos; RUT chilenos; correos; la cabecera `X-API-Key`; y cualquier valor registrado con `register_secret` (la API registra todas las claves del archivo de usuarios; el panel, la clave de quien inicia sesión; mínimo 8 caracteres). El panel además sube werkzeug a WARNING.

Verificado también en vivo con la demo: el access log de uvicorn registra `GET /v1/patients/[REDACTADO]` para un paciente existente y uno inexistente, sin el id ni la clave.

Tests: `shared/tests/test_logging.py` (patrones, `caplog`, excepciones, idempotencia) y `api/tests/test_api_security.py::test_uvicorn_access_log_redacts_patient_id_and_key` (usa el `AccessFormatter` real de uvicorn).

Límites: es una red de seguridad basada en patrones, no una garantía. Un identificador con otro formato o un dato personal en texto libre puede no detectarse; el código no debe registrar datos personales en primer lugar. Los trazados de excepción también se limpian al crear el registro (la fábrica deja `exc_text` ya redactado), así que los manejadores propios de uvicorn o werkzeug, sin `RedactingFilter`, reciben el trazado limpio (test `test_traceback_redacted_in_handlers_without_filter`). El detalle de los errores no incluye rutas ni trazas (ver `api/jobs.py`).

### Contraseña de PostgreSQL (`shared/src/shared/config.py`)

Con `ENVIRONMENT=production` y sin `DATABASE_URL`, `Settings` lanza `ValueError` si `POSTGRES_PASSWORD` es la de ejemplo (`change-me`) o está vacía; el mensaje no imprime la contraseña. En `development` el valor por defecto sigue permitido (docker-compose y `.env.example` no cambian). Test: `shared/tests/test_shared_config.py`.

## Artefactos del modelo

`joblib` deserializa pickle, que puede ejecutar código arbitrario al cargarse. `noshow.train.save` guarda el SHA-256 del `.joblib` en `metadata.json` (`joblib_sha256`) y `load_verified_bundle` lo verifica ANTES de `joblib.load`; el programador y el simulador solo cargan modelos con esa función. Si falta `metadata.json`, falta el hash o no coincide, lanza `ValueError` y no carga nada.

Alcance: esto detecta corrupción o reemplazo parcial del archivo. No protege si un atacante puede escribir ambos archivos (modelo y `metadata.json`): el directorio de modelos debe ser de confianza, con escritura restringida al proceso de entrenamiento. Tests: `noshow/tests/test_noshow_pipeline.py` (`test_load_verified_bundle_*`).

## Auditoría de dependencias

Comando (también `make audit`):

```
uv export --all-packages --no-hashes --no-emit-workspace --format requirements-txt \
  | uv run pip-audit -r /dev/stdin --disable-pip --no-deps
```

Resultado del 2026-10-09 sobre 395 dependencias exportadas del lock: **No known vulnerabilities found**. No hay vulnerabilidades altas ni críticas que corregir o justificar. Repetir antes de cada entrega y al actualizar `uv.lock`.

## Qué falta antes de usar datos reales

Nada de lo siguiente existe hoy; ninguno de los controles anteriores lo sustituye.

1. **Proveedor de identidad**: reemplazar las claves estáticas por autenticación institucional (SSO/OIDC), con expiración, rotación y revocación; hoy las claves son de larga vida y se comparten por archivo.
2. **TLS**: terminar HTTPS delante de la API y del panel (proxy inverso) y añadir HSTS. Hoy se sirve HTTP plano en `127.0.0.1`/red de compose.
3. **Cifrado en reposo**: de PostgreSQL, de los Parquet de `data/` y de las copias de seguridad.
4. **Retención**: política de retención y borrado de la auditoría de revisiones, de los planes y de los logs; hoy no hay rotación ni caducidad (salvo los trabajos en memoria, `JOB_TTL_HOURS`).
5. **Límite de peticiones distribuido** y protección contra DoS en el borde si hay varias réplicas o exposición pública.
6. **Revisión legal** de protección de datos personales y de datos de salud (normativa chilena vigente, finalidad, base de licitud, evaluación de impacto, convenios con los servicios de salud), y validación institucional de los modelos. Este repositorio no ha pasado por ninguna.
7. **Pruebas de seguridad**: revisión independiente, pruebas de penetración y análisis estático de seguridad adicional.
8. **Permisos del archivo de usuarios en contenedores**: con un bind mount, el modo 600 depende del dueño del archivo en el host; en producción conviene usar secretos del orquestador.
