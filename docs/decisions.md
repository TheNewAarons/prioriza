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

- Repositorio en GitHub, privado por defecto (proyecto de investigación; se puede publicar después).
- Trunk-based con ramas cortas, Conventional Commits en español, `main` protegida por CI. Detalle en [version-control.md](version-control.md).
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

## Referencias
- [CLAUDE.md](../CLAUDE.md): Stack y convenciones del proyecto.
