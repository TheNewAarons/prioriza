# Prioriza

Sistema de apoyo a la gestión de listas de espera hospitalarias en Chile. Combina tres piezas:

1. **Priorización transparente**: un puntaje por paciente basado en reglas explícitas (prioridad clínica declarada, tiempo de espera, plazos de garantías GES), auditable y explicable.
2. **Predicción de inasistencias**: modelo de scikit-learn calibrado que estima la probabilidad de que un paciente no se presente a su cita o cirugía.
3. **Programación óptima**: modelo de OR-Tools CP-SAT que asigna pacientes a cupos (pabellones, horas de especialista) respetando capacidades y plazos, y usa la probabilidad de inasistencia para sobreagendar de forma controlada.

Un simulador compara políticas (orden de llegada, solo prioridad, optimizada) a lo largo de meses, y un panel Dash muestra todo.

## Problema que resuelve

Al 30-09-2025 la lista de espera no GES del sistema público sumaba 2,58 millones de interconsultas para consulta nueva de especialidad (2,13 millones de personas, mediana 242 días) y 417 mil para intervenciones quirúrgicas (mediana 264 días), además de 80 mil garantías GES retrasadas (Glosa 06, III trimestre 2025, Minsal; ver `docs/data-sources.md`). Además, la información se publica de forma heterogénea entre servicios de salud. Prioriza muestra cómo ordenar y programar mejor con la misma capacidad, y cuantifica la ganancia con simulación.

## Alcance, privacidad y ética (obligatorio)

- **No se usan datos de pacientes reales.** Solo datos públicos agregados (por ejemplo, de datos.gob.cl o reportes del Minsal) y una población **sintética** calibrada contra esos agregados. Nunca se agregan nombres, RUT ni datos clínicos reales, ni siquiera en fixtures.
- **El sistema apoya, no decide.** La prioridad clínica es un dato de entrada definido por profesionales; el sistema nunca la infiere ni la sobreescribe. Todo plan generado requiere revisión humana antes de usarse.
- **Equidad.** El modelo de inasistencias no puede usar como variables atributos protegidos (sexo, etnia, nacionalidad) ni proxies evidentes. Se mide si el sobreagendamiento perjudica sistemáticamente a algún grupo (comuna, grupo etario, previsión) y se reporta.
- Aviso visible en el panel, en el README y en todo informe: *"Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional."*
- Nunca se ocultan resultados negativos: si la política optimizada no mejora en alguna métrica o grupo, se reporta tal cual.

## Arquitectura

```
Datos públicos agregados ──► ingestion/  ──► calibra ──► synthetic/ (población sintética)
                                                              │
                                ┌─────────────────────────────┤
                                ▼                             ▼
                        priority/ (reglas)           noshow/ (scikit-learn, calibrado)
                                │                             │
                                └──────────► scheduler/ (CP-SAT) ◄──┘
                                                   │
                                                   ▼
                                     simulation/ (SimPy, compara políticas)
                                                   │
                                                   ▼
                              api/ (FastAPI)  +  dashboard/ (Dash)  +  reports/
```

## Stack y convenciones

- Python 3.12, `uv` workspace (miembros: `shared`, `ingestion`, `synthetic`, `priority`, `noshow`, `scheduler`, `simulation`, `api`, `dashboard`), `ruff`, `mypy --strict` en `shared/`, `priority/` y `scheduler/`, `pytest`, `hypothesis`.
- Datos: PostgreSQL 16 (SQLAlchemy 2 + Alembic, porque aquí no hay Django), `polars` para transformaciones.
- Modelos: `ortools` (CP-SAT), `scikit-learn`, `simpy`.
- Interfaz: `dash` + `dash-bootstrap-components` + `plotly`. API: FastAPI.
- Identificadores de código en inglés; docstrings, comentarios y documentación en español.
- Reproducibilidad: semillas fijas en todo lo aleatorio, splits temporales (no aleatorios) para el modelo de inasistencias, resultados de experimentos versionados en `results/*.json`.
- Ningún test de CI depende de la red; las descargas reales usan fixtures grabadas.

## Subagentes y asignación de modelos

El proyecto define subagentes en `.claude/agents/`. La sesión principal **orquesta**: planifica, delega y verifica. Regla de asignación por esfuerzo:

> **Precedencia:** si esta tabla entra en conflicto con el routing por niveles (secciones 2 a 4, al final de este archivo), manda el routing por niveles. Las tareas de Tier 2 y Tier 3 se delegan a `claude-ds`, `claude-qwen` o `claude-kimi` en vez de a los subagentes sonnet/haiku de esta tabla.

| Subagente | Modelo | Para qué |
|---|---|---|
| `architect` | opus | Diseño de módulos, modelado matemático de CP-SAT, decisiones de trade-off |
| `optimizer` | opus | Implementar y depurar el modelo CP-SAT y su rendimiento |
| `ml-engineer` | opus | Modelo de inasistencias, calibración, evaluación de equidad |
| `implementer` | sonnet | Implementación general: módulos, API, panel, simulación |
| `test-writer` | sonnet | Tests, tests de propiedad, fixtures |
| `data-researcher` | sonnet | Buscar y verificar fuentes de datos públicos en internet |
| `docs-writer` | haiku | Documentación, README, docstrings, changelog |
| `chore` | haiku | Tareas mecánicas: configuración, Makefile, formateo, renombres |
| `reviewer` | opus | Revisión crítica de solo lectura (no edita archivos) |

Reglas:
- No usar opus para tareas mecánicas ni haiku para lógica de optimización o ML.
- Tareas independientes se delegan en paralelo; tareas que dependen entre sí, en secuencia.
- La sesión principal revisa el resultado de cada subagente y corre tests antes de dar algo por terminado.
- Al terminar un módulo importante, `reviewer` lo revisa antes de pasar al siguiente prompt.

