"""Invariantes de la simulación (P10-T3): conservación, casos con resultado conocido y verdad.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.

Conservación: ninguna entrada aparece ni desaparece sin causa. Se reconstruye el estado de
cada entrada desde el registro de eventos con una máquina de estados explícita y se compara
con los conteos del resumen y con el tamaño semanal de la lista.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest
from simulation.config import POLICIES, SimulationConfig
from simulation.engine import simulate
from simulation.metrics import PolicyResult
from simulation_test_support import AS_OF, fake_prediction, make_world
from synthetic.capacity import horizon_start

START = horizon_start(AS_OF)
CREATE = {"stock", "arrival"}
# (estado de origen, estado de destino) → causa válida.
TRANSITIONS = {
    ("waiting", "booked"): "commit",
    ("booked", "no_show"): "no_show",
    ("no_show", "waiting"): "return_waiting",
    ("no_show", "removed_no_show"): "two_no_shows",
    ("booked", "resolved"): "attended",
    ("waiting", "abandoned"): "abandon",
}
TERMINAL = {"resolved", "removed_no_show", "abandoned"}


def _replay(result: PolicyResult, max_no_shows: int) -> dict[str, str]:
    """Estado final de cada entrada según los eventos; falla ante cualquier salto sin causa."""
    state: dict[str, str] = {}
    no_shows: Counter[str] = Counter()
    last_day: dict[str, int] = {}
    for day, eid, frm, to, cause in result.events:
        if frm == "":
            assert eid not in state, f"{eid} creada dos veces"
            assert to == "waiting" and cause in CREATE, (eid, to, cause)
        else:
            assert state.get(eid) == frm, f"{eid}: evento desde {frm}, estado {state.get(eid)}"
            assert TRANSITIONS.get((frm, to)) == cause, (eid, frm, to, cause)
            assert day >= last_day[eid], f"{eid}: evento hacia atrás en el tiempo"
        if cause == "no_show":
            no_shows[eid] += 1
            assert no_shows[eid] <= max_no_shows
        if cause == "two_no_shows":
            assert no_shows[eid] == max_no_shows
        state[eid] = to
        last_day[eid] = day
    assert "no_show" not in state.values(), "inasistencia sin destino"
    return state


def _check_conservation(result: PolicyResult, config: SimulationConfig) -> None:
    state = _replay(result, config.max_no_shows)
    created = Counter(c for _, _, _, _, c in result.events if c in CREATE)
    final = Counter(state.values())
    s = result.summary
    # stock inicial + llegadas = en lista + atendidas + salidas por inasistencia + abandonos
    assert created["stock"] + created["arrival"] == len(state)
    assert created["arrival"] == s["arrivals_total"]
    assert final["waiting"] == s["waiting_final"]
    assert final["booked"] == s["booked_final"]
    assert final["resolved"] == s["resolved_total"] == s["exits"]["attended"]
    assert final["removed_no_show"] == s["removed_no_show_total"] == s["exits"]["two_no_shows"]
    assert final["abandoned"] == s["abandoned_total"] == s["exits"]["abandoned"]
    assert s["list_size_final"] == final["waiting"] + final["booked"]
    # Tamaño de la lista cada lunes 7k, tras planificar: creadas antes de ese día, menos las
    # salidas antes de ese día y los abandonos de ese lunes (las citas del lunes se resuelven
    # a las 7k + 0,5 y las llegadas a las 7k + 0,25, después de planificar).
    for row in result.weekly:
        d = 7 * row["week"]
        alive = sum(1 for day, _, frm, _, c in result.events if frm == "" and day < d)
        alive += created["stock"] * (d == 0)
        gone = sum(
            1
            for day, _, _, to, c in result.events
            if to in TERMINAL and (day < d or (day == d and c == "abandon"))
        )
        assert row["list_size"] == alive - gone, row
        assert row["list_size"] == row["waiting"] + row["booked"]


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("seed", [101, 102])
@pytest.mark.parametrize("abandon", [0.0, 0.05])
def test_conservation(
    monkeypatch: pytest.MonkeyPatch, policy: str, seed: int, abandon: float
) -> None:
    """Lista con llegadas, inasistencia de 50 %, GES y sobrecupo: nada se crea ni se pierde."""
    fake_prediction(monkeypatch, 0.5)
    world = make_world(
        n_stock=30, sessions_per_week=1.5, arrivals_per_week=8.0, intercept=0.0, ges_every=4
    )
    config = SimulationConfig(weeks=6, abandon_weekly_rate=abandon, replica_seeds=(seed,))
    result = simulate(world, policy, config, seed)
    _check_conservation(result, config)
    assert result.summary["arrivals_total"] > 0
    assert result.summary["resolved_total"] > 0
    assert result.summary["exits"]["two_no_shows"] + result.summary["waiting_final"] > 0


def test_conservation_in_surgery() -> None:
    """Pabellón (minutos en vez de unidades, sin sobrecupo): mismas cuentas."""
    world = make_world(n_stock=12, sessions_per_week=1.0, arrivals_per_week=3.0, surgery=True)
    config = SimulationConfig(weeks=5)
    for policy in POLICIES:
        _check_conservation(simulate(world, policy, config, 101), config)


def test_everyone_attends_in_the_first_committed_week(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 entradas, 12 cupos por semana, nadie falta, sin llegadas: todas se atienden el lunes
    de la semana 1 (sesión de la tarde, día 7) y la lista queda vacía. Ese lunes la lista aún
    las cuenta: la planificación (7,0) va antes que la sesión (7,5).
    """
    fake_prediction(monkeypatch, 0.2)
    world = make_world(n_stock=5, intercept=-40.0)
    config = SimulationConfig(weeks=3)
    for policy in POLICIES:
        r = simulate(world, policy, config, 101)
        _check_conservation(r, config)
        assert [w["list_size"] for w in r.weekly] == [5, 5, 0], policy
        attended = [(day, eid) for day, eid, _, _, c in r.events if c == "attended"]
        assert sorted(attended) == [(7, f"e{k:03d}") for k in range(5)]
        # Espera = (lunes de la semana 1) - (AS_OF - 200 - k) días.
        waits = sorted((START + timedelta(days=7) - AS_OF).days + 200 + k for k in range(5))
        assert r.summary["wait_attended"]["median"] == waits[2]
        assert r.summary["slot_use"]["cne_utilization"] == pytest.approx(5 / 36)
        assert r.summary["lost_slots"]["cne_units"] == 0
        assert r.summary["no_show"]["rate_cne"] == 0.0


