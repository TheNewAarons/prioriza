# Plan de control de versiones

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Modelo de ramas

Trunk-based con ramas cortas:

- `main`: siempre en verde (lint, typecheck y tests pasan). Es la única rama de larga vida.
- Ramas de trabajo, cortas (idealmente < 3 días), creadas desde `main` actualizado:
  - `feat/<paquete>-<tema>` — funcionalidad nueva (p. ej. `feat/priority-score-rules`).
  - `fix/<paquete>-<tema>` — corrección de errores.
  - `docs/<tema>`, `chore/<tema>`, `ci/<tema>`, `refactor/<tema>`, `test/<tema>`.
- Integración a `main` mediante Pull Request con CI en verde. Merge tipo *squash* cuando la rama tiene commits de trabajo intermedios; *rebase* cuando cada commit ya es atómico y verde.
- Etiquetas `vMAJOR.MINOR.PATCH` (SemVer) en `main` al cerrar cada hito (por ejemplo, al terminar un módulo del pipeline).

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

- Se requiere PR y el check `checks` de CI en verde antes de integrar.
- No se permiten *force push* ni borrado de `main`.
- GitHub borra automáticamente la rama remota al integrar un PR (`delete_branch_on_merge`). La copia local se borra a mano: `git switch main && git pull --ff-only && git fetch --prune`, luego confirmar que el PR está integrado (`gh pr view <rama> --json state`) y `git branch -D <rama>`. Se usa `-D` porque con *squash* o *rebase* los commits de la rama no quedan en `main` con el mismo hash y `git branch -d` los rechaza como no integrados.

## Hooks locales y CI

- `make hooks` instala dos hooks de git con pre-commit:
  - `pre-commit`: ruff (check y format) y mypy sobre los archivos del commit.
  - `pre-push`: `make lint typecheck test` sin red (`UV_OFFLINE=1`), los mismos chequeos que `.github/workflows/ci.yml`. Si algo falla, el push se cancela.
- Mientras GitHub Actions no esté disponible (cuenta bloqueada por facturación), el hook `pre-push` reemplaza a CI. Limitaciones: solo protege los pushes desde máquinas donde se instaló el hook, se puede saltar con `git push --no-verify` (no hacerlo), y verifica el árbol de trabajo, no solo los commits que se suben: conviene hacer push con el árbol limpio.
- Como el check `checks` de CI no se ejecuta, integrar un PR requiere saltarse la protección de `main` (`gh pr merge --admin`), siempre con autorización explícita y con el hook `pre-push` en verde.

## Flujo de trabajo con subagentes

La sesión principal es la única que hace commits y pushes: revisa el trabajo de cada subagente, corre `make lint typecheck test` y recién entonces commitea. Tras cada módulo importante, `reviewer` revisa la rama antes de abrir el PR.
