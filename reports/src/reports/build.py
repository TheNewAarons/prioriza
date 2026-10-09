"""Renderizado del informe: Markdown con Jinja2 y HTML autocontenido con markdown-it-py.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión
real sin validación institucional.

La salida es determinista: no incluye hora de generación y los diccionarios se recorren en el
orden en que ``load_facts`` los arma.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markdown_it import MarkdownIt

from reports.facts import load_facts
from reports.fmt import FILTERS

TEMPLATES_DIR = Path(__file__).parent / "templates"
MARKDOWN_TEMPLATE = "results.md.j2"
HTML_TEMPLATE = "page.html.j2"
MARKDOWN_NAME = "results.md"
HTML_NAME = "results.html"
TITLE = "Informe de resultados de Prioriza"


def make_environment() -> Environment:
    """Entorno Jinja2 estricto (variable indefinida = error) y sin autoescape (Markdown)."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(FILTERS)
    return env


def render_markdown(facts: dict[str, Any]) -> str:
    """Renderiza ``results.md.j2`` con los hechos."""
    template = make_environment().get_template(MARKDOWN_TEMPLATE)
    rendered: str = template.render(**facts)
    return _tidy(rendered)


def _tidy(text: str) -> str:
    """Colapsa líneas en blanco consecutivas y deja un único salto de línea final."""
    out: list[str] = []
    blank = False
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(line)
    return "\n".join(out).strip("\n") + "\n"


def markdown_to_html(markdown: str) -> str:
    """Convierte el Markdown a un fragmento HTML (tablas activadas, sin HTML crudo)."""
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    body: str = parser.render(markdown)
    return body.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>"
    )


def render_html(markdown: str, facts: dict[str, Any]) -> str:
    """Página HTML autocontenida (CSS en línea, sin JS) con el aviso fijo arriba."""
    template = make_environment().get_template(HTML_TEMPLATE)
    return template.render(
        title=TITLE, disclaimer=facts["disclaimer"], body=markdown_to_html(markdown)
    )


def build_report(results_dir: Path, out_dir: Path, repo_root: Path) -> tuple[Path, Path]:
    """Genera ``results.md`` y ``results.html`` en ``out_dir`` y devuelve sus rutas."""
    facts = load_facts(results_dir, repo_root)
    markdown = render_markdown(facts)
    html = render_html(markdown, facts)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / MARKDOWN_NAME
    html_path = out_dir / HTML_NAME
    md_path.write_text(markdown, encoding="utf-8", newline="\n")
    html_path.write_text(html, encoding="utf-8", newline="\n")
    return md_path, html_path
