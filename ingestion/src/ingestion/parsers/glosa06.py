"""Parser de las tablas de la Glosa 06 (listas de espera) a partir de palabras con coordenadas.

Las tablas se reconstruyen desde las palabras de cada página (``pdf_words``):

1. Se agrupan las palabras en líneas por su coordenada ``top`` (tolerancia de 3 pt) y se
   descartan las cabeceras y los pies de página.
2. Cada tabla se ubica por una regex sobre el título normalizado (sin tildes, minúsculas,
   uniendo la línea del título con la siguiente), no por su número, que cambia entre
   trimestres.
3. Una línea es fila de datos si sus últimos ``n`` tokens son numéricos (``n`` = columnas
   numéricas de la tabla). Las celdas se asignan a columnas por posición horizontal (x), no
   por orden: cada fila debe traer exactamente una celda por columna; un dígito que es parte
   de la etiqueta ("tipo 2") queda a la izquierda de la zona numérica y sigue siendo etiqueta.
   El orden de los encabezados se verifica contra ``TableSpec.columns``.
   Las líneas sin números (etiquetas partidas en varias líneas) se unen a la fila numérica
   verticalmente más cercana (empate: la siguiente). En tablas con columna de código, si los
   números van en la primera línea de la etiqueta (diseño "arriba", p. ej. 2026q1) las
   líneas de continuación pertenecen siempre a la fila anterior; si van centrados (2025q3,
   2025q4) rige la regla de la fila más cercana.
4. La tabla termina en la fila ``Total`` (o en ``Fuente:`` si no tiene fila Total), de donde se
   leen la fecha de corte y de extracción.

Cualquier desviación del formato esperado lanza :class:`SchemaDriftError`.
"""

import re
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from pathlib import Path
from statistics import median
from types import MappingProxyType

from shared.health_services import (
    HOSPITAL_DIGITAL_NAME,
    UnknownHealthServiceError,
    resolve_health_service,
)
from shared.schemas import (
    CareSubtype,
    CareType,
    CountUnit,
    GesStatus,
    Grain,
    WaitBasis,
    WaitlistRecord,
)

from ingestion.errors import DataValidationError, SchemaDriftError
from ingestion.normalize import fold_text, normalize_specialty
from ingestion.parsers.numbers import is_number_token, parse_cl_number
from ingestion.pdf_words import PageWords, Word, read_pdf_words
from ingestion.sources import SourceSpec

#: Recorte vertical de página (pt): se excluyen la cabecera corrida y el número de página.
TOP_MIN = 60.0
BOTTOM_MARGIN = 70.0
#: Tolerancia para agrupar palabras en una línea (pt).
LINE_TOLERANCE = 3.0
#: Una línea sin números a lo sumo a esta distancia sobre la primera fila es etiqueta.
HEADER_GAP = 9.0
#: Si alguna línea de etiqueta está más cerca que esto (pt) de una fila de datos, los números
#: van centrados verticalmente respecto de la etiqueta; si no, están en su primera línea.
CENTERED_LAYOUT_GAP = 8.0
#: Semiancho (pt) de la zona de una columna cuando la tabla tiene una sola columna numérica.
SINGLE_COLUMN_HALF_WIDTH = 45.0
#: Tolerancia (pt) del borde izquierdo de la zona numérica.
ZONE_MARGIN = 2.0
#: Tolerancia de |razón - registros/personas| en las tablas por servicio.
RATIO_TOLERANCE = 0.01
#: Campos de días: ``-`` significa "sin dato" y no cero.
_DAY_FIELDS = frozenset({"mean_wait_days", "median_wait_days"})

_RUNNING_HEADER = re.compile(r"^(?:(?:primer|segundo|tercer|cuarto|i{1,3}|iv) )?trimestre \d{4}$")
_TABLE_TITLE = re.compile(r"^tabla (\d+)\.\s*")
_CUTOFF = re.compile(r"corte:\s*(\d{2}/\d{2}/\d{4})")
_EXTRACTION = re.compile(r"extraccion:\s*(\d{2}/\d{2}/\d{4})")


@dataclass(frozen=True)
class ColumnSpec:
    """Una columna numérica: campo destino y palabra clave de su encabezado."""

    field: str
    keyword: re.Pattern[str] | None = None


@dataclass(frozen=True)
class TableSpec:
    """Cómo ubicar y leer una tabla de la Glosa."""

    key: str
    anchor: re.Pattern[str]
    columns: tuple[ColumnSpec, ...]
    label_keyword: re.Pattern[str]
    has_code: bool = False
    ends_with_total: bool = True
    reorderable: bool = False


