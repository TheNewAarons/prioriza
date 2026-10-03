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

## Flujo de trabajo con subagentes

La sesión principal es la única que hace commits y pushes: revisa el trabajo de cada subagente, corre `make lint typecheck test` y recién entonces commitea. Tras cada módulo importante, `reviewer` revisa la rama antes de abrir el PR.
