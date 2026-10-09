#!/usr/bin/env bash
#
# Herramienta de investigación con datos sintéticos.
# No usar para decisiones clínicas ni de gestión real sin validación institucional.
#
# Demo de punta a punta de Prioriza: genera población, entrena modelo,
# programa citas y simula, luego levanta API y panel.

set -euo pipefail

# Valores por defecto
DEMO_SIZE=${DEMO_SIZE:-10000}
DEMO_SEED=${DEMO_SEED:-42}
DEMO_DIR=${DEMO_DIR:-data/demo}
DEMO_API_PORT=${DEMO_API_PORT:-8000}
DEMO_PANEL_PORT=${DEMO_PANEL_PORT:-8050}
DEMO_SIM_WEEKS=${DEMO_SIM_WEEKS:-8}
DEMO_SIM_REPLICAS=${DEMO_SIM_REPLICAS:-2}
DEMO_FRESH=${DEMO_FRESH:-0}
DEMO_NO_SYNC=${DEMO_NO_SYNC:-0}
DEMO_NO_SERVE=${DEMO_NO_SERVE:-0}
DEMO_NO_OPEN=${DEMO_NO_OPEN:-0}

# PID de los procesos lanzados
API_PID=""
PANEL_PID=""

# Función de ayuda
usage() {
	cat <<'HELPEOF'
Uso: scripts/demo.sh [opciones]

Demo de punta a punta de Prioriza.

Opciones:
  --size N            Numero de entradas (>= 1.000, por defecto 10000)
  --seed N            Semilla fija (por defecto 42)
  --dir DIR           Directorio de trabajo (por defecto data/demo)
  --api-port P        Puerto de la API (por defecto 8000)
  --panel-port P      Puerto del panel (por defecto 8050)
  --sim-weeks N       Semanas de simulacion (por defecto 8)
  --sim-replicas N    Replicas de simulacion (por defecto 2)
  --fresh             Borra DIR antes de empezar
  --no-sync           No corre uv sync
  --no-serve          Termina tras generar resultados
  --no-open           No abre el navegador
  -h, --help          Muestra esta ayuda
HELPEOF
	exit 0
}

# Parsear argumentos
while [[ $# -gt 0 ]]; do
	case "$1" in
		--size)
			DEMO_SIZE="$2"
			shift 2
			;;
		--seed)
			DEMO_SEED="$2"
			shift 2
			;;
		--dir)
			DEMO_DIR="$2"
			shift 2
			;;
		--api-port)
			DEMO_API_PORT="$2"
			shift 2
			;;
		--panel-port)
			DEMO_PANEL_PORT="$2"
			shift 2
			;;
		--sim-weeks)
			DEMO_SIM_WEEKS="$2"
			shift 2
			;;
		--sim-replicas)
			DEMO_SIM_REPLICAS="$2"
			shift 2
			;;
		--fresh)
			DEMO_FRESH=1
			shift
			;;
		--no-sync)
			DEMO_NO_SYNC=1
			shift
			;;
		--no-serve)
			DEMO_NO_SERVE=1
			shift
			;;
		--no-open)
			DEMO_NO_OPEN=1
			shift
			;;
		-h | --help)
			usage
			;;
		*)
			echo "Error: opción desconocida: $1" >&2
			usage
			;;
	esac
done

# Verificar tamaño mínimo
if [[ ${DEMO_SIZE} -lt 1000 ]]; then
	echo "Error: el tamaño mínimo es 1000" >&2
	exit 1
fi

# Verificar que uv esté disponible
if ! command -v uv &>/dev/null; then
	cat <<'UVEOF'
Error: 'uv' no esta instalado.

Instalalo desde: https://docs.astral.sh/uv/getting-started/installation/
UVEOF
	exit 1
fi

