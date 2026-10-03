"""Lectura de palabras con coordenadas desde un PDF (único módulo que usa pdfplumber).

Las Glosas 06 no se pueden leer con ``find_tables()`` (solo detecta encabezado y total), así
que los parsers reconstruyen las tablas desde las palabras y su posición.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Word:
    """Una palabra con su caja (puntos PDF; ``top`` crece hacia abajo)."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class PageWords:
    """Todas las palabras de una página (``page_number`` base 1)."""

    page_number: int
    width: float
    height: float
    words: tuple[Word, ...]


def read_pdf_words(path: Path, pages: Iterable[int] | None = None) -> list[PageWords]:
    """Lee las palabras de un PDF; ``pages`` (base 1) restringe qué páginas leer."""
    import pdfplumber

    wanted = None if pages is None else set(pages)
    result: list[PageWords] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            if wanted is not None and number not in wanted:
                continue
            raw = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            words = tuple(
                Word(
                    text=str(w["text"]),
                    x0=float(w["x0"]),
                    x1=float(w["x1"]),
                    top=float(w["top"]),
                    bottom=float(w["bottom"]),
                )
                for w in raw
            )
            result.append(
                PageWords(
                    page_number=number,
                    width=float(page.width),
                    height=float(page.height),
                    words=words,
                )
            )
            page.flush_cache()
    return result


def load_words_json(path: Path) -> PageWords:
    """Carga una página desde el volcado JSON usado como fixture."""
    data = json.loads(path.read_text(encoding="utf-8"))
    words = tuple(
        Word(
            text=w["text"],
            x0=float(w["x0"]),
            x1=float(w["x1"]),
            top=float(w["top"]),
            bottom=float(w["bottom"]),
        )
        for w in data["words"]
    )
    return PageWords(
        page_number=int(data["page_number"]),
        width=float(data["width"]),
        height=float(data["height"]),
        words=words,
    )


def dump_words_json(page: PageWords, path: Path, *, source_id: str | None = None) -> None:
    """Escribe una página como JSON (coordenadas a 2 decimales)."""
    payload = {
        "source_id": source_id,
        "page_number": page.page_number,
        "width": round(page.width, 2),
        "height": round(page.height, 2),
        "words": [
            {
                "text": w.text,
                "x0": round(w.x0, 2),
                "x1": round(w.x1, 2),
                "top": round(w.top, 2),
                "bottom": round(w.bottom, 2),
            }
            for w in page.words
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
