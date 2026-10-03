"""Genera las fixtures de ingestion a partir de los originales públicos.

Script MANUAL (puede usar la red); no se ejecuta en CI. Es independiente del
código de ``ingestion``: usa pdfplumber, pypdf y openpyxl directamente.

Uso::

    uv run --no-project --with pdfplumber --with pypdf --with openpyxl \
        python ingestion/tests/fixtures/make_fixtures.py [--local-dir DIR]

Orden de búsqueda de cada original:

1. ``--local-dir`` (archivos ``<source_id>.<ext>`` o los alias de ``LOCAL_ALIASES``).
2. Caché ``data/raw/<source_id>/<fecha>/<archivo>`` (la más reciente).
3. Descarga desde la URL oficial hacia esa misma caché.

La salida es determinista: ejecutarlo dos veces no cambia ningún byte.

Las fixtures son extractos mínimos con atribución (fuente: Minsal, Superintendencia
de Salud y datos.gob.cl). No contienen datos de personas. Aviso: Herramienta de
investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión
real sin validación institucional.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
USER_AGENT = "Mozilla/5.0 (compatible; Prioriza/0.1; +https://github.com/TheNewAarons/prioriza)"

# Banda de cabecera / región de tabla (pt; la página mide 612x792).
# Nota: el contrato propone 75 pt, pero el título de la Tabla 16 de la Glosa III-2025
# (p. 28) está en top=73; con 75 se perdería. La cabecera real termina en top~62.
HEADER_BAND = 70.0
FOOTER_BAND = 712.0
LINE_TOLERANCE = 3.0

SOURCES = {
    "glosa06_2025q3": {
        "url": "https://www.minsal.cl/wp-content/uploads/2025/11/1764018133827_Glosa-06-LE-III-trimestre-2025.pdf",
        "sha256": "b4fe13ea8afffd9d47fb33ae3a2f071dc6acc13539dd5094d0f8ba29809c4d7c",
        "filename": "Glosa-06-LE-III-trimestre-2025.pdf",
        "publisher": "Minsal",
    },
    "glosa06_2025q4": {
        "url": "https://www.minsal.cl/wp-content/uploads/2026/02/Glosa-06-LE-IV-trimestre.pdf",
        "sha256": "4e3dab4685b6c3c396fe30a7cfefce44fc493ad72851e7901bbcdd4aed461c55",
        "filename": "Glosa-06-LE-IV-trimestre.pdf",
        "publisher": "Minsal",
    },
    "glosa06_2026q1": {
        "url": "https://www.minsal.cl/wp-content/uploads/2026/07/Glosa-06-letra-a-b-c-i-j-k-comun-a-la-partida-1er-trimestre-1.pdf",
        "sha256": "eed1e288e8572bc87daefb4b366ebe915fe6b8b0563fc9abec1d746632bafefb",
        "filename": "Glosa-06-letra-a-b-c-i-j-k-comun-a-la-partida-1er-trimestre-1.pdf",
        "publisher": "Minsal",
    },
    "sis_ges_cases_2026q1": {
        "url": "https://www.superdesalud.gob.cl/app/uploads/2026/07/estadistica-trimestral-de-casos-ges-auge-de-fonasa-y-sistema-isapre-marzo-2026-1.xlsx",
        "sha256": "60799377e494f31aa2147bc53329cd2cfbfc43540989fb5b12be909b1a2e5352",
        "filename": "estadistica-trimestral-de-casos-ges-auge-de-fonasa-y-sistema-isapre-marzo-2026-1.xlsx",
        "publisher": "Superintendencia de Salud",
    },
    "minsal_establishments": {
        "url": "https://datos.gob.cl/api/3/action/resource_show?id=2c44d782-3365-44e3-aefb-2c8b8363a1bc",
        "sha256": None,
        "filename": "establecimientos.csv",
        "publisher": "Minsal (datos.gob.cl, CC0)",
    },
}

LOCAL_ALIASES = {
    "glosa06_2025q3": ["e1.pdf"],
    "glosa06_2025q4": ["e2a.pdf"],
    "glosa06_2026q1": ["e2b.pdf"],
    "sis_ges_cases_2026q1": ["e3_2026q1.xlsx"],
    "minsal_establishments": ["e5.csv"],
}

# Anclas por tabla (sobre el título normalizado: sin tildes, minúsculas).
TABLE_ANCHORS = {
    "noges_national_by_subtype": r"numero de registros y personas en lista de espera no ges .* segun tipo de prestacion",
    "cne_by_service": r"consultas? nueva especialidad: registros, personas, promedios y medianas de espera (por|segun) servicio de salud",
    "cne_medical_by_specialty": r"numero de registros en lista de espera para (consulta nueva de especialidad medica|cne medica) segun especialidades",
    "cne_dental_by_specialty": r"numero de registros en lista de espera (consulta nueva especialidad|cne) odontologica segun especialidad",
    "iq_by_service": r"numero de registros en lista de espera para (intervenciones quirurgicas|iq) por numero de registros y numero de personas",
    "iq_by_specialty": r"numero de registros y personas en lista de espera de (intervenciones quirurgicas|iq) desagregadas por especialidad",
    "ges_delayed_by_service": r"garantias de oportunidad ges retrasadas acumuladas al .+ por servicio de salud y segun sexo",
    "ges_delayed_by_problem": r"garantias de oportunidad ges retrasadas acumuladas al .+ distribuidas por problema de salud y tramo",
}

# Columnas de teléfono y dirección: se vacían en el CSV de establecimientos.
CSV_BLANK_COLUMNS = ("TelefonoMovil_TelefonoFijo", "TipoViaGlosa", "NombreVia", "Numero")

FIXED_ZIP_DATE = (2026, 1, 1, 0, 0, 0)
FIXED_DATETIME = None  # se asigna en main() (datetime fijo para openpyxl)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(text: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", text).strip()


def locate(source_id: str, local_dir: Path | None, download: bool = True) -> Path:
    spec = SOURCES[source_id]
    if local_dir is not None:
        for name in LOCAL_ALIASES[source_id]:
            cand = local_dir / name
            if cand.exists():
                return cand
    cache = REPO / "data" / "raw" / source_id
    if cache.exists():
        for sub in sorted(cache.iterdir(), reverse=True):
            cand = sub / spec["filename"]
            if cand.exists():
                return cand
    if not download:
        raise FileNotFoundError(source_id)
    dest_dir = cache / date.today().isoformat()
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = spec["url"]
    if source_id == "minsal_establishments":
        info = json.loads(http_get(url))
        url = info["result"]["url"]
    dest = dest_dir / spec["filename"]
    dest.write_bytes(http_get(url))
    return dest


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def check_sha(source_id: str, path: Path) -> str:
    actual = sha256_of(path)
    expected = SOURCES[source_id]["sha256"]
    if expected and actual != expected:
        raise SystemExit(f"sha256 inesperado para {source_id}: {actual} != {expected}")
    return actual


def dump_json(obj: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# PDF: volcados de palabras
# ---------------------------------------------------------------------------


def group_lines(words: list[dict]) -> list[list[dict]]:
    """Agrupa palabras por línea (tolerancia de 3 pt en ``top``)."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def find_tables(pages_words: dict[int, list[dict]]) -> dict[str, list[dict]]:
    """Localiza cada tabla: página inicial, ``top`` del título y fin (Fuente)."""
    found: dict[str, list[dict]] = {k: [] for k in TABLE_ANCHORS}
    page_lines = {
        n: group_lines([w for w in ws if HEADER_BAND <= w["top"] <= FOOTER_BAND])
        for n, ws in pages_words.items()
    }
    for n in sorted(page_lines):
        lines = page_lines[n]
        for i, line in enumerate(lines):
            if not re.match(r"tabla \d+\.", norm(line_text(line))):
                continue
            title = norm(" ".join(line_text(x) for x in lines[i : i + 2]))
            for key, rx in TABLE_ANCHORS.items():
                if re.search(rx, title):
                    found[key].append({"page": n, "top": line[0]["top"], "label": line_text(line)})
    for key, hits in found.items():
        # el título se repite en las páginas de continuación (p. ej. Tabla 5): se
        # conserva solo la primera aparición de una racha de páginas consecutivas
        dedup: list[dict] = []
        for hit in hits:
            if (
                dedup
                and hit["label"] == dedup[-1]["label"]
                and hit["page"] == dedup[-1]["last"] + 1
            ):
                dedup[-1]["last"] = hit["page"]
            else:
                dedup.append({**hit, "last": hit["page"]})
        found[key] = hits = dedup
        if len(hits) != 1:
            raise SystemExit(f"ancla {key}: {len(hits)} coincidencias (se esperaba 1): {hits}")
    out = {}
    for key, hits in found.items():
        hit = hits[0]
        end_page = end_top = None
        for n in sorted(p for p in page_lines if p >= hit["page"]):
            for i, line in enumerate(page_lines[n]):
                if n == hit["page"] and line[0]["top"] <= hit["top"]:
                    continue
                if line[0]["text"].startswith("Fuente:"):
                    # la línea Fuente puede continuar en la siguiente hasta la extracción
                    last = line[0]["top"]
                    for extra in page_lines[n][i : i + 3]:
                        last = extra[0]["top"]
                        if re.search(r"xtracci\S*", line_text(extra)) and re.search(
                            r"\d\d/\d\d/\d{4}", line_text(extra)
                        ):
                            break
                    end_page, end_top = n, last
                    break
            if end_page is not None:
                break
        if end_page is None:
            raise SystemExit(f"sin línea Fuente para {key}")
        out[key] = {**hit, "end_page": end_page, "end_top": end_top}
    return out


