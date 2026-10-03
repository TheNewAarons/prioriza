"""Regresiones de la revisión de ingestion (hallazgos A1-A3, M1) sobre la Glosa 06.

Se ejecutan sobre los volcados de palabras grabados (sin red). Las mutaciones se hacen en
memoria y reproducen fallas de formato que el parser debe detectar, no absorber.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest
from ingestion.errors import DataValidationError, SchemaDriftError
from ingestion.parsers.glosa06 import TableResult, parse_glosa06
from ingestion.pdf_words import PageWords, Word
from ingestion.sources import get_source
from ingestion.validate import validate_waitlist
from shared.schemas import Grain, WaitlistRecord

QUARTERS = ["glosa06_2025q3", "glosa06_2025q4", "glosa06_2026q1"]
Q1 = "glosa06_2026q1"
Results = dict[str, dict[str, TableResult]]
WordsFn = Callable[[list[Word]], list[Word]]

T5_PAGE = 16  # Tabla 5 (GES retrasadas por problema), I-2026
T6_PAGE = 19  # Tabla 6 (GES retrasadas por servicio, con sexo), I-2026
T12_PAGE = 26  # Tabla 12 (CNE por servicio), I-2026


# --- utilidades -------------------------------------------------------------------------


def _problem(results: Results, quarter: str, code: int) -> WaitlistRecord:
    (row,) = [
        r for r in results[quarter]["ges_delayed_by_problem"].records if r.ges_problem_code == code
    ]
    return row


def _mutate(pages: list[PageWords], number: int, fn: WordsFn) -> list[PageWords]:
    """Aplica ``fn`` a las palabras de una página y devuelve una copia de la lista."""
    return [
        dataclasses.replace(p, words=tuple(fn(list(p.words)))) if p.page_number == number else p
        for p in pages
    ]


def _line(words: list[Word], anchor: Word) -> list[Word]:
    """Palabras de la misma línea que ``anchor``, de izquierda a derecha."""
    return sorted((w for w in words if abs(w.top - anchor.top) < 3.0), key=lambda w: w.x0)


def _row_anchor(words: list[Word], text: str, *, x_max: float, top: float | None = None) -> Word:
    """Palabra de la columna izquierda (código o nombre) que identifica una fila."""
    found = [
        w
        for w in words
        if w.text == text and w.x0 < x_max and (top is None or abs(w.top - top) < 3.0)
    ]
    assert len(found) == 1, f"ancla {text!r} no es única: {len(found)}"
    return found[0]


def _replace_word(words: list[Word], victim: Word, new_text: str) -> list[Word]:
    return [dataclasses.replace(w, text=new_text) if w is victim else w for w in words]


def _drop_word(words: list[Word], victim: Word) -> list[Word]:
    return [w for w in words if w is not victim]


def _swap_positions(words: list[Word], first: str, second: str) -> list[Word]:
    """Intercambia las posiciones x de dos encabezados (el texto se queda donde está)."""
    (a,) = [w for w in words if w.text == first]
    (b,) = [w for w in words if w.text == second]
    out = []
    for w in words:
        if w is a:
            out.append(dataclasses.replace(w, x0=b.x0, x1=b.x1))
        elif w is b:
            out.append(dataclasses.replace(w, x0=a.x0, x1=a.x1))
        else:
            out.append(w)
    return out


def _parse_and_validate(pages: list[PageWords], source_id: str = Q1) -> None:
    source = get_source(source_id)
    validate_waitlist(parse_glosa06(pages, source), source)


# --- F1 (A1): etiquetas multilínea de la Tabla 5 -----------------------------------------


def test_q1_t5_multiline_labels_are_attached_to_their_own_code(glosa_results: Results) -> None:
    """Códigos 12, 13, 53, 54, 89 y 90 de I-2026: la etiqueta continúa la fila anterior."""
    label = {code: _problem(glosa_results, Q1, code).ges_problem for code in (12, 13, 53, 54, 88)}
    assert label[12] == (
        "Endoprótesis total de cadera en personas de 65 años y más "
        "con artrosis de cadera con limitación funcional severa"
    )
    assert label[13] == "Fisura labiopalatina"
    assert label[53] == (
        "Consumo perjudicial o dependencia de riesgo bajo a moderado de alcohol "
        "y drogas en personas menores de 20 años"
    )
    assert label[54] == "Analgesia del parto"
    assert label[88] is not None and label[88].endswith("cirrosis hepática")

    label89 = _problem(glosa_results, Q1, 89).ges_problem
    assert label89 == (
        "Tratamiento hospitalario para personas menores de 15 años con depresión grave "
        "refractaria o psicótica con riesgo suicida"
    )
    label90 = _problem(glosa_results, Q1, 90).ges_problem
    assert label90 == "Cesación del consumo de tabaco en personas de 25 años y más"


@pytest.mark.parametrize("quarter", QUARTERS)
def test_t5_labels_never_start_with_lowercase_or_digit(
    glosa_results: Results, quarter: str
) -> None:
    rows = [
        r
        for r in glosa_results[quarter]["ges_delayed_by_problem"].records
        if r.grain is Grain.GES_PROBLEM
    ]
    assert len(rows) >= 87
    for r in rows:
        assert r.ges_problem, f"código {r.ges_problem_code} sin etiqueta"
        first = r.ges_problem[0]
        assert first.isalpha() and first.isupper(), (r.ges_problem_code, r.ges_problem)


@pytest.mark.parametrize(
    ("original", "broken"),
    [("Fisura", "fisura"), ("Fisura", "7Fisura")],
    ids=["lowercase_start", "digit_start"],
)
def test_t5_label_starting_with_lowercase_or_digit_is_schema_drift(
    glosa_pages: dict[str, list[PageWords]], original: str, broken: str
) -> None:
    def fn(words: list[Word]) -> list[Word]:
        (victim,) = [w for w in words if w.text == original]
        return _replace_word(words, victim, broken)

    pages = _mutate(list(glosa_pages[Q1]), T5_PAGE, fn)
    with pytest.raises(SchemaDriftError) as excinfo:
        _parse_and_validate(pages)
    assert "ges_delayed_by_problem" in str(excinfo.value)


# --- F2 (A2+A3): asignación de columnas por posición x ----------------------------------


@pytest.mark.parametrize(
    ("page", "first", "second", "table"),
    [
        (T12_PAGE, "Promedio", "Mediana", "cne_by_service"),
        (T5_PAGE, "Promedio", "Mediana", "ges_delayed_by_problem"),
        (T6_PAGE, "Femenino", "Masculino", "ges_delayed_by_service"),
    ],
    ids=["t12_mean_median", "t5_mean_median", "t6_female_male"],
)
def test_swapped_header_columns_are_schema_drift(
    glosa_pages: dict[str, list[PageWords]], page: int, first: str, second: str, table: str
) -> None:
    pages = _mutate(list(glosa_pages[Q1]), page, lambda ws: _swap_positions(ws, first, second))
    with pytest.raises(SchemaDriftError) as excinfo:
        _parse_and_validate(pages)
    assert table in str(excinfo.value)
    assert excinfo.value.source_id == Q1


@pytest.mark.parametrize("which", ["first_bucket", "median"])
def test_empty_cell_in_row_whose_label_ends_in_a_digit_is_schema_drift(
    glosa_pages: dict[str, list[PageWords]], which: str
) -> None:
    """Código 7 'Diabetes mellitus tipo 2': el '2' de la etiqueta no puede pasar por dato."""

    def fn(words: list[Word]) -> list[Word]:
        seven = _row_anchor(words, "7", x_max=80)
        cells = [w for w in _line(words, seven) if w.x0 > 300]
        victim = cells[0] if which == "first_bucket" else cells[-1]
        return _drop_word(words, victim)

    pages = _mutate(list(glosa_pages[Q1]), T5_PAGE, fn)
    with pytest.raises(SchemaDriftError) as excinfo:
        _parse_and_validate(pages)
    assert "ges_delayed_by_problem" in str(excinfo.value)


def test_untouched_t5_row_7_keeps_digit_in_label(glosa_results: Results) -> None:
    """Control: sin mutación, 'tipo 2' sigue siendo etiqueta y las cifras son las publicadas."""
    row = _problem(glosa_results, Q1, 7)
    assert row.ges_problem == "Diabetes mellitus tipo 2"
    assert (row.waiting_count, row.mean_wait_days, row.median_wait_days) == (6853, 192.0, 111.0)


# --- F3 (A3): consistencia de columnas hoy descartadas --------------------------------


def test_t5_buckets_that_do_not_add_up_to_the_row_total_are_rejected(
    glosa_pages: dict[str, list[PageWords]],
) -> None:
    def fn(words: list[Word]) -> list[Word]:
        one = _row_anchor(words, "1", x_max=80, top=165)
        victim = next(w for w in _line(words, one) if w.text == "212")
        return _replace_word(words, victim, "213")  # 213+262+190+368+540+341 = 1.914 != 1.913

    pages = _mutate(list(glosa_pages[Q1]), T5_PAGE, fn)
    with pytest.raises(DataValidationError) as excinfo:
        _parse_and_validate(pages)
    message = str(excinfo.value)
    assert Q1 in message
    assert "ges_delayed_by_problem" in message


def test_t6_sexes_that_do_not_add_up_to_the_row_total_are_rejected(
    glosa_pages: dict[str, list[PageWords]],
) -> None:
    def fn(words: list[Word]) -> list[Word]:
        row = next(w for w in words if w.text == "Tarapacá")
        victim = next(w for w in _line(words, row) if w.text == "494")
        return _replace_word(words, victim, "495")  # 495+357+0 = 852 != 851

    pages = _mutate(list(glosa_pages[Q1]), T6_PAGE, fn)
    with pytest.raises(DataValidationError) as excinfo:
        _parse_and_validate(pages)
    message = str(excinfo.value)
    assert Q1 in message
    assert "ges_delayed_by_service" in message


def test_service_ratio_inconsistent_with_records_over_persons_is_rejected(
    glosa_pages: dict[str, list[PageWords]],
) -> None:
    def fn(words: list[Word]) -> list[Word]:
        row = next(w for w in words if w.text == "Arica")
        victim = next(w for w in _line(words, row) if w.text == "1,16")
        return _replace_word(words, victim, "1,60")  # 31.098 / 26.849 = 1,158

    pages = _mutate(list(glosa_pages[Q1]), T12_PAGE, fn)
    with pytest.raises(DataValidationError) as excinfo:
        _parse_and_validate(pages)
    message = str(excinfo.value)
    assert Q1 in message
    assert "cne_by_service" in message


@pytest.mark.parametrize("quarter", QUARTERS)
def test_real_data_passes_the_consistency_checks(
    glosa_pages: dict[str, list[PageWords]], quarter: str
) -> None:
    """Control: los PDF publicados cumplen todas las identidades (sin falsos positivos)."""
    _parse_and_validate(list(glosa_pages[quarter]), quarter)


# --- F4 (M1): "-" en días es dato ausente, no cero ---------------------------------------


def test_q1_t5_problem_54_dashes_mean_no_data_not_zero_days(glosa_results: Results) -> None:
    row = _problem(glosa_results, Q1, 54)  # Analgesia del parto: "- - - - ..."
    assert row.waiting_count == 0
    assert row.mean_wait_days is None
    assert row.median_wait_days is None


def test_q1_t6_arica_zero_guarantees_has_no_wait_stats(glosa_results: Results) -> None:
    (arica,) = [
        r for r in glosa_results[Q1]["ges_delayed_by_service"].records if r.health_service_code == 1
    ]
    assert arica.waiting_count == 0
    assert arica.mean_wait_days is None
    assert arica.median_wait_days is None


@pytest.mark.parametrize("quarter", QUARTERS)
def test_no_record_with_zero_waiting_reports_wait_days(
    glosa_results: Results, quarter: str
) -> None:
    zero_rows = [
        r
        for result in glosa_results[quarter].values()
        for r in result.records
        if not r.waiting_count
    ]
    assert zero_rows, "debe haber filas con 0 (p. ej. código 46 de la Tabla 5)"
    for r in zero_rows:
        assert r.mean_wait_days is None and r.median_wait_days is None, r.key()


@pytest.mark.parametrize("quarter", QUARTERS)
def test_rows_with_waiting_keep_their_published_wait_days(
    glosa_results: Results, quarter: str
) -> None:
    """Control del cambio: solo las filas con 0 pierden los días; el resto los conserva."""
    rows = [
        r
        for r in glosa_results[quarter]["ges_delayed_by_problem"].records
        if r.grain is Grain.GES_PROBLEM and r.waiting_count > 0
    ]
    assert rows
    assert all(r.mean_wait_days is not None and r.median_wait_days is not None for r in rows)
