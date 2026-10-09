# Prioriza

**Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.**

## Qué es

Prioriza es un sistema de apoyo a la gestión de listas de espera hospitalarias en Chile. Integra tres componentes:

1. **Priorización transparente**: un puntaje por paciente basado en reglas explícitas (prioridad clínica declarada, tiempo de espera, plazos de garantías GES), auditable y explicable.

2. **Predicción de inasistencias**: modelo de scikit-learn calibrado que estima la probabilidad de que un paciente no se presente a su cita o cirugía.

3. **Programación óptima**: modelo de OR-Tools CP-SAT que asigna pacientes a cupos (pabellones, horas de especialista) respetando capacidades y plazos, y usa la probabilidad de inasistencia para sobreagendar de forma controlada.

Un **simulador** SimPy compara políticas (orden de llegada, solo prioridad, optimizada) a lo largo de semanas, y una **API** FastAPI + **panel** Dash muestran todos los resultados, con flujo de revisión: todo plan nace pendiente; solo un revisor lo aprueba o rechaza; solo un gestor lo marca vigente.

## Demo en unos minutos

Lo primero útil: sigue estos pasos para ver el sistema completo funcionando localmente.

### Requisitos

- **Git**
- **`uv`** (gestor de paquetes Python e instalador de Python): instálalo en macOS/Linux con

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  En Windows, sigue las instrucciones en [astral.sh/uv/install](https://astral.sh/uv/install).

Eso es todo. No necesitas Docker, PostgreSQL ni instalar Python manualmente.

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/TheNewAarons/prioriza.git
cd prioriza

# 2. Ejecutar la demo
make demo
```

O directamente con el script:

```bash
scripts/demo.sh
```

### Qué hace

La demo genera una población sintética, entrena el modelo de inasistencias, programa citas con tres políticas, corre una simulación corta que compara cuatro y levanta la API y el panel. Todo queda en `data/demo/` (ignorado por git). Los pasos:

1. **Sincroniza dependencias** con `uv sync` (instala Python 3.12 si falta y crea `.venv` en el proyecto).
2. **Genera la población sintética** (por defecto 10.000 entradas en lista de espera, ajustable con `--size`).
3. **Entrena el modelo de inasistencias**.
4. **Crea usuarios de demostración** (gestor, revisor y lectura) con claves generadas al azar en `data/demo/users.json`.
5. **Programa citas** para 4 semanas con tres políticas: orden de llegada, solo prioridad y optimizada (con sobrecupo controlado).
6. **Simula** 8 semanas con 2 réplicas y compara cuatro políticas (las tres anteriores y la optimizada sin sobrecupo).
7. **Levanta el panel interactivo** en `http://127.0.0.1:8050` y la API en `http://127.0.0.1:8000`.

Medido en un Mac con Apple Silicon (8 núcleos), con las dependencias ya descargadas: unos 4 minutos en total (población 14 s, modelo 49 s, programación 30 s, simulación 2 min). La primera vez hay que sumar la descarga de dependencias, que depende de la conexión.

### Qué imprime al final

La demo mostrará:

- **URL del panel**: `http://127.0.0.1:8050`
- **URL de la API** (OpenAPI): `http://127.0.0.1:8000/docs`
- **Tres usuarios locales** con su clave (la misma que está en `data/demo/users.json`):
  ```
  gestora.demo (gestor): <clave>     programa planes y los marca como vigentes
  revisor.demo (revisor): <clave>    aprueba o rechaza planes
  lectura.demo (lectura): <clave>    solo consulta
  ```
- Un recorrido sugerido y cómo detenerla.

Las claves son solo para esta demo local: se generan al azar en tu máquina y no sirven en ningún otro lugar.

### Recorrido sugerido

1. Entra con la clave de `gestora.demo` y revisa **Resumen** y **Lista** (elige una fila para ver el desglose del puntaje).
2. En **Programación**, elige una política y pulsa **Programar**; espera a que el trabajo termine.
3. Pulsa **Salir**, entra como `revisor.demo` y, en **Programación**, aprueba el plan.
4. Sal y entra otra vez como `gestora.demo`; pulsa **Marcar como vigente**.
5. Revisa **Simulación** y **Equidad**: los resultados se muestran tal cual, también los desfavorables.

### Opciones útiles

```bash
# Población más chica y rápida (el mínimo es 1.000)
make demo DEMO_ARGS="--size 1000"

# Generar datos nuevos (borra anteriores)
scripts/demo.sh --fresh

# No abrir el navegador automáticamente
scripts/demo.sh --no-open

# Solo generar datos, sin levantar servicios
scripts/demo.sh --no-serve

# Cambiar puertos (API en 9000, panel en 9050)
scripts/demo.sh --api-port 9000 --panel-port 9050

# Ver todas las opciones
scripts/demo.sh --help
```

### Detener la demo

Presiona **Ctrl+C** en la terminal donde corre `make demo`. El script limpiará los procesos automáticamente.

## Principios

- **Sin datos de pacientes reales**: solo datos públicos agregados (datos.gob.cl, reportes del Minsal) y una población sintética calibrada contra ellos. Nunca se agregan nombres, RUT ni datos clínicos reales.

- **El sistema apoya, no decide**: la prioridad clínica es un dato de entrada definido por profesionales; el sistema nunca la infiere ni la sobreescribe. Todo plan generado requiere revisión humana antes de usarse.

- **Equidad**: el modelo de inasistencias no puede usar atributos protegidos (sexo, etnia, nacionalidad) ni proxies evidentes. Se mide y reporta si el sobreagendamiento perjudica sistemáticamente a algún grupo (comuna, grupo etario, previsión).

- **Transparencia de resultados**: nunca se ocultan resultados negativos. Si una política no mejora en alguna métrica o grupo, se reporta tal cual.

## Uso avanzado

### Comandos individuales

Desde la raíz del repo, después de `uv sync`:

```bash
# Descargar datos públicos agregados
make ingest

# Generar población sintética (100.000 entradas, seed 42) y cargarla en PostgreSQL
# (requiere la base de `make up` y `make migrate`; sin base usa
#  `uv run --package synthetic prioriza-synth generate --size 100000`)
make synth

# Entrenar el modelo de inasistencias
make train-noshow

# Programar citas (4 semanas, seed 42, tamaño 100.000)
make schedule

# Benchmark del programador (tamaños 1k, 10k, 50k; horizonte 2 y 4 semanas)
make bench-scheduler

# Simular políticas (26 semanas, 5 réplicas)
make simulate

# Ejecutar tests
make test

# Verificar código (linter + formateo)
make lint

# Type checking (mypy)
make typecheck

# Formatear código
make format
```

Personaliza con variables de entorno:

```bash
# Población de 50.000 en lugar de 100.000 (con PostgreSQL)
make synth SIZE=50000

# Seed distinto
make synth SEED=123

# Semanas de programación
make schedule WEEKS=8

# Argumentos de las CLIs
make schedule SCHEDULE_ARGS="--policy priority --time-limit 60"
make simulate SIM_ARGS="--weeks 4 --replicas 3"
```

### Con Docker Compose (opcional)

Si prefieres PostgreSQL persistente y servicios completos en contenedores:

```bash
# Levanta PostgreSQL, API y panel en contenedores
make up

# Ejecuta migraciones de Alembic
make migrate

# Detiene los servicios
make down
```

Configura usuarios en `api/config/users.json` (copiar `api/users.example.json` y llenar claves; el archivo de ejemplo **no tiene claves válidas**).

Variables de entorno opcionales:

```bash
PRIORIZA_API_USERS_FILE=api/config/users.json  # Ubicación del archivo de usuarios
PRIORIZA_API_RUN_DIR=data/synthetic/<run_id>    # Directorio de la corrida sintética
PRIORIZA_API_MODELS_DIR=models/noshow           # Directorio de modelos
PRIORIZA_API_RESULTS_DIR=results                # Directorio de resultados
```

### Desarrollo

```bash
# Sincronizar todas las dependencias del workspace
make sync

# Instalar hooks de git (pre-commit, pre-push con lint/typecheck/test)
make hooks

# Formatear y revisar el código
make format
make lint
make typecheck

# Ver todos los targets disponibles
make help
```

## Documentación

- **[docs/data-sources.md](docs/data-sources.md)**: fuentes de datos públicos verificadas, cifras y licencias.
- **[docs/synthetic-data.md](docs/synthetic-data.md)**: descripción de la población sintética, calibración, variables y supuestos.
- **[docs/priority.md](docs/priority.md)**: reglas de priorización explícitas, cálculo del puntaje y tiers de garantía GES.
- **[docs/noshow-model-card.md](docs/noshow-model-card.md)**: modelo de inasistencias, datos de entrenamiento, calibración y equidad.
- **[docs/scheduler-formulation.md](docs/scheduler-formulation.md)**: formulación matemática del programador CP-SAT, fases lexicográficas y sobrecupo.
- **[docs/scheduler-performance.md](docs/scheduler-performance.md)**: benchmark del programador, tiempos y comparación con políticas simples.
- **[docs/simulation-design.md](docs/simulation-design.md)**: diseño del simulador SimPy, métricas y limitaciones.
- **[docs/api.md](docs/api.md)**: referencia de endpoints FastAPI, autenticación, roles y ejemplos.
- **[docs/design.md](docs/design.md)**: diseño visual del panel Dash, tokens y estructura de páginas.
- **[docs/decisions.md](docs/decisions.md)**: decisiones arquitectónicas del proyecto, workspace, dependencias y reproducibilidad.
- **[docs/version-control.md](docs/version-control.md)**: estrategia de ramas, commits y versionado de resultados.

## Estructura del monorepo

Workspace `uv` con 9 miembros:

| Módulo | Descripción |
|---|---|
| `shared/` | Configuración, enums, sesiones de BD, utilidades comunes. |
| `ingestion/` | CLI `prioriza-ingest`: descarga datos públicos, parsea PDF, valida. |
| `synthetic/` | CLI `prioriza-synth`: genera población sintética calibrada. |
| `priority/` | Cálculo de prioridad por reglas explícitas. |
| `noshow/` | Modelo de scikit-learn para predicción de inasistencias. |
| `scheduler/` | Asignación con OR-Tools CP-SAT, búsqueda de soluciones óptimas. |
| `simulation/` | Simulador de políticas con SimPy, comparación de estrategias. |
| `api/` | API FastAPI con autenticación, roles y revisión de planes. |
| `dashboard/` | Panel Dash: lista, programación, simulación, equidad. |

## Licencia de datos

Las fuentes de datos públicos se citan en [docs/data-sources.md](docs/data-sources.md). Los PDFs fuente (ej. Glosa 06 del Minsal) **no se redistribuyen** en el repositorio; se usan solo mediante URLs verificadas y SHA256.

Licencias de entrada:
- **Glosas 06 (Minsal)**: no indicada.
- **Estadísticas GES (Superintendencia de Salud)**: no indicada.
- **Catálogo de establecimientos (datos.gob.cl)**: CC0.
- **Literatura**: CC BY-NC 3.0 o similar (ver [docs/data-sources.md](docs/data-sources.md)).

El código y la población sintética generada están sujetos al aviso de investigación con datos sintéticos (ver inicio del README).

---

**Más información**: lee [docs/decisions.md](docs/decisions.md) para la arquitectura completa, o contacta al equipo de desarrollo.
