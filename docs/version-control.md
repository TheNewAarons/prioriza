# Plan de control de versiones

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Modelo de ramas

Desde el 2026-10-09, **commits directos en `main`** (decisión del usuario, `docs/decisions.md` §16): sin ramas de
trabajo ni Pull Requests. Motivo: con PR integrados por *squash* y ramas apiladas, cada integración obligaba a
rebasar las ramas siguientes y resolver conflictos; con un solo autor (la sesión principal) el PR no aportaba
revisión adicional.

- `main`: siempre en verde (lint, typecheck y tests pasan). Es la única rama.
- Cada commit va directo a `main` local con `make lint typecheck test` en verde; el push a `origin/main` pasa por el
  hook `pre-push` y se hace cuando el usuario lo pide.
- La revisión que antes daba el PR la da `reviewer` antes de commitear un módulo importante.
- Etiquetas `vMAJOR.MINOR.PATCH` (SemVer) en `main` al cerrar cada hito (por ejemplo, al terminar un módulo del pipeline).
- Historial: hasta el PR #16 se usó trunk-based con ramas cortas `feat/`, `fix/`, `docs/`… e integración por PR.

## Cuándo commitear

Un commit por cada cambio lógico y verificado, nunca al final de una sesión larga:

1. Termina una unidad coherente (un módulo, un endpoint, una migración, un fix).
2. Corre `make lint typecheck test`; solo se commitea en verde. El hook de pre-commit lo refuerza (ruff y mypy).
3. Commit con mensaje según la convención de abajo.
4. Si el cambio toca una migración de Alembic, el commit incluye la migración y el modelo juntos.

Reglas:

- No se commitea código roto "para guardar"; para eso se usa `git stash` o una rama WIP local que no se sube.
- `uv.lock` se commitea siempre junto con el cambio de `pyproject.toml` que lo provoca. Toda dependencia nueva se justifica en `docs/decisions.md` en el mismo commit.
- Resultados de experimentos (`results/*.json`) se commitean junto con el código y la semilla que los produjo.
- Nunca se commitean: `.env`, secretos, datos de pacientes reales, datos crudos descargados (`data/raw/`), artefactos de modelos pesados.

## Mensajes de commit

[Conventional Commits](https://www.conventionalcommits.org/) con descripción en español:

```
<tipo>(<ámbito opcional>): <resumen en imperativo, ≤ 72 caracteres>

<cuerpo opcional: por qué, no qué>
```

Tipos: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
Ámbitos: nombre del paquete (`shared`, `priority`, `scheduler`, `noshow`, …), `docker`, `agents`.

Ejemplo: `feat(priority): agrega puntaje por plazo de garantía GES`.

## Protección de `main`

- La regla de GitHub sigue pidiendo PR y el check `checks`; el push directo la salta con permisos de administrador y
  GitHub lo registra ("Bypassed rule violations"). Esto es intencional mientras rija el modelo de commits directos.
- No se permiten *force push* ni borrado de `main`: el historial de `main` nunca se reescribe.
- Antes de commitear, `git pull --ff-only` para no divergir de `origin/main`.

## Hooks locales y CI

- `make hooks` instala dos hooks de git con pre-commit:
  - `pre-commit`: ruff (check y format) y mypy sobre los archivos del commit.
  - `pre-push`: `make lint typecheck test` sin red (`UV_OFFLINE=1`), los mismos chequeos que `.github/workflows/ci.yml`. Si algo falla, el push se cancela.
- Mientras GitHub Actions no esté disponible (cuenta bloqueada por facturación), el hook `pre-push` reemplaza a CI. Limitaciones: solo protege los pushes desde máquinas donde se instaló el hook, se puede saltar con `git push --no-verify` (no hacerlo), y verifica el árbol de trabajo, no solo los commits que se suben: conviene hacer push con el árbol limpio.
- Como el check `checks` de CI no se ejecuta, el hook `pre-push` en verde es la única verificación antes de subir a `main`.

## Flujo de trabajo con subagentes

La sesión principal es la única que hace commits y pushes: revisa el trabajo de cada subagente, corre `make lint typecheck test` y recién entonces commitea en `main`. Tras cada módulo importante, `reviewer` revisa los cambios antes del commit.