@dataclass
class TableResult:
    """Resultado de parsear una tabla: registros, totales publicados y procedencia."""

    key: str
    label: str
    pages: tuple[int, ...]
    records: list[WaitlistRecord]
    totals: dict[str, float]
    cutoff: date
    extracted_at: date | None


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _cols(*items: tuple[str, str | None]) -> tuple[ColumnSpec, ...]:
    return tuple(ColumnSpec(f, _re(k) if k else None) for f, k in items)


_SERVICE_COLUMNS = _cols(
    ("waiting_count", "registros"),
    ("persons_count", "personas"),
    ("ratio", "razon"),
    ("mean_wait_days", "promedio"),
    ("median_wait_days", "mediana"),
)
_SPECIALTY_REGISTROS = "registros|interconsultas"

GLOSA06_TABLES: Mapping[str, TableSpec] = MappingProxyType(
    {
        spec.key: spec
        for spec in (
            TableSpec(
                key="noges_national_by_subtype",
                anchor=_re(
                    r"numero de registros y personas en lista de espera no ges .* "
                    r"segun tipo de prestacion"
                ),
                columns=_cols(("waiting_count", "registros"), ("persons_count", "personas")),
                label_keyword=_re("tipo de prestacion"),
                ends_with_total=False,
                reorderable=True,
            ),
            TableSpec(
                key="cne_by_service",
                anchor=_re(
                    r"consultas? nueva especialidad: registros, personas, promedios y medianas "
                    r"de espera (?:por|segun) servicio de salud"
                ),
                columns=_SERVICE_COLUMNS,
                label_keyword=_re("servicio de salud"),
            ),
            TableSpec(
                key="cne_medical_by_specialty",
                anchor=_re(
                    r"numero de registros en lista de espera para "
                    r"(?:consulta nueva de especialidad medica|cne medica) segun especialidades"
                ),
                columns=_cols(("waiting_count", _SPECIALTY_REGISTROS)),
                label_keyword=_re("especialidad"),
            ),
            TableSpec(
                key="cne_dental_by_specialty",
                anchor=_re(
                    r"numero de registros en lista de espera "
                    r"(?:consulta nueva especialidad|cne) odontologica segun especialidad"
                ),
                columns=_cols(("waiting_count", _SPECIALTY_REGISTROS)),
                label_keyword=_re("especialidad"),
            ),
            TableSpec(
                key="iq_by_service",
                anchor=_re(
                    r"numero de registros en lista de espera para "
                    r"(?:intervenciones quirurgicas|iq) por numero de registros y numero "
                    r"de personas"
                ),
                columns=_SERVICE_COLUMNS,
                label_keyword=_re("servicio de salud"),
            ),
            TableSpec(
                key="iq_by_specialty",
                anchor=_re(
                    r"numero de registros y personas en lista de espera de "
                    r"(?:intervenciones quirurgicas|iq) desagregadas por especialidad"
                ),
                columns=_cols(
                    ("waiting_count", _SPECIALTY_REGISTROS), ("persons_count", "personas")
                ),
                label_keyword=_re("especialidad"),
                reorderable=True,
            ),
            TableSpec(
                key="ges_delayed_by_service",
                anchor=_re(
                    r"garantias de oportunidad ges retrasadas acumuladas al .+ por servicio "
                    r"de salud y segun sexo"
                ),
                columns=_cols(
                    ("female", "femenino"),
                    ("male", "masculino"),
                    ("undefined", "no definido"),
                    ("waiting_count", "total"),
                ),
                label_keyword=_re("servicio de salud"),
            ),
            TableSpec(
                key="ges_delayed_by_problem",
                anchor=_re(
                    r"garantias de oportunidad ges retrasadas acumuladas al .+ distribuidas "
                    r"por problema de salud y tramo"
                ),
                columns=_cols(
                    ("bucket1", None),
                    ("bucket2", None),
                    ("bucket3", None),
                    ("bucket4", None),
                    ("bucket5", None),
                    ("bucket6", None),
                    ("waiting_count", "total"),
                    ("mean_wait_days", "promedio"),
                    ("median_wait_days", "mediana"),
                ),
                label_keyword=_re("problema de salud"),
                has_code=True,
            ),
        )
    }
)


@dataclass(frozen=True)
class Line:
    """Una línea de texto de una página, con sus palabras ordenadas por ``x0``."""

    page: int
    top: float
    y: float
    tokens: tuple[Word, ...]
    norm: str


@dataclass
class _Hit:
    index: int
    consumed: int
    label: str


@dataclass
class _Group:
    """Una fila: su línea de datos y las líneas de etiqueta que se le unieron."""

    data: Line
    labels: list[Line] = field(default_factory=list)


@dataclass
class _RawRow:
    label: str
    code: int | None
    values: dict[str, float]