# Cambiar a la raíz del repo
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Función para limpiar recursos al salir
cleanup() {
	local exit_code=$?
	if [[ -n "$API_PID" ]]; then
		echo "Deteniendo API (PID $API_PID)..."
		kill "$API_PID" 2>/dev/null || true
		wait "$API_PID" 2>/dev/null || true
	fi
	if [[ -n "$PANEL_PID" ]]; then
		echo "Deteniendo panel (PID $PANEL_PID)..."
		kill "$PANEL_PID" 2>/dev/null || true
		wait "$PANEL_PID" 2>/dev/null || true
	fi
	exit "$exit_code"
}

trap cleanup INT TERM EXIT

# Crear directorio de trabajo y logs
mkdir -p "$DEMO_DIR/logs"

# Paso 0: Borrar si es necesario
if [[ $DEMO_FRESH -eq 1 ]]; then
	echo "Borrando $DEMO_DIR..."
	rm -rf "$DEMO_DIR"
	mkdir -p "$DEMO_DIR/logs"
fi

# Total de pasos (5 o 7 según --no-serve)
TOTAL_STEPS=7
if [[ $DEMO_NO_SERVE -eq 1 ]]; then
	TOTAL_STEPS=6
fi
if [[ $DEMO_NO_SYNC -eq 1 ]]; then
	TOTAL_STEPS=$((TOTAL_STEPS - 1))
fi

STEP=0

# Paso 1: uv sync (opcional)
if [[ $DEMO_NO_SYNC -eq 0 ]]; then
	STEP=$((STEP + 1))
	echo ""
	echo "[$STEP/$TOTAL_STEPS] Sincronizando dependencias..."
	start_time=$(date +%s)

	if uv sync --all-packages >"$DEMO_DIR/logs/step_01_sync.log" 2>&1; then
		end_time=$(date +%s)
		elapsed=$((end_time - start_time))
		echo "listo en $elapsed s"
	else
		echo "error (código $?)"
		tail -30 "$DEMO_DIR/logs/step_01_sync.log"
		exit 1
	fi
fi

# Paso 2: Generar población
STEP=$((STEP + 1))
echo ""
echo "[$STEP/$TOTAL_STEPS] Generando la población sintética..."
start_time=$(date +%s)

uv run --package synthetic prioriza-synth generate \
	--size "$DEMO_SIZE" \
	--seed "$DEMO_SEED" \
	--out "$DEMO_DIR/synthetic" \
	--report-dir "$DEMO_DIR/results" \
	>"$DEMO_DIR/logs/step_02_synth.log" 2>&1 && SYNTH_CODE=0 || SYNTH_CODE=$?

# Corridas con manifest.json y el tamaño pedido. El generador sale con código 1 si algún
# chequeo estricto de calibración falla (pasa en tamaños chicos) pero igual escribe la corrida.
RUNS=$(uv run python - "$DEMO_DIR/synthetic" "$DEMO_SIZE" <<'PYEOF'
import json
import sys
from pathlib import Path

root, size = Path(sys.argv[1]), int(sys.argv[2])
for manifest in sorted(root.glob("*/manifest.json")) if root.exists() else []:
    if json.loads(manifest.read_text(encoding="utf-8"))["run"]["size"] == size:
        print(manifest.parent)
PYEOF
)
RUN_COUNT=$(printf '%s' "$RUNS" | grep -c . || true)
if [[ $RUN_COUNT -eq 0 ]]; then
	echo "error: el generador no escribió la corrida (código $SYNTH_CODE)"
	tail -30 "$DEMO_DIR/logs/step_02_synth.log"
	exit 1
fi
if [[ $RUN_COUNT -gt 1 ]]; then
	echo "error: hay $RUN_COUNT corridas de tamaño $DEMO_SIZE en $DEMO_DIR/synthetic; usa --fresh" >&2
	exit 1
fi
RUN_DIR=$RUNS
if [[ $SYNTH_CODE -ne 0 ]]; then
	echo "aviso: la corrida no pasa algún chequeo estricto de calibración (esperable con"
	echo "       --size chico; detalle en $DEMO_DIR/logs/step_02_synth.log). Se sigue igual."
fi

end_time=$(date +%s)
elapsed=$((end_time - start_time))
echo "listo en $elapsed s"

