"""Pruebas de ``load_facts``: estructura, errores claros y resultados negativos visibles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from reports.facts import FactsError, load_facts

RUN_ID = "11111111-2222-3333-4444-555555555555"  # el mismo de conftest.py

TOP_LEVEL = {
    "disclaimer",
    "labels",
    "provenance",
    "context",
    "calibration",
    "priority",
    "noshow",
    "scheduler",
    "benchmark",
    "simulation",
    "equity",
    "limitations",
    "method",
}


def _edit(path: Path, edit: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_claves_de_primer_nivel(minimal_results: Path, tmp_path: Path) -> None:
    facts = load_facts(minimal_results, tmp_path)
    assert set(facts) == TOP_LEVEL
    assert facts["scheduler"]["run"]["id"] == RUN_ID
    assert facts["provenance"]["results_commit"] is None  # tmp_path no es un repositorio git


def test_calibracion_conserva_los_chequeos_que_fallan(
    minimal_results: Path, tmp_path: Path
) -> None:
    cal = load_facts(minimal_results, tmp_path)["calibration"]
    assert [c["name"] for c in cal["failed"]] == ["C5.x"]
    assert cal["notes"] == ["Una nota de calibración"]  # el aviso se muestra aparte
    assert cal["size"] == 210
    assert cal["seed"] == 42


def test_simulacion_distingue_tamano_canonico(minimal_results: Path, tmp_path: Path) -> None:
    sim = load_facts(minimal_results, tmp_path)["simulation"]
    assert sim["run"]["size"] == 100
    assert sim["canonical_size"] == 210
    assert sim["is_canonical_size"] is False
    assert sim["n_replicas"] == 2


def test_comparaciones_incluyen_las_desfavorables(minimal_results: Path, tmp_path: Path) -> None:
    sim = load_facts(minimal_results, tmp_path)["simulation"]
    names = [c["name"] for c in sim["comparisons"]]
    assert "fifo_vs_priority" not in names  # es el espejo de priority_vs_fifo
    readings = {r["reading"] for c in sim["comparisons"] for r in c["rows"]}
    assert {"better", "worse", "unclear"} <= readings
    for comp in sim["comparisons"]:
        assert comp["n_better"] + comp["n_worse"] + comp["n_unclear"] <= len(comp["rows"])
        assert len(comp["rows"]) == len(sim["metrics"])


def test_equidad_nombra_el_grupo_mas_expuesto(minimal_results: Path, tmp_path: Path) -> None:
    equity = load_facts(minimal_results, tmp_path)["equity"]
    by_dim = {d["dimension"]: d for d in equity["scheduler"]["dimensions"]}
    assert by_dim["age_group"]["most_exposed"]["value"] == "65_plus"
    sim_dims = {d["dimension"]: d for d in equity["simulation"]}
    assert sim_dims["insurance"]["most_exposed"]["value"] == "other"
    assert sim_dims["insurance"]["gaps"]["fifo"]["overbooking_exposure"]["group"] is not None


def test_benchmark_calcula_mediana_y_conserva_estados(
    minimal_results: Path, tmp_path: Path
) -> None:
    bench = load_facts(minimal_results, tmp_path)["benchmark"]
    cell = bench["cells"][0]
    assert cell["wall_time_s_median"] == pytest.approx(0.2)
    assert cell["repeats"] == 3
    assert {v["variant"]: v["status"] for v in cell["variants"]} == {
        "all": "OPTIMAL",
        "none": "FEASIBLE",
    }


@pytest.mark.parametrize(
    "name",
    [
        "noshow.json",
        "scheduler-benchmark.json",
        "simulation.json",
        f"schedule_{RUN_ID}_4w.json",
        "synthetic_calibration_baseline_seed42_n210.json",
    ],
)
def test_falta_un_archivo(minimal_results: Path, tmp_path: Path, name: str) -> None:
    (minimal_results / name).unlink()
    with pytest.raises(FactsError, match=r"falta|ningún|corresponde"):
        load_facts(minimal_results, tmp_path)


def test_el_mensaje_nombra_el_archivo_faltante(minimal_results: Path, tmp_path: Path) -> None:
    (minimal_results / "noshow.json").unlink()
    with pytest.raises(FactsError, match=r"noshow\.json"):
        load_facts(minimal_results, tmp_path)


@pytest.mark.parametrize(
    ("name", "field", "edit"),
    [
        ("noshow.json", "selection.primary", lambda d: d["selection"].pop("primary")),
        ("simulation.json", "config.policies", lambda d: d["config"].pop("policies")),
        ("scheduler-benchmark.json", "generated_at", lambda d: d.pop("generated_at")),
        (
            "synthetic_calibration_baseline_seed42_n210.json",
            "summary",
            lambda d: d.pop("summary"),
        ),
        (
            f"schedule_{RUN_ID}_4w.json",
            "policies.optimized.solver.status",
            lambda d: d["policies"]["optimized"]["solver"].pop("status"),
        ),
    ],
)
def test_falta_un_campo(
    minimal_results: Path, tmp_path: Path, name: str, field: str, edit: Any
) -> None:
    _edit(minimal_results / name, edit)
    with pytest.raises(FactsError) as info:
        load_facts(minimal_results, tmp_path)
    message = str(info.value)
    assert name in message
    assert field in message


def test_campo_con_tipo_incorrecto(minimal_results: Path, tmp_path: Path) -> None:
    _edit(minimal_results / "noshow.json", lambda d: d["config"].update(seed="cuarenta y dos"))
    with pytest.raises(FactsError, match=r"config\.seed"):
        load_facts(minimal_results, tmp_path)


def test_json_invalido(minimal_results: Path, tmp_path: Path) -> None:
    (minimal_results / "noshow.json").write_text("{no es json", encoding="utf-8")
    with pytest.raises(FactsError, match="JSON inválido"):
        load_facts(minimal_results, tmp_path)


def test_modelo_entrenado_con_otra_corrida(minimal_results: Path, tmp_path: Path) -> None:
    _edit(minimal_results / "noshow.json", lambda d: d["data_version"].update(run_id="otra"))
    with pytest.raises(FactsError, match="otra"):
        load_facts(minimal_results, tmp_path)


def test_politica_desconocida(minimal_results: Path, tmp_path: Path) -> None:
    def edit(d: dict[str, Any]) -> None:
        d["config"]["policies"].append("magica")
        d["aggregate"]["magica"] = d["aggregate"]["fifo"]

    _edit(minimal_results / "simulation.json", edit)
    with pytest.raises(FactsError, match="magica"):
        load_facts(minimal_results, tmp_path)


def test_espejo_inconsistente(minimal_results: Path, tmp_path: Path) -> None:
    def edit(d: dict[str, Any]) -> None:
        d["comparisons"]["fifo_vs_priority"]["exits_attended"]["mean_diff"] = 99.0

    _edit(minimal_results / "simulation.json", edit)
    with pytest.raises(FactsError, match="espejo"):
        load_facts(minimal_results, tmp_path)