def test_everyone_misses_twice_and_leaves() -> None:
    """Todos faltan: cita el lunes de la semana 1 (día 7), vuelven a la lista, cita en la
    semana 3 (la de la semana 2 se planificó el día 7,0, antes de la falta; la sesión de la
    semana 3 es el martes en la tarde, día 22), segunda falta y egreso por dos inasistencias.
    """
    world = make_world(n_stock=5, intercept=40.0)
    config = SimulationConfig(weeks=5)
    for policy in ("fifo", "priority", "optimized"):
        r = simulate(world, policy, config, 101)
        _check_conservation(r, config)
        assert [w["list_size"] for w in r.weekly] == [5, 5, 5, 5, 0], policy
        assert [w["booked"] for w in r.weekly] == [5, 5, 5, 5, 0]
        assert r.summary["removed_no_show_total"] == 5
        assert r.summary["resolved_total"] == 0
        assert r.summary["lost_slots"]["cne_units"] == 10  # 5 faltas en cada una de 2 sesiones
        assert r.summary["slot_use"]["cne_utilization"] == 0.0
        no_show_days = Counter(day for day, _, _, _, c in r.events if c == "no_show")
        assert no_show_days == {7: 5, 22: 5}


def test_fifo_serves_the_oldest_first() -> None:
    """20 entradas y 12 cupos por semana, nadie falta: fifo atiende primero las 12 más antiguas
    (e008-e019) y la semana siguiente las 8 restantes.
    """
    world = make_world(n_stock=20, intercept=-40.0)
    r = simulate(world, "fifo", SimulationConfig(weeks=3), 101)
    weeks: dict[int, set[str]] = {}
    for day, eid, _, _, c in r.events:
        if c == "attended":
            weeks.setdefault(day // 7, set()).add(eid)
    assert weeks[1] == {f"e{k:03d}" for k in range(8, 20)}
    assert weeks[2] == {f"e{k:03d}" for k in range(8)}


def test_attendance_uses_true_probability_not_predicted(monkeypatch: pytest.MonkeyPatch) -> None:
    """El programador cree que falta el 60 % y sobreagenda; en el mundo nadie falta.

    Si la asistencia se sorteara con la p predicha habría inasistencias; con la verdadera no hay
    ninguna y los sobrecupos se convierten en desborde.
    """
    fake_prediction(monkeypatch, 0.6)
    # 80 entradas no caben en 4 semanas de 12 cupos: hay razón para sobreagendar.
    world = make_world(n_stock=80, intercept=-40.0)
    r = simulate(world, "optimized_overbooking", SimulationConfig(weeks=3), 101)
    s = r.summary
    assert s["no_show"]["predicted_mean_cne"] == pytest.approx(0.6)
    assert s["no_show"]["realized_rate_cne_with_prediction"] == 0.0
    assert s["no_show"]["rate_cne"] == 0.0
    assert s["overflow"]["sessions"] > 0 and s["overflow"]["units"] > 0


def test_predicted_probability_never_reaches_attendance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Al revés: el programador cree que nadie falta y en el mundo faltan todos."""
    fake_prediction(monkeypatch, 0.01)
    world = make_world(n_stock=10, intercept=40.0)
    r = simulate(world, "optimized_overbooking", SimulationConfig(weeks=3), 101)
    assert r.summary["no_show"]["rate_cne"] == 1.0
    assert r.summary["resolved_total"] == 0


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_only_truth_module_imports_the_generator_truth() -> None:
    """``truth.py`` es el único que importa la verdad; las políticas no ven ``truth``."""
    pkg = Path(__file__).parents[1] / "src" / "simulation"
    for path in sorted(pkg.glob("*.py")):
        mods = _imports(path)
        if path.name != "truth.py":
            assert not any(m.startswith("synthetic.noshow_truth") for m in mods), path.name
    policies = _imports(pkg / "policies.py")
    assert not any("truth" in m for m in policies)
    assert "simulation.truth" in _imports(pkg / "engine.py")