def build_word_dumps(pdf_path: Path, source_id: str, out_dir: Path) -> dict:
    import pdfplumber

    pages_words: dict[int, list[dict]] = {}
    sizes: dict[int, tuple[float, float]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            pages_words[n] = page.extract_words()
            sizes[n] = (page.width, page.height)
    tables = find_tables(pages_words)

    # intervalos [desde, hasta] de ``top`` que se conservan por página
    intervals: dict[int, list[tuple[float, float]]] = {}
    for info in tables.values():
        for n in range(info["page"], info["end_page"] + 1):
            lo = info["top"] - 1.0 if n == info["page"] else HEADER_BAND
            hi = info["end_top"] + 3.0 if n == info["end_page"] else FOOTER_BAND
            intervals.setdefault(n, []).append((lo, hi))

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("p*.words.json"):
        stale.unlink()
    kept_pages = []
    total_words = 0
    for n in sorted(intervals):
        keep = []
        for w in pages_words[n]:
            top = w["top"]
            in_band = top < HEADER_BAND or top > sizes[n][1] - 80.0  # páginas apaisadas: 612 pt
            in_region = any(lo <= top <= hi for lo, hi in intervals[n])
            if in_band or in_region:
                keep.append(w)
        keep.sort(key=lambda w: (round(w["top"], 2), round(w["x0"], 2)))
        payload = {
            "source_id": source_id,
            "page_number": n,
            "width": round(float(sizes[n][0]), 2),
            "height": round(float(sizes[n][1]), 2),
            "words": [
                {
                    "text": w["text"],
                    "x0": round(float(w["x0"]), 2),
                    "x1": round(float(w["x1"]), 2),
                    "top": round(float(w["top"]), 2),
                    "bottom": round(float(w["bottom"]), 2),
                }
                for w in keep
            ],
        }
        dump_json(payload, out_dir / f"p{n:02d}.words.json")
        kept_pages.append(n)
        total_words += len(keep)
    return {
        "pages": kept_pages,
        "words": total_words,
        "tables": {
            k: {"label": v["label"], "pages": list(range(v["page"], v["end_page"] + 1))}
            for k, v in tables.items()
        },
    }


def build_single_page_pdf(pdf_path: Path, page_number: int, dest: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_number - 1])
    writer.add_metadata({"/Producer": "pypdf", "/Title": "Extracto Glosa 06 (Minsal)"})
    buf = io.BytesIO()
    writer.write(buf)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(buf.getvalue())