def build_lines(pages: Sequence[PageWords]) -> list[Line]:
    """Agrupa las palabras de las páginas en líneas, recortando cabecera y pie de página."""
    lines: list[Line] = []
    offset = 0.0
    for page in pages:
        words = sorted(
            (w for w in page.words if w.top >= TOP_MIN and w.bottom <= page.height - BOTTOM_MARGIN),
            key=lambda w: (w.top, w.x0),
        )
        current: list[Word] = []
        anchor_top = 0.0

        def flush(
            current: list[Word] = current, page: PageWords = page, offset: float = offset
        ) -> None:
            if not current:
                return
            tokens = tuple(sorted(current, key=lambda w: w.x0))
            norm = fold_text(" ".join(w.text for w in tokens))
            if _RUNNING_HEADER.match(norm):
                return
            top = min(w.top for w in tokens)
            lines.append(Line(page.page_number, top, offset + top, tokens, norm))

        for word in words:
            if current and abs(word.top - anchor_top) > LINE_TOLERANCE:
                flush()
                current.clear()
            if not current:
                anchor_top = word.top
            current.append(word)
        flush()
        offset += page.height
    return lines


def _is_data(line: Line, n: int) -> bool:
    tokens = line.tokens
    return len(tokens) >= n and all(is_number_token(w.text) for w in tokens[-n:])


def _trailing_numbers(line: Line) -> int:
    count = 0
    for word in reversed(line.tokens):
        if not is_number_token(word.text):
            break
        count += 1
    return count


def _is_source_line(line: Line) -> bool:
    return line.norm.startswith("fuente")


def _drift(source: SourceSpec, key: str, detail: str, **kw: str | None) -> SchemaDriftError:
    return SchemaDriftError(source.source_id, key, detail, kw.get("expected"), kw.get("found"))


def _find_hits(lines: Sequence[Line], spec: TableSpec) -> list[_Hit]:
    hits: list[_Hit] = []
    for i, line in enumerate(lines):
        match = _TABLE_TITLE.match(line.norm)
        if match is None:
            continue
        rest = line.norm[match.end() :]
        consumed = 1
        found = spec.anchor.search(rest)
        if found is None and i + 1 < len(lines):
            found = spec.anchor.search(rest + " " + lines[i + 1].norm)
            consumed = 2
        if found is not None:
            hits.append(_Hit(i, consumed, f"Tabla {match.group(1)}"))
    return hits


def _keywords(spec: TableSpec) -> list[re.Pattern[str]]:
    return [spec.label_keyword] + [c.keyword for c in spec.columns if c.keyword is not None]


def _missing_keywords(spec: TableSpec, text: str) -> list[str]:
    return [k.pattern for k in _keywords(spec) if k.search(text) is None]


def _is_header_block(spec: TableSpec, block: Sequence[Line], hit_indices: set[int]) -> bool:
    """¿El bloque inicial de una página de continuación repite título o encabezado?"""
    text = " ".join(line.norm for line in block)
    distinct = sum(1 for k in _keywords(spec) if k.search(text) is not None)
    return distinct >= 2


