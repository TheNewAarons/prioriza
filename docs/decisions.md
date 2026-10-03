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

---

## Referencias
- [CLAUDE.md](../CLAUDE.md): Stack y convenciones del proyecto.