# ---------------------------------------------------------------------------
# XLSX mínimo (SIS GES)
# ---------------------------------------------------------------------------


def build_sis_ges_mini(xlsx_path: Path, dest: Path) -> dict:
    import datetime as dt

    import openpyxl

    src = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    kept_rows: dict[str, list[int]] = {}
    for sheet in ("Año 2025", "Año 2026"):
        ws_src = src[sheet]
        rows = list(ws_src.iter_rows(min_row=1, max_col=12, values_only=True))
        header_idx = next(i for i, r in enumerate(rows) if r[1] == "PROBLEMA DE SALUD")
        ws = wb.create_sheet(sheet)
        # filas previas al encabezado (título y 2 filas en blanco), tal cual
        out_row = 1
        for r in rows[: header_idx + 3]:  # encabezado + aseguradoras + fechas de corte
            for c, v in enumerate(r, 1):
                if v is not None:
                    ws.cell(out_row, c, v)
            out_row += 1
        data = [r for r in rows[header_idx + 3 :] if r[0] in (1, 2, 3, 4, 5, 0)]
        problems = [r for r in data if r[0] in (1, 2, 3, 4, 5)]
        zero = [r for r in data if r[0] == 0]
        kept_rows[sheet] = [r[0] for r in problems + zero]
        for r in problems + zero:
            for c, v in enumerate(r, 1):
                if v is not None:
                    ws.cell(out_row, c, v)
            out_row += 1
        # TOTAL GENERAL re-totalizado sobre las filas conservadas
        ws.cell(out_row, 2, "TOTAL GENERAL")
        for c in range(3, 13):
            vals = [r[c - 1] for r in problems if isinstance(r[c - 1], (int, float))]
            if vals:
                ws.cell(out_row, c, int(sum(vals)))
        # celdas combinadas de encabezado (pares FONASA/ISAPRE), igual que el original
        for c in (3, 5, 7, 9, 11):
            ws.merge_cells(
                start_row=header_idx + 1, start_column=c, end_row=header_idx + 1, end_column=c + 1
            )
    fixed = dt.datetime(2026, 1, 1)
    wb.properties.created = fixed
    wb.properties.modified = fixed
    wb.properties.creator = "make_fixtures"
    wb.properties.lastModifiedBy = "make_fixtures"
    buf = io.BytesIO()
    wb.save(buf)
    # reempaqueta con fechas de zip fijas (openpyxl usa la hora actual)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zin,
        zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for name in sorted(zin.namelist()):
            info = zipfile.ZipInfo(name, FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            data = zin.read(name)
            if name == "docProps/core.xml":
                # openpyxl sella la fecha de modificación al guardar: se fija
                data = re.sub(
                    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                    rb"\g<1>2026-01-01T00:00:00Z\g<2>",
                    data,
                )
            zout.writestr(info, data)
    return {"sheets": ["Año 2025", "Año 2026"], "rows_kept": kept_rows}


# ---------------------------------------------------------------------------
# CSV de establecimientos
# ---------------------------------------------------------------------------


def build_establishments_sample(csv_path: Path, dest: Path) -> dict:
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = next(reader)
        rows = list(reader)
    ix = {c: i for i, c in enumerate(header)}

    def col(r: list[str], name: str) -> str:
        return r[ix[name]]

    def first(pred, exclude: set[str]):
        for r in rows:
            if col(r, "EstablecimientoCodigo") not in exclude and pred(r):
                return r
        raise SystemExit(f"no se encontró fila para el predicado #{len(chosen) + 1}")

    chosen: list[list[str]] = []
    taken: set[str] = set()

    def add(pred) -> None:
        r = first(pred, taken)
        taken.add(col(r, "EstablecimientoCodigo"))
        chosen.append(r)

    glosa = "SeremiSaludGlosa_ServicioDeSaludGlosa"
    est = "EstadoFuncionamiento"
    has_geo = lambda r: bool(col(r, "Latitud").strip() and col(r, "Longitud").strip())  # noqa: E731
    open_ = lambda r: col(r, est).lower().startswith("vigente")  # noqa: E731
    snss = lambda r: col(r, "TipoPertenenciaEstabGlosa").lower().startswith("perteneciente")  # noqa: E731
    # SNSS: hospital de un Servicio de Salud con urgencia y coordenadas
    add(
        lambda r: (
            snss(r)
            and col(r, "TipoEstablecimientoGlosa") == "Hospital"
            and open_(r)
            and has_geo(r)
            and col(r, "TieneServicioUrgencia") == "SI"
            and col(r, glosa).startswith("Servicio de Salud")
            and col(r, "RegionCodigo").lstrip("0") == "13"
        )
    )
    # SNSS: consultorio/CESFAM en otra región
    add(
        lambda r: (
            snss(r)
            and open_(r)
            and has_geo(r)
            and col(r, "RegionCodigo").lstrip("0") == "5"
            and col(r, glosa).startswith("Servicio de Salud")
        )
    )
    # Privado (no SNSS) con coordenadas
    add(
        lambda r: (
            not snss(r)
            and col(r, "TipoPertenenciaEstabGlosa").lower().startswith("no perteneciente")
            and open_(r)
            and has_geo(r)
            and col(r, "TipoSistemaSaludGlosa") != "Público"
        )
    )
    # Glosa SEREMI con código compartido 06 (y su variante O?Higgins)
    add(lambda r: col(r, glosa).startswith("SEREMI de Salud del Libertador") and open_(r))
    add(
        lambda r: (
            col(r, "SeremiSaludCodigo_ServicioDeSaludCodigo") == "06"
            and col(r, glosa).startswith("Servicio de Salud")
            and open_(r)
            and has_geo(r)
        )
    )
    # Servicio con apóstrofo y servicio con doble espacio
    add(lambda r: col(r, glosa) == "Servicio de Salud O'Higgins" and open_(r) and has_geo(r))
    add(lambda r: col(r, glosa) == "Servicio de Salud  Reloncaví" and open_(r) and has_geo(r))
    # Servicio "No Aplica" (con y sin código)
    add(
        lambda r: (
            col(r, glosa) == "No Aplica" and col(r, "SeremiSaludCodigo_ServicioDeSaludCodigo") == ""
        )
    )
    add(
        lambda r: (
            col(r, glosa) == "No Aplica"
            and col(r, "SeremiSaludCodigo_ServicioDeSaludCodigo") == "95"
        )
    )
    # Cerrado, con fecha de cierre
    add(lambda r: col(r, est) == "Cerrado" and col(r, "FechaCierre").strip() != "" and has_geo(r))
    # Vigente sin coordenadas
    add(lambda r: open_(r) and not has_geo(r) and col(r, glosa).startswith("Servicio de Salud"))
    # Las dos variantes de "Vigente en operación habitual"
    add(
        lambda r: (
            col(r, est) == "Vigente en Operación Habitual"
            and col(r, "TieneServicioUrgencia") == "No Aplica"
        )
    )
    add(
        lambda r: (
            col(r, est) == "Vigente en operación habitual"
            and has_geo(r)
            and col(r, glosa).startswith("Servicio de Salud")
        )
    )
    # Variante de minúsculas en "No perteneciente" y valor vacío en urgencia
    add(lambda r: col(r, "TieneServicioUrgencia") == "")
    add(
        lambda r: (
            col(r, "TipoPertenenciaEstabGlosa")
            == "No perteneciente al Sistema Nacional de Servicios de Salud"
            and open_(r)
        )
    )

    chosen.sort(key=lambda r: col(r, "EstablecimientoCodigo"))
    for r in chosen:
        for name in CSV_BLANK_COLUMNS:
            r[ix[name]] = ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(chosen)
    dest.write_text(buf.getvalue(), encoding="utf-8", newline="\n")
    return {
        "rows": len(chosen),
        "columns": len(header),
        "establishment_codes": [col(r, "EstablecimientoCodigo") for r in chosen],
        "blanked_columns": list(CSV_BLANK_COLUMNS),
    }


def build_ckan_json(search_json: Path | None, dest: Path) -> None:
    """Respuesta grabada de ``resource_show`` (tomada del recurso real)."""
    resource = None
    if search_json is not None and search_json.exists():
        data = json.loads(search_json.read_text(encoding="utf-8"))
        for pkg in data["result"]["results"]:
            if pkg["name"] == "establecimientos-de-salud-vigentes":
                resource = next(
                    r for r in pkg["resources"] if r["id"] == "2c44d782-3365-44e3-aefb-2c8b8363a1bc"
                )
    if resource is None:
        resource = json.loads(http_get(SOURCES["minsal_establishments"]["url"]))["result"]
    payload = {
        "help": "https://datos.gob.cl/api/3/action/help_show?name=resource_show",
        "success": True,
        "result": resource,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--local-dir", type=Path, default=None, help="directorio con los originales"
    )
    args = parser.parse_args(argv)

    manifest: dict[str, object] = {
        "_nota": "Extractos mínimos con atribución; fuente Minsal / SIS / datos.gob.cl. "
        "Sin datos personales. Generado por make_fixtures.py.",
        "fixtures": {},
    }
    fixtures: dict[str, object] = manifest["fixtures"]  # type: ignore[assignment]

    glosa_dir = HERE / "glosa06"
    for source_id in ("glosa06_2025q3", "glosa06_2025q4", "glosa06_2026q1"):
        path = locate(source_id, args.local_dir)
        sha = check_sha(source_id, path)
        info = build_word_dumps(path, source_id, glosa_dir / source_id)
        fixtures[f"glosa06/{source_id}/"] = {
            "url": SOURCES[source_id]["url"],
            "original_sha256": sha,
            "kind": "volcado de palabras (pdfplumber.extract_words, 2 decimales)",
            "pages_kept": info["pages"],
            "words_kept": info["words"],
            "tables": info["tables"],
            "note": "extracto; fuente Minsal",
        }
        if source_id == "glosa06_2026q1":
            dest = glosa_dir / "glosa06_2026q1_p26.pdf"
            build_single_page_pdf(path, 26, dest)
            fixtures["glosa06/glosa06_2026q1_p26.pdf"] = {
                "url": SOURCES[source_id]["url"],
                "original_sha256": sha,
                "kind": "PDF de 1 página (Tabla 12, recortada con pypdf)",
                "pages_kept": [26],
                "sha256": sha256_of(dest),
                "note": "extracto; fuente Minsal (cita breve con atribución, Ley 17.336 art. 71 B)",
            }

    path = locate("sis_ges_cases_2026q1", args.local_dir)
    sha = check_sha("sis_ges_cases_2026q1", path)
    dest = HERE / "sis_ges" / "sis_ges_cases_mini.xlsx"
    info = build_sis_ges_mini(path, dest)
    fixtures["sis_ges/sis_ges_cases_mini.xlsx"] = {
        "url": SOURCES["sis_ges_cases_2026q1"]["url"],
        "original_sha256": sha,
        "kind": "XLSX reducido (hojas Año 2025 y Año 2026; códigos 1-5, 0 y TOTAL GENERAL re-totalizado)",
        "sheets": info["sheets"],
        "rows_kept": info["rows_kept"],
        "sha256": sha256_of(dest),
        "note": "extracto; fuente Superintendencia de Salud",
    }

    path = locate("minsal_establishments", args.local_dir)
    sha = sha256_of(path)
    dest = HERE / "minsal_establishments" / "establishments_sample.csv"
    info = build_establishments_sample(path, dest)
    fixtures["minsal_establishments/establishments_sample.csv"] = {
        "url": SOURCES["minsal_establishments"]["url"],
        "original_sha256": sha,
        "kind": "CSV reducido (CC0), columnas de teléfono y dirección vaciadas",
        "rows_kept": info["rows"],
        "columns": info["columns"],
        "establishment_codes": info["establishment_codes"],
        "blanked_columns": info["blanked_columns"],
        "sha256": sha256_of(dest),
        "note": "extracto; fuente datos.gob.cl / Minsal (CC0)",
    }
    search = args.local_dir / "e5_search.json" if args.local_dir else None
    ckan_dest = HERE / "minsal_establishments" / "ckan_resource_show.json"
    build_ckan_json(search, ckan_dest)
    fixtures["minsal_establishments/ckan_resource_show.json"] = {
        "url": SOURCES["minsal_establishments"]["url"],
        "kind": "respuesta grabada de resource_show",
        "sha256": sha256_of(ckan_dest),
        "note": "extracto; fuente datos.gob.cl",
    }

    dump_json_pretty(manifest, HERE / "MANIFEST.json")
    print("fixtures generadas en", HERE)
    return 0


def dump_json_pretty(obj: object, path: Path) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    sys.exit(main())