def _walk(
    lines: Sequence[Line], spec: TableSpec, hits: Sequence[_Hit], source: SourceSpec
) -> tuple[list[_Group], list[Line], Line | None, int, list[Line]]:
    """Recorre la tabla. Devuelve grupos de filas, etiquetas sueltas, fila Total, fin, cabecera."""
    n = len(spec.columns)
    start = hits[0]
    j = start.index + start.consumed
    header: list[Line] = []
    header_text = ""
    first: int | None = None
    keywords_done: int | None = None
    while j < len(lines):
        line = lines[j]
        if _is_source_line(line):
            raise _drift(
                source,
                spec.key,
                "encabezado cambió",
                expected=", ".join(_missing_keywords(spec, header_text)) or "datos",
                found=header_text[-120:],
            )
        if _is_data(line, n) and not _missing_keywords(spec, header_text):
            first = j
            break
        header.append(line)
        header_text += " " + line.norm
        if keywords_done is None and not _missing_keywords(spec, header_text):
            keywords_done = len(header)
        j += 1
    if first is None:
        raise _drift(source, spec.key, "no se encontró el fin de la tabla (falta 'Fuente:')")

    groups: list[_Group] = []
    loose: list[Line] = []
    first_line = lines[first]
    for line in reversed(header):
        if line.page == first_line.page and first_line.top - line.top <= HEADER_GAP:
            loose.append(line)
            first_line = line
        else:
            break
    # Una fila de datos con celdas faltantes antes de la primera fila completa no es un
    # encabezado: casi todas sus columnas traen cifras al final de la línea.
    for ln in header[keywords_done or 0 :]:
        if _trailing_numbers(ln) >= max(2, n - 2):
            raise _drift(
                source,
                spec.key,
                "fila sin las celdas esperadas antes de la primera fila de datos",
                found=" ".join(w.text for w in ln.tokens),
            )
    hit_indices = {h.index for h in hits}
    total: Line | None = None
    end = first
    page_seen = lines[first].page
    k = first
    block_skip: set[int] = set()
    while k < len(lines):
        line = lines[k]
        if _is_source_line(line):
            end = k
            break
        if line.page != page_seen:
            page_seen = line.page
            m = k
            while m < len(lines) and lines[m].page == page_seen and not _is_data(lines[m], n):
                if _is_source_line(lines[m]):
                    break
                m += 1
            block = lines[k:m]
            if block and _is_header_block(spec, block, hit_indices):
                keep_from = m
                if m < len(lines) and lines[m].page == page_seen:
                    anchor_line = lines[m]
                    while keep_from > k and (
                        anchor_line.top - lines[keep_from - 1].top <= HEADER_GAP
                    ):
                        anchor_line = lines[keep_from - 1]
                        keep_from -= 1
                block_skip.update(range(k, keep_from))
        if k in block_skip:
            k += 1
            continue
        if _is_data(line, n):
            norm_label = fold_text(" ".join(w.text for w in line.tokens[:-n]))
            groups.append(_Group(line))
            if spec.ends_with_total and norm_label.startswith("total"):
                total = line
                end = k
                # buscar la línea Fuente que sigue al Total
                look = k + 1
                while look < len(lines) and look <= k + 8 and not _is_source_line(lines[look]):
                    look += 1
                if look >= len(lines) or look > k + 8:
                    raise _drift(source, spec.key, "falta la línea 'Fuente:' tras la fila Total")
                end = look
                break
        else:
            loose.append(line)
        k += 1
    else:
        end = len(lines)
    if end >= len(lines) or not _is_source_line(lines[end]):
        raise _drift(source, spec.key, "la tabla terminó sin línea 'Fuente:'")
    if spec.ends_with_total and total is None:
        raise _drift(source, spec.key, "falta la fila Total", expected="Total", found=None)
    return groups, loose, total, end, header


def _is_centered_layout(groups: Sequence[_Group], loose: Sequence[Line]) -> bool:
    """¿Los números van centrados respecto de la etiqueta (alguna línea a media altura)?"""
    gaps = [abs(group.data.y - line.y) for line in loose for group in groups]
    return bool(gaps) and min(gaps) < CENTERED_LAYOUT_GAP


def _assign_labels(
    groups: list[_Group],
    loose: Sequence[Line],
    spec: TableSpec,
    source: SourceSpec,
) -> None:
    """Une cada línea de etiqueta a su fila numérica.

    En tablas con código y números en la primera línea de la etiqueta, la línea pertenece a la
    fila anterior (banda de fila). En el resto se une a la fila numérica más cercana (empate:
    la siguiente), lo que cubre las etiquetas centradas verticalmente.
    """
    continuation = spec.has_code and not _is_centered_layout(groups, loose)
    for line in loose:
        best: _Group | None = None
        if continuation:
            above = [g for g in groups if g.data.y < line.y]
            best = above[-1] if above else None
            if best is None:
                raise _drift(
                    source,
                    spec.key,
                    "línea de etiqueta antes de la primera fila con código",
                    found=line.norm,
                )
        else:
            best_dist = float("inf")
            for group in groups:
                dist = abs(group.data.y - line.y)
                later = group.data.y > line.y
                if dist < best_dist or (dist == best_dist and later):
                    best, best_dist = group, dist
        if best is not None:
            best.labels.append(line)


def _header_positions(
    spec: TableSpec, header: Sequence[Line], source: SourceSpec
) -> dict[str, float]:
    """Posición x (borde izquierdo) del encabezado de cada columna con palabra clave."""
    positions: dict[str, float] = {}
    for column in spec.columns:
        if column.keyword is None:
            continue
        xs: list[float] = []
        for line in header:
            folded = [fold_text(w.text) for w in line.tokens]
            text = " ".join(folded)
            starts: list[int] = []
            offset = 0
            for token in folded:
                starts.append(offset)
                offset += len(token) + 1
            for match in column.keyword.finditer(text):
                index = bisect_left(starts, match.start() + 1) - 1
                xs.append(line.tokens[max(index, 0)].x0)
        if not xs:
            raise _drift(source, spec.key, "encabezado cambió", expected=column.keyword.pattern)
        positions[column.field] = min(xs)
    return positions


