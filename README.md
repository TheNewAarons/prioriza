# Prioriza

> **Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.**

## Qué es

Prioriza es un sistema de apoyo a la gestión de listas de espera hospitalarias en Chile. Combina tres componentes:

1. **Priorización transparente**: un puntaje por paciente basado en reglas explícitas (prioridad clínica declarada, tiempo de espera, plazos de garantías GES), auditable y explicable. *[Pendiente]*

2. **Predicción de inasistencias**: modelo de scikit-learn calibrado que estima la probabilidad de que un paciente no se presente a su cita o cirugía. *[Pendiente]*

3. **Programación óptima**: modelo de OR-Tools CP-SAT que asigna pacientes a cupos (pabellones, horas de especialista) respetando capacidades y plazos, y usa la probabilidad de inasistencia para sobreagendar de forma controlada. *[Pendiente]*

Un **simulador** (SimPy) compara políticas (orden de llegada, solo prioridad, optimizada) a lo largo de meses, y un **panel** Dash muestra todos los resultados.

### Estado actual

**Implementado:**
- Ingesta de datos públicos agregados (Glosa 06 del Minsal, Estadísticas GES, datos.gob.cl).
- Población sintética calibrada contra esos agregados (registros de pacientes, entradas en listas de espera, citas históricas).
- Modelo de datos (PostgreSQL con SQLAlchemy + Alembic).
- API mínima y panel mínimo (estructura).

**Pendiente:**
- Módulo de priorización explícita.
- Modelo de inasistencias calibrado.
- Programador CP-SAT.
- Simulación de políticas.
- Informes y panel funcional.

## Principios

- **Sin datos de pacientes reales**: solo datos públicos agregados (datos.gob.cl, reportes del Minsal) y una población sintética calibrada contra ellos. Nunca se agregan nombres, RUT ni datos clínicos reales.

- **El sistema apoya, no decide**: la prioridad clínica es un dato de entrada definido por profesionales; el sistema nunca la infiere ni la sobreescribe. Todo plan generado requiere revisión humana antes de usarse.

- **Equidad**: el modelo de inasistencias no puede usar atributos protegidos (sexo, etnia, nacionalidad) ni proxies evidentes. Se mide y reporta si el sobreagendamiento perjudica sistemáticamente a algún grupo (comuna, grupo etario, previsión).

- **Transparencia de resultados**: nunca se ocultan resultados negativos. Si la política optimizada no mejora en alguna métrica o grupo, se reporta tal cual.

## Requisitos

- Python 3.12
- `uv` (gestor de paquetes y workspace)
- Docker y Docker Compose

## Puesta en marcha

```bash
# Clonar y entrar al directorio
git clone <repo> && cd Prioriza

# Sincronizar dependencias
make sync

# Instala los hooks de git (pre-commit; pre-push corre lint, typecheck y tests)
make hooks

# Levanta PostgreSQL, API y estructura de servicios
make up

# Ejecuta migraciones de base de datos
make migrate

# Descarga datos públicos agregados
make ingest

# Genera población sintética calibrada (100.000 registros por defecto)
make synth

# Verifica el código
make test lint typecheck

# Detiene los servicios
make down
```

**Opciones adicionales:**

```bash
# Tamaño de población: make synth SIZE=50000
# Semilla: make synth SEED=123
# Carga a BD: make synth load=true
```

## Estructura del monorepo

Workspace `uv` con 9 miembros:

| Módulo | Descripción |
|---|---|
| `shared/` | Configuración, enums, sesiones de BD, utilidades comunes. |
| `ingestion/` | CLI `prioriza-ingest`: descarga datos públicos, parsea PDF, valida. |
| `synthetic/` | CLI `prioriza-synth`: genera población sintética, calibración, validación. |
| `priority/` | *[Pendiente]* Cálculo de prioridad por reglas explícitas. |
| `noshow/` | *[Pendiente]* Modelo de scikit-learn para predicción de inasistencias. |
| `scheduler/` | *[Pendiente]* Asignación con OR-Tools CP-SAT. |
| `simulation/` | *[Pendiente]* Simulador de políticas con SimPy. |
| `api/` | API mínima FastAPI. |
| `dashboard/` | Panel Dash (estructura, pendiente vistas funcionales). |

## Documentación

- **[docs/data-sources.md](docs/data-sources.md)**: fuentes de datos públicos verificadas, cifras y advertencias sobre licencias.
- **[docs/synthetic-data.md](docs/synthetic-data.md)**: descripción de la población sintética, calibración, variables y supuestos.
- **[docs/decisions.md](docs/decisions.md)**: decisiones arquitectónicas (workspace, dependencias, control de versiones).
- **[docs/version-control.md](docs/version-control.md)**: estrategia de control de versiones y reproducibilidad.
- **[docs/design/](docs/design/)**: planes detallados (síntesis del modelo de inasistencias, etc.).

## Licencia de datos

Las fuentes de datos públicos se citan en [docs/data-sources.md](docs/data-sources.md). Los PDF fuente (ej. Glosa 06 del Minsal) **no se redistribuyen** en el repositorio; se usan solo mediante URL verificadas y SHA256.

Licencias de entrada:
- **Glosas 06 (Minsal)**: no indicada en la fuente.
- **Estadísticas GES (Superintendencia de Salud)**: no indicada.
- **Catálogo de establecimientos (datos.gob.cl)**: CC0.
- **Literatura (Salinas 2014, Sepúlveda 2024, etc.)**: CC BY-NC 3.0 o similar (ver [docs/data-sources.md](docs/data-sources.md)).

El proyecto aún no define una licencia para el código ni para la población sintética generada. Todo uso queda sujeto al aviso de investigación con datos sintéticos.