## Comandos

```
make up / down         # postgres + api + dashboard
make migrate           # alembic upgrade head
make ingest            # descarga datos públicos agregados
make synth             # genera población sintética calibrada
make train-noshow      # entrena y calibra el modelo de inasistencias
make schedule          # corre el programador CP-SAT sobre un escenario
make simulate          # compara políticas con SimPy
make report            # genera docs/results.md y .html
make dashboard         # levanta el panel Dash
make test / lint / typecheck
```

## Forma de trabajar

- Antes de una tarea grande, pide a `architect` un plan corto; si hay ambigüedad real, pregunta; si no, decide y sigue.
- Después de cada tarea: tests, lint y typecheck en verde, y un resumen de qué se hizo, qué subagentes se usaron y qué queda pendiente.
- Si una decisión cambia algo de este archivo, actualízalo junto con `docs/decisions.md`.
- No agregues dependencias sin justificarlas en `docs/decisions.md`.
- Control de versiones según `docs/version-control.md`: ramas cortas desde `main`, Conventional Commits en español, un commit por cambio lógico y solo con `make lint typecheck test` en verde. Solo la sesión principal commitea y hace push.



## Metodología de Selección de Modelos (Routing)

Tienes a tu disposición comandos alias redirigidos a OpenCode Go (vía LiteLLM local) y acceso nativo a Anthropic.
Analiza la complejidad de la tarea antes de ejecutar cambios grandes:

1. **Tareas de Mantenimiento / Escaneo / Tests (Usar OpenCode Go):**
   - LECTURA: Lectura masiva de archivos, auditorías de logs, búsqueda de patrones.
   - BOILERPLATE: Generación de unit tests, tipos de TypeScript/Zod, documentación JSDoc.
   - Sugiere o ejecuta mediante sub-proceso/CLI con `claude-qwen` o `claude-ds`.

2. **Tareas Críticas y Arquitectura (Usar Claude Pro / Sonnet / Opus):**
   - REFACTORING CORE: Modificación de la arquitectura principal de la app.
   - BUGS COMPLEJOS: Errores de concurrencia, lógica de negocio intrincada o memory leaks.
   - Mantén la ejecución actual nativa en Claude Code.

3. **Flujo Híbrido:**
   - Si la tarea requiere más de 5 archivos de contexto preliminar, usa primero `claude-qwen` para redactar un resumen en `TASK_PLAN.md` y luego retoma la implementación crítica en la sesión nativa.

## 2. Arquitectura de Agentes y Enrutamiento por Esfuerzo (Agent Routing)

> **Precedencia:** estas secciones (2 a 4) mandan sobre la tabla de "Subagentes y asignación de modelos" y sobre "Metodología de Selección de Modelos" cuando haya conflicto.

Este proyecto y entorno de trabajo utiliza una estrategia de **routing de modelos en 3 niveles (Tiers)** según la complejidad, esfuerzo y volumen de tokens de cada tarea. Tu objetivo es optimizar la precisión y preservar el presupuesto de tokens contextualmente.

### Tabla de Niveles y Delegación

| Nivel / Tier | Esfuerzo / Tipo de Tarea | Modelo Objetivo | Ejecución / Alias |
| :--- | :--- | :--- | :--- |
| **Tier 1: High Effort** | Arquitectura core, debugging complejo de concurrencia, refactorizaciones críticas, lógica de negocio intrincada. | Claude 3.7 Sonnet / Opus (Nativo) | `claude` |
| **Tier 2: Mid Effort** | Implementación de features estándar, algoritmos, refactorización de componentes, endpoints API. | DeepSeek V4 / Qwen 3.7 Max | `claude-ds` / `claude-qwen` |
| **Tier 3: Low Effort / Bulk** | Generación de unit tests, tipos Zod/TypeScript, JSDoc/documentación, escaneo de repos, linters. | Kimi K3 / Qwen 3.7 Max | `claude-kimi` / `claude-qwen` |

---

## 3. Reglas Autónomas de Delegación

Cuando operes como agente principal (`claude` nativo):

1. **Evaluación Preliminar del Prompt:** Antes de ejecutar una tarea masiva (más de 3 archivos o más de 200 líneas de código a modificar/generar):
   - Si la tarea es de **Tier 2 o Tier 3**, advierte al usuario o genera un script para delegarla al subagente correspondiente mediante `claude-qwen`, `claude-ds` o `claude-kimi`.
2. **Estrategia "Plan First, Code Later":**
   - Para tareas que requieran leer más de 5 archivos de contexto:
     1. Usa un subagente de **Tier 3** (`claude-kimi` o `claude-qwen`) para escanear la estructura y redactar/actualizar el archivo `TASK_PLAN.md`.
     2. Retoma la sesión principal en **Tier 1** (`claude`) para leer `TASK_PLAN.md` e implementar la solución crítica.

---

## 4. Estado Compartido y Sincronización entre Agentes

Para garantizar que el cambio de contexto entre subagentes sea continuo y sin pérdida de información:

- **`TASK_PLAN.md`:** Debe usarse como el tablero de transferencia entre agentes.
  - *Estructura obligatoria:*
    ```markdown
    # Plan de Trabajo
    - [ ] Tarea 1 (Asignada a: Tier 3 - Qwen) -> Estado
    - [ ] Tarea 2 (Asignada a: Tier 1 - Claude) -> Estado
    ```
- Cada subagente que termine una fase debe actualizar el estado del paso en `TASK_PLAN.md` y dejar un breve log de lo realizado antes de ceder el control.

---