def _column_order(spec: TableSpec, header: Sequence[Line], source: SourceSpec) -> list[ColumnSpec]:
    """Orden de las columnas numéricas (de izquierda a derecha), verificado con el encabezado.

    En tablas ``reorderable`` el orden lo dicta el encabezado. En las demás, el encabezado debe
    traer las columnas con palabra clave en el mismo orden que ``spec.columns``; si no, hay
    deriva de formato (columnas intercambiadas) y se lanza ``SchemaDriftError``.
    """
    positions = _header_positions(spec, header, source)
    if spec.reorderable:
        return sorted(spec.columns, key=lambda c: positions[c.field])
    keyed = [c for c in spec.columns if c.field in positions]
    found = sorted(keyed, key=lambda c: positions[c.field])
    if found != keyed:
        raise _drift(
            source,
            spec.key,
            "las columnas del encabezado están en otro orden",
            expected=", ".join(c.field for c in keyed),
            found=", ".join(c.field for c in found),
        )
    return list(spec.columns)


@dataclass(frozen=True)
class _Geometry:
    """Zona numérica de una tabla: centros de las columnas y borde izquierdo de la zona."""

    centers: tuple[float, ...]
    left: float
    right: float

    def in_zone(self, word: Word) -> bool:
        return word.x1 > self.left

    def column_of(self, word: Word) -> int | None:
        """Índice de la columna a la que pertenece el token, o ``None`` si está fuera."""
        center = (word.x0 + word.x1) / 2
        if center > self.right:
            return None
        bounds = [(a + b) / 2 for a, b in pairwise(self.centers)]
        return bisect_left(bounds, center)


def _geometry(groups: Sequence[_Group], n: int, source: SourceSpec, key: str) -> _Geometry:
    """Estima la zona numérica desde las filas de datos (mediana de los centros por columna)."""
    cells = [g.data.tokens[-n:] for g in groups]
    centers = tuple(median((row[i].x0 + row[i].x1) / 2 for row in cells) for i in range(n))
    if any(a >= b for a, b in pairwise(centers)):
        raise _drift(source, key, "las columnas numéricas se solapan", found=str(centers))
    half_first = (centers[1] - centers[0]) / 2 if n > 1 else SINGLE_COLUMN_HALF_WIDTH
    half_last = (centers[-1] - centers[-2]) / 2 if n > 1 else SINGLE_COLUMN_HALF_WIDTH
    # Borde izquierdo: el x0 mínimo de la primera columna, ignorando filas cuyo "primer
    # número" es en realidad un dígito de la etiqueta (celda vacía).
    firsts = [
        row[0] for row in cells if abs((row[0].x0 + row[0].x1) / 2 - centers[0]) <= half_first
    ]
    left = min(w.x0 for w in firsts) - ZONE_MARGIN
    return _Geometry(centers, left, centers[-1] + half_last)


def _row_text(line: Line) -> str:
    return " ".join(w.text for w in line.tokens)


def _check_loose_lines(
    groups: Sequence[_Group],
    loose: Sequence[Line],
    geometry: _Geometry,
    spec: TableSpec,
    source: SourceSpec,
) -> None:
    """Una línea de etiqueta no puede traer cifras en la zona numérica (celdas faltantes)."""
    for line in loose:
        stray = [w for w in line.tokens if geometry.in_zone(w) and is_number_token(w.text)]
        if stray:
            raise _drift(
                source,
                spec.key,
                "cifras en una línea sin las demás celdas de la fila (celda vacía o desplazada)",
                found=_row_text(line),
            )


def _split_cells(
    line: Line,
    geometry: _Geometry,
    order: Sequence[ColumnSpec],
    spec: TableSpec,
    source: SourceSpec,
) -> tuple[list[Word], dict[str, str]]:
    """Separa la etiqueta de las celdas de una fila de datos, asignando celdas por posición x."""
    label: list[Word] = []
    cells: dict[str, str] = {}
    for word in line.tokens:
        if not geometry.in_zone(word):
            label.append(word)
            continue
        index = geometry.column_of(word)
        if index is None or not is_number_token(word.text):
            raise _drift(
                source,
                spec.key,
                "token fuera de las columnas numéricas",
                found=_row_text(line),
            )
        field_name = order[index].field
        if field_name in cells:
            raise _drift(
                source,
                spec.key,
                f"dos cifras en la misma columna ({field_name})",
                found=_row_text(line),
            )
        cells[field_name] = word.text
    missing = [c.field for c in order if c.field not in cells]
    if missing:
        raise _drift(
            source,
            spec.key,
            "celda vacía o desplazada en la fila",
            expected=", ".join(missing),
            found=_row_text(line),
        )
    return label, cells


def _cell_value(field_name: str, text: str) -> float | None:
    """Valor de una celda; ``-`` es cero en conteos y "sin dato" (``None``) en días."""
    if text.rstrip("*") == "-" and field_name in _DAY_FIELDS:
        return None
    return parse_cl_number(text)