# Paso 3: Entrenar modelo
STEP=$((STEP + 1))
echo ""
echo "[$STEP/$TOTAL_STEPS] Entrenando modelo de inasistencias..."
start_time=$(date +%s)

if uv run --package noshow prioriza-noshow train \
	--run-dir "$RUN_DIR" \
	--models-dir "$DEMO_DIR/models" \
	--results "$DEMO_DIR/results/noshow.json" \
	--seed "$DEMO_SEED" \
	>"$DEMO_DIR/logs/step_03_noshow.log" 2>&1; then
	end_time=$(date +%s)
	elapsed=$((end_time - start_time))
	echo "listo en $elapsed s"
else
	echo "error (código $?)"
	tail -30 "$DEMO_DIR/logs/step_03_noshow.log"
	exit 1
fi

# Paso 4: Crear archivo de usuarios
STEP=$((STEP + 1))
echo ""
echo "[$STEP/$TOTAL_STEPS] Configurando usuarios..."
start_time=$(date +%s)

USERS_FILE="$DEMO_DIR/users.json"
if [[ ! -f "$USERS_FILE" ]]; then
	uv run python - "$USERS_FILE" <<'PYEOF'
import json
import secrets
import sys

api_keys = []
for _ in range(3):
    api_keys.append(secrets.token_urlsafe(32))

users = {
    api_keys[0]: {"user": "gestora.demo", "role": "gestor"},
    api_keys[1]: {"user": "revisor.demo", "role": "revisor"},
    api_keys[2]: {"user": "lectura.demo", "role": "lectura"}
}

with open(sys.argv[1], 'w') as f:
    json.dump(users, f, indent=2)
PYEOF
	chmod 600 "$USERS_FILE"
fi

end_time=$(date +%s)
elapsed=$((end_time - start_time))
echo "listo en $elapsed s"

# Paso 5: Programar (todas las políticas)
STEP=$((STEP + 1))
echo ""
echo "[$STEP/$TOTAL_STEPS] Programando citas..."
start_time=$(date +%s)

if uv run --package scheduler prioriza-schedule \
	--run-dir "$RUN_DIR" \
	--models-dir "$DEMO_DIR/models" \
	--results-dir "$DEMO_DIR/results" \
	--out-dir "$DEMO_DIR/schedules" \
	--weeks 4 \
	--time-limit 30 \
	--workers 1 \
	--seed "$DEMO_SEED" \
	>"$DEMO_DIR/logs/step_05_schedule.log" 2>&1; then
	end_time=$(date +%s)
	elapsed=$((end_time - start_time))
	echo "listo en $elapsed s"
else
	echo "error (código $?)"
	tail -30 "$DEMO_DIR/logs/step_05_schedule.log"
	exit 1
fi

# Paso 6: Simular
STEP=$((STEP + 1))
echo ""
echo "[$STEP/$TOTAL_STEPS] Simulando políticas..."
start_time=$(date +%s)

if uv run --package simulation prioriza-simulate \
	--size "$DEMO_SIZE" \
	--seed "$DEMO_SEED" \
	--weeks "$DEMO_SIM_WEEKS" \
	--replicas "$DEMO_SIM_REPLICAS" \
	--work-dir "$DEMO_DIR/simulation" \
	--out "$DEMO_DIR/results/simulation.json" \
	>"$DEMO_DIR/logs/step_06_simulate.log" 2>&1; then
	end_time=$(date +%s)
	elapsed=$((end_time - start_time))
	echo "listo en $elapsed s"
else
	echo "error (código $?)"
	tail -30 "$DEMO_DIR/logs/step_06_simulate.log"
	exit 1
fi

# Si --no-serve, terminar aquí
if [[ $DEMO_NO_SERVE -eq 1 ]]; then
	echo ""
	echo "Demostración completada."
	echo "Resultados en: $DEMO_DIR"
	exit 0
fi

# Paso 7: Servicio
STEP=$((STEP + 1))
echo ""
echo "[$STEP/$TOTAL_STEPS] Levantando la API y el panel..."
start_time=$(date +%s)

