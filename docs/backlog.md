# Backlog

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Pendientes de baja prioridad y hallazgos medios abiertos de la revisión P17 ([`review.md`](review.md)). Ninguno cambia las conclusiones publicadas; los de la sección "Medios abiertos" tienen un riesgo latente o de coherencia con la formulación y conviene resolverlos antes de ampliar el alcance. Las referencias de línea son las del commit de la revisión.

## Medios abiertos (requieren al especialista del programador)

| Id | Dónde | Qué pasa | Por qué sigue abierto |
|---|---|---|---|
| M3 | `scheduler/src/scheduler/cpsat.py:586`, `plan.py:111-119` | La regla R4 (un cupo por paciente y día) no considera citas ya congeladas (`prebooked_*`). Con `commit_weeks ≥ 2` en la simulación, o con citas `scheduled` previas en `make schedule`, un paciente puede quedar con dos citas el mismo día y la verificación del plan no lo detecta. | Es latente: con `commit_weeks = 1` (valor por defecto, usado en todos los resultados publicados) no hay citas congeladas. El arreglo agrega pares `(patient_id, fecha local)` ocupados a `SchedulingInstance`, los filtra en `prepare` y los verifica en `_Assembler`; cambia la API de la instancia y exige regenerar resultados. |
| M4 | `scheduler/src/scheduler/phases.py:310-319` | La fase 4 (equilibrio) no fija el conjunto de pacientes agendados, aunque la formulación §8.1 dice que solo puede mover bloques. Con la 3a en `FEASIBLE` o con cupo libre, podría agregar pacientes, que quedarían etiquetados `phase_added = "3b"` sin que la 3b haya corrido (`plan.py:270`) y desactivarían la comprobación de §9.4 (`plan.py:178`). | El plan sigue cumpliendo todas las restricciones duras; es una incoherencia con la formulación y de etiquetado. Arreglar (fijar `a_i` de los agendados en la fase 4) cambia el plan canónico, y regenerarlo toma unos 160 s más la simulación. |

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
- **Pendientes anteriores a P17**: presupuesto de tiempo global del programador (el plan canónico tarda 163,5 s frente a un objetivo de 120 s), límites de equidad de P6 sin formalizar, `dash-bootstrap-components` declarada y sin uso, y la fase P11 que nunca se hizo.