def _build_rows(
    groups: Sequence[_Group],
    spec: TableSpec,
    order: Sequence[ColumnSpec],
    geometry: _Geometry,
    source: SourceSpec,
) -> list[_RawRow]:
    rows: list[_RawRow] = []
    for group in groups:
        data_label, cells = _split_cells(group.data, geometry, order, spec, source)
        code: int | None = None
        if spec.has_code and data_label and data_label[0].text.isdigit():
            code = int(data_label[0].text)
            data_label = data_label[1:]
        label_tokens: list[Word] = []
        for line in sorted([group.data, *group.labels], key=lambda ln: ln.y):
            label_tokens.extend(data_label if line is group.data else line.tokens)
        label = re.sub(r"\s+", " ", " ".join(w.text for w in label_tokens)).strip()
        if spec.has_code and (not label or label[0].islower() or label[0].isdigit()):
            raise _drift(
                source,
                spec.key,
                "etiqueta mal formada (vacía o empieza con minúscula/dígito); "
                "probable línea de etiqueta asignada a la fila equivocada",
                found=f"código {code}: {label!r}",
            )
        values: dict[str, float] = {}
        for column in order:
            value = _cell_value(column.field, cells[column.field])
            if value is not None:
                values[column.field] = value
        rows.append(_RawRow(label, code, values))
    return rows


def _parse_date(text: str) -> date:
    day, month, year = (int(p) for p in text.split("/"))
    return date(year, month, day)


def _read_source_line(
    lines: Sequence[Line], end: int, source: SourceSpec, key: str
) -> tuple[date, date | None]:
    text = " ".join(line.norm for line in lines[end : end + 3])
    cutoff = _CUTOFF.search(text)
    if cutoff is None:
        raise _drift(source, key, "no se encontró la fecha de corte en la línea 'Fuente:'")
    extraction = _EXTRACTION.search(text)
    return (
        _parse_date(cutoff.group(1)),
        _parse_date(extraction.group(1)) if extraction else None,
    )


@dataclass(frozen=True)
class _Ctx:
    source: SourceSpec
    key: str
    label: str
    page: int
    cutoff: date
    extracted_at: date | None


def _record(ctx: _Ctx, **kwargs: object) -> WaitlistRecord:
    return WaitlistRecord.model_validate(
        {
            "period": ctx.cutoff,
            "extracted_at": ctx.extracted_at,
            "source_id": ctx.source.source_id,
            "source_table": ctx.key,
            "source_table_label": ctx.label,
            "source_page": ctx.page,
            "ges_status": GesStatus.NON_GES,
            "count_unit": CountUnit.REFERRALS,
            **kwargs,
        }
    )


def _wait_kwargs(values: Mapping[str, float], basis: WaitBasis) -> dict[str, object]:
    """Campos de espera de tablas con columnas de días.

    Sin registros, o con ``-`` en la celda, no hay dato: promedio y mediana quedan en ``None``
    (nunca cero, para que un promedio ponderado posterior no trate "sin dato" como 0 días).
    """
    empty = values["waiting_count"] == 0
    return {
        "mean_wait_days": None if empty else values.get("mean_wait_days"),
        "median_wait_days": None if empty else values.get("median_wait_days"),
        "wait_basis": basis,
    }


_T9_ROWS: Mapping[str, tuple[CareType, CareSubtype | None]] = MappingProxyType(
    {
        "cne total": (CareType.CONSULTATION, None),
        "cne medica": (CareType.CONSULTATION, CareSubtype.MEDICAL),
        "cne odontologica": (CareType.CONSULTATION, CareSubtype.DENTAL),
        "iq total": (CareType.SURGERY, None),
        "iq mayores": (CareType.SURGERY, CareSubtype.MAJOR),
        "iq menores": (CareType.SURGERY, CareSubtype.MINOR),
    }
)


def _build_t9(ctx: _Ctx, rows: Sequence[_RawRow]) -> tuple[list[WaitlistRecord], dict[str, float]]:
    records: list[WaitlistRecord] = []
    totals: dict[str, float] = {}
    seen: set[str] = set()
    for row in rows:
        key = fold_text(row.label)
        if key not in _T9_ROWS:
            raise _drift(
                ctx.source,
                ctx.key,
                "fila desconocida",
                expected=", ".join(_T9_ROWS),
                found=row.label,
            )
        seen.add(key)
        care_type, subtype = _T9_ROWS[key]
        if subtype is None:
            prefix = key.split()[0]
            totals[f"{prefix}_registros"] = row.values["waiting_count"]
            totals[f"{prefix}_personas"] = row.values["persons_count"]
            continue
        records.append(
            _record(
                ctx,
                grain=Grain.NATIONAL,
                care_type=care_type,
                care_subtype=subtype,
                waiting_count=round(row.values["waiting_count"]),
                persons_count=round(row.values["persons_count"]),
            )
        )
    missing = sorted(set(_T9_ROWS) - seen)
    if missing:
        raise _drift(ctx.source, ctx.key, "faltan filas", expected=", ".join(missing))
    return records, totals


