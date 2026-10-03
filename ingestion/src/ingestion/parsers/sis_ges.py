"""Parser del XLSX de la Superintendencia de Salud: casos GES acumulados por problema y aseguradora.

Cada hoja ``Año <AAAA>`` trae pares FONASA/ISAPRE de "Número de casos acumulados Jul-2005 a
<Mes>-<AAAA>" y un par final "Ingresos entre Ene y <Mes> <AAAA>". La fila de encabezado se busca
por el texto ``PROBLEMA DE SALUD`` en la columna B (su índice varía entre archivos).
"""

import calendar
import re
from datetime import date
from pathlib import Path

from shared.schemas import GesCaseRecord, Insurer

from ingestion.errors import SchemaDriftError
from ingestion.normalize import fold_text
from ingestion.sources import SourceSpec

_MONTHS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}
_TABLE = "ges_cases"
_MAX_HEADER_SEARCH = 30
_LAST_COLUMN = "L"
_CUMULATIVE = re.compile(r"casos acumulados.*?a\s+([a-z]{3,4})[-\s]*(\d{4})")
_YTD = re.compile(r"ingresos entre.*?ene\s+y\s+([a-z]{3,4})\s+(\d{4})")


def _month_end(month_text: str, year: int) -> date | None:
    month = _MONTHS.get(month_text)
    if month is None:
        return None
    return date(year, month, calendar.monthrange(year, month)[1])


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return int(float(text))


def _cell(row: tuple[object, ...], index: int) -> object:
    return row[index] if index < len(row) else None


def _parse_sheet(
    rows: list[tuple[object, ...]],
    sheet: str,
    source: SourceSpec,
    records: list[GesCaseRecord],
    totals: dict[tuple[date, Insurer], int],
) -> None:
    header_idx = next(
        (
            i
            for i, row in enumerate(rows[:_MAX_HEADER_SEARCH])
            if fold_text(str(_cell(row, 1) or "")) == "problema de salud"
        ),
        None,
    )
    if header_idx is None:
        raise SchemaDriftError(
            source.source_id,
            _TABLE,
            f"hoja {sheet!r}: no se encontró el encabezado",
            expected="PROBLEMA DE SALUD (columna B)",
            found=None,
        )
    header, insurers = rows[header_idx], rows[header_idx + 1]
    data_start = header_idx + 3  # tras la fila de aseguradoras y la de fechas de corte

    pairs: list[tuple[int, date]] = []
    ytd_period: date | None = None
    ytd_col: int | None = None
    for col in range(2, len(header)):
        text = fold_text(str(header[col] or ""))
        cumulative = _CUMULATIVE.search(text)
        if cumulative:
            period = _month_end(cumulative.group(1), int(cumulative.group(2)))
            if period is not None:
                pairs.append((col, period))
            continue
        ytd = _YTD.search(text)
        if ytd:
            ytd_period = _month_end(ytd.group(1), int(ytd.group(2)))
            ytd_col = col
    if not pairs:
        raise SchemaDriftError(
            source.source_id,
            _TABLE,
            f"hoja {sheet!r}: sin columnas de casos acumulados",
            expected="Número de casos acumulados Jul-2005 a <Mes>-<Año>",
            found=None,
        )
    for col, _ in pairs:
        pair_labels = (
            fold_text(str(_cell(insurers, col) or "")),
            fold_text(str(_cell(insurers, col + 1) or "")),
        )
        if pair_labels != ("fonasa", "isapre"):
            raise SchemaDriftError(
                source.source_id,
                _TABLE,
                f"hoja {sheet!r}: columnas de aseguradora inesperadas",
                expected="FONASA, ISAPRE",
                found=", ".join(pair_labels),
            )

    for row in rows[data_start:]:
        name = str(_cell(row, 1) or "").strip()
        if not name:
            continue
        if fold_text(name) == "total general":
            for col, period in pairs:
                for offset, insurer in enumerate((Insurer.FONASA, Insurer.ISAPRE)):
                    value = _to_int(_cell(row, col + offset))
                    if value is not None:
                        totals[(period, insurer)] = value
            continue
        code_text = str(_cell(row, 0) or "").strip()
        if not code_text.isdigit():
            continue
        code = int(code_text)
        for col, period in pairs:
            for offset, insurer in enumerate((Insurer.FONASA, Insurer.ISAPRE)):
                value = _to_int(_cell(row, col + offset))
                if value is None:
                    continue
                ytd_value = None
                if ytd_col is not None and period == ytd_period:
                    ytd_value = _to_int(_cell(row, ytd_col + offset))
                records.append(
                    GesCaseRecord(
                        period=period,
                        ges_problem_code=code,
                        ges_problem=re.sub(r"\s+", " ", name),
                        insurer=insurer,
                        cumulative_cases=value,
                        ytd_new_cases=ytd_value,
                        source_id=source.source_id,
                        source_sheet=sheet,
                    )
                )


def parse_sis_ges_xlsx(
    path: Path, source: SourceSpec
) -> tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]]:
    """Lee las hojas del año del corte y del anterior.

    Devuelve los registros y los totales publicados (``TOTAL GENERAL``) por período y
    aseguradora, para validarlos.
    """
    import fastexcel

    if source.period is None:
        raise ValueError(f"la fuente {source.source_id} no define period")
    reader = fastexcel.read_excel(str(path))
    records: list[GesCaseRecord] = []
    totals: dict[tuple[date, Insurer], int] = {}
    for year in (source.period.year - 1, source.period.year):
        sheet = f"Año {year}"
        if sheet not in reader.sheet_names:
            raise SchemaDriftError(
                source.source_id,
                _TABLE,
                "falta una hoja",
                expected=sheet,
                found=", ".join(reader.sheet_names[:6]),
            )
        frame = reader.load_sheet_by_name(
            sheet, header_row=None, use_columns=f"A:{_LAST_COLUMN}"
        ).to_polars()
        _parse_sheet(frame.rows(), sheet, source, records, totals)
    return records, totals
