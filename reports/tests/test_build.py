"""Pruebas del renderizado: plantillas sin cifras escritas a mano, determinismo y fidelidad."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from reports.build import TEMPLATES_DIR, build_report, render_markdown
from reports.cli import app
from reports.facts import load_facts
from typer.testing import CliRunner

from reports import fmt

DISCLAIMER = (
    "Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas "
    "ni de gestión real sin validación institucional."
)
ALLOWED_LABELS = ("p90", "p50", "IC 95 %", "0-14")
JINJA_TAGS = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
HTML_NOISE = re.compile(r"<style\b.*?</style>|<[^>]+>", re.DOTALL | re.IGNORECASE)


def _digits_outside_tags(text: str) -> list[str]:
    stripped = JINJA_TAGS.sub("", text)
    for label in ALLOWED_LABELS:
        stripped = stripped.replace(label, "")
    return [line for line in stripped.splitlines() if re.search(r"\d", line)]


def test_plantilla_markdown_sin_digitos_fuera_de_etiquetas() -> None:
    text = (TEMPLATES_DIR / "results.md.j2").read_text(encoding="utf-8")
    assert _digits_outside_tags(text) == []


def test_plantilla_html_sin_digitos_en_el_texto_visible() -> None:
    text = (TEMPLATES_DIR / "page.html.j2").read_text(encoding="utf-8")
    visible = HTML_NOISE.sub("", text)
    assert _digits_outside_tags(visible) == []


def test_el_detector_de_digitos_funciona() -> None:
    assert _digits_outside_tags("Hay 3 casos {{ n }} y p90") == ["Hay 3 casos  y "]
    assert _digits_outside_tags("{# 12 #}{{ 5 }}{% if 7 %}x{% endif %}") == []


def test_cada_seccion_deja_un_marcador_de_narrativa() -> None:
    text = (TEMPLATES_DIR / "results.md.j2").read_text(encoding="utf-8")
    sections = re.findall(r"^## ", text, flags=re.MULTILINE)
    markers = re.findall(r"\{# narrativa:", text)
    assert len(markers) >= len(sections)


def test_las_plantillas_no_contienen_cifras_en_la_prosa_de_los_marcadores() -> None:
    text = (TEMPLATES_DIR / "results.md.j2").read_text(encoding="utf-8")
    for comment in re.findall(r"\{# narrativa:.*?#\}", text, flags=re.DOTALL):
        for label in ALLOWED_LABELS:
            comment = comment.replace(label, "")
        assert not re.search(r"\d", comment)


def test_informe_minimo_es_determinista(minimal_results: Path, tmp_path: Path) -> None:
    first = build_report(minimal_results, tmp_path / "a", tmp_path)
    second = build_report(minimal_results, tmp_path / "b", tmp_path)
    for one, two in zip(first, second, strict=True):
        assert one.read_bytes() == two.read_bytes()


def test_informe_minimo_contiene_aviso_y_advertencia_de_tamano(
    minimal_results: Path, tmp_path: Path
) -> None:
    md_path, html_path = build_report(minimal_results, tmp_path / "out", tmp_path)
    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert DISCLAIMER in md
    assert DISCLAIMER in html
    assert "<script" not in html
    assert "no son comparables con las del plan canónico" in md
    assert "100" in md  # el tamaño de la simulación sale de los datos
    assert "<table>" in html


def test_resultados_negativos_aparecen_en_el_informe(minimal_results: Path, tmp_path: Path) -> None:
    facts = load_facts(minimal_results, tmp_path)
    md = render_markdown(facts)
    worse_total = sum(c["n_worse"] for c in facts["simulation"]["comparisons"])
    assert worse_total > 0
    worse_rows = [line for line in md.splitlines() if line.rstrip().endswith("| empeora |")]
    assert len(worse_rows) == worse_total
    # un grupo desfavorable nunca se omite: cada grupo de la dimensión aparece en su tabla
    for dim in facts["equity"]["simulation"]:
        for group in dim["shown"]:
            assert fmt.label(group["value"]) in md


def test_informe_real_contiene_el_aviso_y_sale_de_los_hechos(
    repo_root: Path, tmp_path: Path
) -> None:
    results = repo_root / "results"
    facts = load_facts(results, repo_root)
    md_path, html_path = build_report(results, tmp_path / "out", repo_root)
    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert DISCLAIMER in md
    assert DISCLAIMER in html

    sched = facts["scheduler"]
    sim = facts["simulation"]
    noshow = facts["noshow"]
    samples = [
        fmt.num(sched["rows"][0]["scheduled"]),
        fmt.num(sched["rows"][-1]["ges_met"]),
        fmt.num(sched["rows"][-1]["sum_coef"]),
        fmt.num(sim["run"]["size"]),
        fmt.num(sim["canonical_size"]),
        fmt.num(noshow["primary_metrics"]["auc"], 3),
        fmt.signed(noshow["vs_baseline"]["brier_difference"], 4),
        fmt.ci(sim["metrics"][0]["by_policy"]["optimized"], sim["metrics"][0]["kind"]),
        fmt.num(facts["context"]["national"][0]["waiting_count"]),
        fmt.num(facts["calibration"]["summary"]["strict_passed"]),
    ]
    for sample in samples:
        assert sample in md, sample


def test_informe_real_dice_que_la_simulacion_no_es_del_tamano_canonico(
    repo_root: Path, tmp_path: Path
) -> None:
    facts = load_facts(repo_root / "results", repo_root)
    md = render_markdown(facts)
    sim = facts["simulation"]
    if sim["is_canonical_size"]:
        pytest.skip("la simulación guardada usa el tamaño canónico")
    assert f"{fmt.num(sim['run']['size'])} entradas" in md
    assert f"{fmt.num(sim['canonical_size'])} entradas" in md
    assert "no son comparables" in md


def test_informe_real_es_determinista(repo_root: Path, tmp_path: Path) -> None:
    results = repo_root / "results"
    first = build_report(results, tmp_path / "a", repo_root)
    second = build_report(results, tmp_path / "b", repo_root)
    for one, two in zip(first, second, strict=True):
        assert one.read_bytes() == two.read_bytes()


def test_no_hay_hora_de_generacion(minimal_results: Path, tmp_path: Path) -> None:
    md = render_markdown(load_facts(minimal_results, tmp_path))
    assert "Generado el" not in md
    assert "generado a las" not in md.lower()


def test_cli_genera_los_archivos(minimal_results: Path, tmp_path: Path) -> None:
    out = tmp_path / "docs"
    result = CliRunner().invoke(
        app,
        [
            "--results-dir",
            str(minimal_results),
            "--out-dir",
            str(out),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "results.md").is_file()
    assert (out / "results.html").is_file()


def test_cli_falla_con_mensaje_claro(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["--results-dir", str(tmp_path / "vacio"), "--out-dir", str(tmp_path / "docs")],
    )
    assert result.exit_code == 1
    assert "falta" in result.output


def test_informe_avisa_de_grupos_en_menos_replicas_y_sentido_de_la_brecha(
    minimal_results: Path,
    tmp_path: Path,
    drop_group_in_first_replica: Callable[[Path, str, str], None],
) -> None:
    drop_group_in_first_replica(minimal_results, "insurance", "other")
    text = render_markdown(load_facts(minimal_results, tmp_path))
    assert "no alcanzan el mínimo de entradas en todas las réplicas" in text
    assert "presente en" in text
    assert "una diferencia negativa indica subestimación" in text


def test_informe_imprime_la_brecha_con_signo_y_las_entradas_cuadran(
    minimal_results: Path, tmp_path: Path
) -> None:
    import json

    path = minimal_results / "noshow.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for block in data["fairness"].values():
        if isinstance(block, dict) and "groups" in block:
            block["groups"][-1]["gap_vs_truth"] = -0.0321
    path.write_text(json.dumps(data), encoding="utf-8")
    text = render_markdown(load_facts(minimal_results, tmp_path))
    assert "(predicha menos verdad, con su signo): -3,21 pp" in text
    assert "entradas ingresan en la fase 3b" in text
    assert "citas agregadas por sobrecupo" not in text
    assert "210 entradas en espera, 210 tienen algún bloque compatible y 0 no tienen" in text