def _service_fields(ctx: _Ctx, label: str) -> dict[str, object]:
    try:
        code, name = resolve_health_service(label)
    except UnknownHealthServiceError:
        raise _drift(ctx.source, ctx.key, "servicio de salud desconocido", found=label) from None
    if code is None and "HOSPITAL DIGITAL" in label.upper():
        name = HOSPITAL_DIGITAL_NAME
    return {"health_service_code": code, "health_service": name}


def _build_service_table(
    ctx: _Ctx, rows: Sequence[_RawRow], total: _RawRow, care_type: CareType
) -> tuple[list[WaitlistRecord], dict[str, float]]:
    def fields(row: _RawRow) -> dict[str, object]:
        out: dict[str, object] = {
            "care_type": care_type,
            "waiting_count": round(row.values["waiting_count"]),
            "persons_count": round(row.values["persons_count"]),
        }
        out.update(_wait_kwargs(row.values, WaitBasis.SINCE_REFERRAL))
        return out

    records = [
        _record(ctx, grain=Grain.HEALTH_SERVICE, **_service_fields(ctx, row.label), **fields(row))
        for row in rows
    ]
    records.append(_record(ctx, grain=Grain.NATIONAL, **fields(total)))
    return records, dict(total.values)


def _build_specialty_table(
    ctx: _Ctx,
    rows: Sequence[_RawRow],
    total: _RawRow,
    care_type: CareType,
    subtype: CareSubtype | None,
) -> tuple[list[WaitlistRecord], dict[str, float]]:
    records = [
        _record(
            ctx,
            grain=Grain.SPECIALTY,
            specialty=normalize_specialty(row.label),
            specialty_raw=row.label,
            care_type=care_type,
            care_subtype=subtype,
            waiting_count=round(row.values["waiting_count"]),
            persons_count=(
                round(row.values["persons_count"]) if "persons_count" in row.values else None
            ),
        )
        for row in rows
    ]
    return records, dict(total.values)


def _build_t6(
    ctx: _Ctx, rows: Sequence[_RawRow], total: _RawRow
) -> tuple[list[WaitlistRecord], dict[str, float]]:
    records = [
        _record(
            ctx,
            grain=Grain.HEALTH_SERVICE,
            ges_status=GesStatus.GES,
            care_type=CareType.UNSPECIFIED,
            count_unit=CountUnit.GUARANTEES,
            waiting_count=round(row.values["waiting_count"]),
            **_service_fields(ctx, row.label),
        )
        for row in rows
    ]
    return records, {"waiting_count": total.values["waiting_count"]}


def _build_t5(
    ctx: _Ctx, rows: Sequence[_RawRow], total: _RawRow
) -> tuple[list[WaitlistRecord], dict[str, float]]:
    def fields(row: _RawRow) -> dict[str, object]:
        out: dict[str, object] = {
            "ges_status": GesStatus.GES,
            "care_type": CareType.UNSPECIFIED,
            "count_unit": CountUnit.GUARANTEES,
            "waiting_count": round(row.values["waiting_count"]),
        }
        out.update(_wait_kwargs(row.values, WaitBasis.DELAY_PAST_GUARANTEE))
        return out

    records: list[WaitlistRecord] = []
    for row in rows:
        if row.code is None:
            raise _drift(ctx.source, ctx.key, "fila sin código de problema GES", found=row.label)
        records.append(
            _record(
                ctx,
                grain=Grain.GES_PROBLEM,
                ges_problem_code=row.code,
                ges_problem=row.label,
                **fields(row),
            )
        )
    records.append(_record(ctx, grain=Grain.NATIONAL, **fields(total)))
    return records, dict(total.values)


def _inconsistent(ctx: _Ctx, row: _RawRow, detail: str) -> DataValidationError:
    name = f"código {row.code} {row.label}" if row.code is not None else row.label
    return DataValidationError(ctx.source.source_id, ctx.key, f"fila {name!r}: {detail}")