# Verificar que los puertos estén disponibles
for PORT in "$DEMO_API_PORT" "$DEMO_PANEL_PORT"; do
	if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
		echo "error: el puerto $PORT ya está en uso (¿otra demo o la API corriendo?)."
		echo "Detén ese proceso o usa --api-port / --panel-port con otros puertos."
		exit 1
	fi
done

# Exportar variables para la API
export PRIORIZA_API_USERS_FILE="$USERS_FILE"
export PRIORIZA_API_RUN_DIR="$RUN_DIR"
export PRIORIZA_API_MODELS_DIR="$DEMO_DIR/models"
export PRIORIZA_API_RESULTS_DIR="$DEMO_DIR/results"
export PRIORIZA_API_DATA_DIR="$DEMO_DIR/synthetic"
export PRIORIZA_DASHBOARD_API_URL="http://127.0.0.1:$DEMO_API_PORT"

# Lanzar servicio en segundo plano
uv run --package dashboard prioriza-dashboard \
	--with-api \
	--port "$DEMO_PANEL_PORT" \
	--api-url "http://127.0.0.1:$DEMO_API_PORT" \
	>"$DEMO_DIR/logs/step_07_service.log" 2>&1 &
PANEL_PID=$!

# Esperar a que ambos endpoints respondan
HEALTHZ_URL="http://127.0.0.1:$DEMO_API_PORT/healthz"
PANEL_URL="http://127.0.0.1:$DEMO_PANEL_PORT/"
TIMEOUT=120
ELAPSED=0
STEP_START=$(date +%s)

while [[ $ELAPSED -lt $TIMEOUT ]]; do
	if curl -sf "$HEALTHZ_URL" >/dev/null 2>&1 && curl -sf "$PANEL_URL" >/dev/null 2>&1; then
		break
	fi
	if ! kill -0 "$PANEL_PID" 2>/dev/null; then
		echo "error: el panel terminó antes de responder"
		tail -30 "$DEMO_DIR/logs/step_07_service.log"
		exit 1
	fi
	sleep 2
	ELAPSED=$(($(date +%s) - STEP_START))
done

if [[ $ELAPSED -ge $TIMEOUT ]]; then
	echo "error: timeout esperando el servicio"
	echo "Últimas líneas de $DEMO_DIR/logs/step_07_service.log:"
	tail -30 "$DEMO_DIR/logs/step_07_service.log"
	exit 1
fi

end_time=$(date +%s)
elapsed=$((end_time - start_time))
echo "listo en $elapsed s"

# Mostrar credenciales y recorrido
echo ""
echo "Demostración completada."
echo ""
echo "URL del panel: $PANEL_URL"
echo "API docs: http://127.0.0.1:$DEMO_API_PORT/docs"
echo ""
echo "Credenciales (lee el archivo $USERS_FILE para ver las claves):"

uv run python - "$USERS_FILE" <<'PYEOF'
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

for key, value in data.items():
    print(f"  {value['user']} ({value['role']}): {key}")
PYEOF

echo ""
echo "Recorrido sugerido:"
echo "  1. Entra con la clave de gestora.demo y revisa Resumen y Lista (elige una fila para ver"
echo "     el desglose del puntaje)."
echo "  2. En Programación, elige una política y pulsa Programar; espera a que termine."
echo "  3. Sal, entra como revisor.demo y, en Programación, aprueba el plan."
echo "  4. Sal, entra como gestora.demo y pulsa Marcar como vigente."
echo "  5. Revisa Simulación y Equidad (resultados tal cual, también los desfavorables)."
echo ""
echo "Para detener: Ctrl+C"
echo ""

# Abrir navegador (opcional)
if [[ $DEMO_NO_OPEN -eq 0 ]]; then
	if [[ "$OSTYPE" == "darwin"* ]]; then
		open "$PANEL_URL" || true
	elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
		xdg-open "$PANEL_URL" || true
	fi
fi

# Esperar a que la sesión termine (trap se encargará de limpiar)
echo "Esperando... (Ctrl+C para detener)"
wait "$PANEL_PID"
