# Backlog

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Pendientes de baja prioridad de la revisión P17 ([`review.md`](review.md)) y pendientes de P18. Los dos hallazgos medios que seguían abiertos (M3 y M4) se resolvieron en P18 (sección "Resueltos en P18"). Las referencias de línea de los bajos son las del commit de la revisión.

## Resueltos en P18

- **M3 (revisión P17): R4 con citas congeladas.** `SchedulingInstance.busy_patient_days` (tabla opcional `busy`) descarta en `prepare` los pares de un paciente en un día en que ya tiene cita, con la causa `patient_day_busy` y verificación en el ensamblador; ver `docs/decisions.md` ("Citas previas en R4 (M-03)") y `docs/scheduler-formulation.md` §4 y §15 (punto 9).
- **M4 (revisión P17): fase 4 con agendados fijos.** La fase 4 fija `a_i = 1` en `S3` y `a_i = 0` fuera (`Fixings.assigned_exact`), y el ensamblador verifica agendados finales = `S3` y `phase_added = "3b"` solo si la 3b corrió; ver `docs/decisions.md` ("Fase 4 con agendados fijos (M-04)") y `docs/scheduler-formulation.md` §8.1.
- **Presupuesto de tiempo global del programador.** `time_limit_s` es el presupuesto del plan completo, en tiempo determinista, repartido entre primera pasada y expansión de frontera (`docs/scheduler-formulation.md` §8.5). En el plan canónico gasta 103,0 de 120 unidades; el presupuesto se agotó (53 fases terminaron por el límite), resultado que se informa tal cual (§11.3).

## Pendientes de P18

- **Barrido del presupuesto `B` = 60, 120 y 240: sin ejecutar.** Todo el benchmark y el plan canónico usan `B` = 120; no se conoce cuánto cambia el plan de 50.000 × 4 (el único con presupuesto agotado en el benchmark) ni el plan canónico con otro presupuesto.
- **Cobertura de la oferta de la simulación (generador 0.3.0).** Con 10.000 entradas, 58,3 % de las celdas CNE reciben alguna sesión (91,8 % del stock) y en pabellón 65,1 % (88,8 % del stock). En pabellón hay un leve retroceso frente a la oferta 0.2.0 (89,7 % a 88,8 % del stock cubierto), y la cobertura de celdas CNE queda por debajo de la meta que se había fijado en P18; ver `docs/decisions.md` ("Calentamiento") y `docs/results.md`.

## Bajos: programador

- **R15 usa `floor`, la formulación dice `round`** (`cpsat.py:33-35`, `cpsat.py:672`). El código es más conservador (garantiza `share ≤ ρ`). Corregir el texto de `docs/scheduler-formulation.md` §6.5.
- **`overbooking_fill` cuenta como expuesta a una entrada nueva en un bloque aún sin sobrecupo** (`cpsat.py:454-459`). Solo debilita la pista; no viola restricciones. Sumar a `e[q]` solo si `o ≥ 1`.
- **La fase 3b no exige puntaje `≥ Z0`** (`phases.py:286`). Solo importa con `objective_cut` y `hints` apagados (benchmark): una 3b `FEASIBLE` podría dar `Z3 < Z0`. Agregar `coef_min = Z0` a `fix3b`.
- **El respaldo por semana de las GES no filtra `later` con `free(p)`** (`phases.py:446-452`). No se activa en la corrida canónica. Filtrar `later`.

## Bajos: informe (`reports/`)

- **Fila del oráculo con "sin dato" fijo** (`results.md.j2:129`), aunque el JSON trae `mean_predicted` y `observed_rate`. Usar los valores.
- **IC mostrado como "0,0 a +4,8"** en "Salidas por dos inasistencias" (`results.md:536`): el límite inferior real es -0,020, así que parece que el intervalo no cruza el cero. Mostrar el signo o usar 2 decimales.
- **`no_show_rate_*` etiquetada "mejora" cuando baja** (`results.md:433,512`). En la política sin sobrecupo refleja qué pacientes se seleccionan, no un logro operativo. Declarar la dirección como `None` (solo contexto) en `report.DIRECTION` y `facts`.
- **Ablación sin lectura en la prosa** (`results.md:341-352`): en la celda de 50.000 entradas y 4 semanas, 3 variantes (sin pistas, sin arranque en caliente, sin ruptura de simetría) superan en puntaje a la configuración completa, con 1 sola repetición. Agregar una frase fija que lo diga.

## Bajos: API, panel y operación

- **`ErrorOut` no lleva el aviso** (`api/src/api/schemas.py:36`). Las respuestas con datos sí; los errores no. Valorar si agregarlo.
- **Cobertura baja** en `dashboard/views/programacion.py` (65 %), `dashboard/cli.py` (49 %), `simulation/world.py` (59 %), y en las migraciones 0002, 0003 y 0005 (57-58 %). Los tests `db` (almacén SQL de planes, carga sintética) se omiten sin PostgreSQL: con el CI desactivado nadie los corre por defecto.
- **CI desactivado** (decisión del 2026-10-09). Los chequeos dependen del hook `pre-push` y de la disciplina de correr `make lint typecheck test audit`.
- **Pendientes anteriores a P17**: límites de equidad de P6 sin formalizar, `dash-bootstrap-components` declarada y sin uso, y la fase P11 que nunca se hizo.