def _check_row_consistency(ctx: _Ctx, rows: Sequence[_RawRow]) -> None:
    """Chequeos por fila con columnas que luego se descartan; detectan celdas corridas.

    - Tabla 5: la suma de los seis tramos de retraso es igual al total.
    - Tabla 6: femenino + masculino + no definido es igual al total.
    - Tablas por servicio: ``razón`` coincide con registros/personas (±0,01) si hay personas.
    """
    for row in rows:
        values = row.values
        if ctx.key == "ges_delayed_by_problem":
            buckets = sum(values[f"bucket{i}"] for i in range(1, 7))
            if buckets != values["waiting_count"]:
                raise _inconsistent(
                    ctx,
                    row,
                    f"los tramos suman {buckets:.0f} y el total publicado es "
                    f"{values['waiting_count']:.0f}",
                )
        elif ctx.key == "ges_delayed_by_service":
            by_sex = values["female"] + values["male"] + values["undefined"]
            if by_sex != values["waiting_count"]:
                raise _inconsistent(
                    ctx,
                    row,
                    f"femenino+masculino+no definido suman {by_sex:.0f} y el total publicado "
                    f"es {values['waiting_count']:.0f}",
                )
        elif ctx.key in ("cne_by_service", "iq_by_service") and values["persons_count"] > 0:
            expected = values["waiting_count"] / values["persons_count"]
            if abs(values["ratio"] - expected) > RATIO_TOLERANCE:
                raise _inconsistent(
                    ctx,
                    row,
                    f"razón publicada {values['ratio']} distinta de registros/personas "
                    f"= {expected:.3f}",
                )


_Builder = Callable[
    [_Ctx, Sequence[_RawRow], _RawRow | None], tuple[list[WaitlistRecord], dict[str, float]]
]


def _dispatch(
    ctx: _Ctx, rows: Sequence[_RawRow], total: _RawRow | None
) -> tuple[list[WaitlistRecord], dict[str, float]]:
    key = ctx.key
    if key == "noges_national_by_subtype":
        return _build_t9(ctx, rows)
    if total is None:
        raise _drift(ctx.source, key, "falta la fila Total", expected="Total", found=None)
    if key == "cne_by_service":
        return _build_service_table(ctx, rows, total, CareType.CONSULTATION)
    if key == "iq_by_service":
        return _build_service_table(ctx, rows, total, CareType.SURGERY)
    if key == "cne_medical_by_specialty":
        return _build_specialty_table(ctx, rows, total, CareType.CONSULTATION, CareSubtype.MEDICAL)
    if key == "cne_dental_by_specialty":
        return _build_specialty_table(ctx, rows, total, CareType.CONSULTATION, CareSubtype.DENTAL)
    if key == "iq_by_specialty":
        return _build_specialty_table(ctx, rows, total, CareType.SURGERY, None)
    if key == "ges_delayed_by_service":
        return _build_t6(ctx, rows, total)
    if key == "ges_delayed_by_problem":
        return _build_t5(ctx, rows, total)
    raise KeyError(key)


def _parse_table(lines: Sequence[Line], spec: TableSpec, source: SourceSpec) -> TableResult:
    hits = _find_hits(lines, spec)
    if not hits:
        raise _drift(
            source,
            spec.key,
            "no se encontró la tabla (ancla ausente)",
            expected=spec.anchor.pattern,
        )
    groups, loose, total_line, end, header = _walk(lines, spec, hits, source)
    late = [h for h in hits if h.index > end]
    if late:
        raise _drift(
            source,
            spec.key,
            "ancla duplicada: el título aparece otra vez en otra parte del documento",
            found=hits[0].label,
        )
    order = _column_order(spec, header, source)
    geometry = _geometry(groups, len(spec.columns), source, spec.key)
    _check_loose_lines(groups, loose, geometry, spec, source)
    _assign_labels(groups, loose, spec, source)
    raw = _build_rows(groups, spec, order, geometry, source)
    total_row: _RawRow | None = None
    if total_line is not None:
        total_row = next(r for g, r in zip(groups, raw, strict=True) if g.data is total_line)
        raw = [r for r in raw if r is not total_row]
    cutoff, extracted = _read_source_line(lines, end, source, spec.key)
    if source.period is not None and cutoff != source.period:
        raise _drift(
            source,
            spec.key,
            "el corte no coincide con el período de la fuente",
            expected=source.period.isoformat(),
            found=cutoff.isoformat(),
        )
    pages = tuple(sorted({lines[i].page for i in range(hits[0].index, end + 1)}))
    ctx = _Ctx(source, spec.key, hits[0].label, pages[0], cutoff, extracted)
    _check_row_consistency(ctx, raw if total_row is None else [*raw, total_row])
    records, totals = _dispatch(ctx, raw, total_row)
    return TableResult(spec.key, hits[0].label, pages, records, totals, cutoff, extracted)


def parse_glosa06(pages: Sequence[PageWords], source: SourceSpec) -> list[TableResult]:
    """Parsea las tablas declaradas en ``source.tables`` desde las palabras de las páginas."""
    lines = build_lines(pages)
    return [_parse_table(lines, GLOSA06_TABLES[key], source) for key in source.tables]


def parse_glosa06_pdf(path: Path, source: SourceSpec) -> list[TableResult]:
    """Lee un PDF de la Glosa 06 y parsea sus tablas."""
    return parse_glosa06(read_pdf_words(path), source)
