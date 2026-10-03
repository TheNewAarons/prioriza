"""Tests de las fixtures grabadas, la lectura de PDF, la normalización y la salida a parquet."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from ingestion.errors import SchemaDriftError
from ingestion.normalize import SPECIALTY_ALIASES, normalize_label, to_frame
from ingestion.output import write_processed
from ingestion.parsers.glosa06 import TableResult, parse_glosa06, parse_glosa06_pdf
from ingestion.pdf_words import PageWords, dump_words_json, load_words_json, read_pdf_words
from ingestion.sources import SOURCES, get_source
from shared.schemas import WAITLIST_POLARS_SCHEMA, Grain

QUARTERS = ["glosa06_2025q3", "glosa06_2025q4", "glosa06_2026q1"]
MAX_FIXTURES_BYTES = 2 * 1024 * 1024

Results = dict[str, dict[str, TableResult]]


# --- fixtures grabadas ----------------------------------------------------------------------


def test_fixtures_total_size_is_reasonable(fixtures_dir: Path) -> None:
    total = sum(p.stat().st_size for p in fixtures_dir.rglob("*") if p.is_file())
    assert total < MAX_FIXTURES_BYTES, total


def test_manifest_lists_existing_fixtures_with_matching_hashes(fixtures_dir: Path) -> None:
    manifest = json.loads((fixtures_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    entries = manifest["fixtures"]
    assert entries
    for name, entry in entries.items():
        target = fixtures_dir / name
        assert target.exists(), name
        assert "fuente" in entry["note"].lower()
        assert entry["url"].startswith("https://")
        if "sha256" in entry:
            assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"], name
        if "original_sha256" in entry:
            assert re.fullmatch(r"[0-9a-f]{64}", entry["original_sha256"])
    for quarter in QUARTERS:
        spec = get_source(quarter)
        assert entries[f"glosa06/{quarter}/"]["original_sha256"] == spec.expected_sha256
        assert entries[f"glosa06/{quarter}/"]["url"] == spec.url
    spec = get_source("sis_ges_cases_2026q1")
    assert entries["sis_ges/sis_ges_cases_mini.xlsx"]["original_sha256"] == spec.expected_sha256


@pytest.mark.parametrize("quarter", QUARTERS)
def test_word_dumps_follow_the_documented_format(fixtures_dir: Path, quarter: str) -> None:
    files = sorted((fixtures_dir / "glosa06" / quarter).glob("p*.words.json"))
    assert len(files) >= 11
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == {"source_id", "page_number", "width", "height", "words"}
        assert data["source_id"] == quarter
        assert path.name == f"p{data['page_number']:02d}.words.json"
        assert data["width"] in (612.0, 792.0)
        assert data["words"]
        for word in data["words"]:
            assert set(word) == {"text", "x0", "x1", "top", "bottom"}
            for key in ("x0", "x1", "top", "bottom"):
                assert round(word[key], 2) == word[key]
            assert word["x0"] <= word["x1"] and word["top"] <= word["bottom"]


def test_word_dumps_keep_only_table_regions_not_narrative(
    glosa_pages: dict[str, list[PageWords]],
) -> None:
    """Se descarta la prosa: cada página tiene cabecera, tabla y (a lo sumo) un pie corto."""
    for pages in glosa_pages.values():
        for page in pages:
            assert len(page.words) < 700
            text = " ".join(w.text for w in page.words).lower()
            assert "ministerio de salud" in text  # cabecera corrida conservada


def test_fixtures_contain_no_personal_identifiers(fixtures_dir: Path) -> None:
    rut = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
    for path in fixtures_dir.rglob("*"):
        if path.suffix in {".json", ".csv"}:
            assert not rut.search(path.read_text(encoding="utf-8")), path
    csv_text = (fixtures_dir / "minsal_establishments" / "establishments_sample.csv").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"\b[\w.+-]+@[\w-]+\.\w+\b", csv_text), "sin correos"


def test_make_fixtures_script_is_independent_of_ingestion(fixtures_dir: Path) -> None:
    source = (fixtures_dir / "make_fixtures.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(ingestion|shared)\b", source, re.MULTILINE)


# --- lectura de palabras ----------------------------------------------------------------------


def test_words_json_roundtrip(tmp_path: Path, glosa_pages: dict[str, list[PageWords]]) -> None:
    page = glosa_pages["glosa06_2026q1"][0]
    target = tmp_path / "p.words.json"
    dump_words_json(page, target)
    assert load_words_json(target) == page
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["page_number"] == page.page_number
    assert len(data["words"]) == len(page.words)


def test_read_pdf_words_on_the_one_page_pdf(
    fixtures_dir: Path, glosa_pages: dict[str, list[PageWords]]
) -> None:
    pdf = fixtures_dir / "glosa06" / "glosa06_2026q1_p26.pdf"
    pages = read_pdf_words(pdf)
    assert len(pages) == 1
    page = pages[0]
    assert page.page_number == 1
    assert (page.width, page.height) == (612.0, 792.0)
    texts = [w.text for w in page.words]
    assert "Tabla" in texts and "Fuente:" in texts

    # cada palabra del volcado JSON de la página 26 está en el PDF (misma posición)
    (dumped,) = [p for p in glosa_pages["glosa06_2026q1"] if p.page_number == 26]
    in_pdf = {(w.text, round(w.x0, 2), round(w.top, 2)) for w in page.words}
    missing = [w for w in dumped.words if (w.text, round(w.x0, 2), round(w.top, 2)) not in in_pdf]
    assert missing == []


def test_read_pdf_words_pages_filter(fixtures_dir: Path) -> None:
    pdf = fixtures_dir / "glosa06" / "glosa06_2026q1_p26.pdf"
    assert len(read_pdf_words(pdf, pages=[1])) == 1
    assert read_pdf_words(pdf, pages=[2]) == []
    assert len(read_pdf_words(pdf, pages=iter([1]))) == 1


def test_pdf_page_and_json_dump_give_the_same_table(
    fixtures_dir: Path, glosa_pages: dict[str, list[PageWords]], glosa_results: Results
) -> None:
    """De punta a punta: la página real del PDF reemplaza al volcado y la tabla no cambia."""
    pdf_page = read_pdf_words(fixtures_dir / "glosa06" / "glosa06_2026q1_p26.pdf")[0]
    pdf_page = dataclasses.replace(pdf_page, page_number=26)
    pages = [pdf_page if p.page_number == 26 else p for p in glosa_pages["glosa06_2026q1"]]
    results = {r.key: r for r in parse_glosa06(pages, get_source("glosa06_2026q1"))}
    assert (
        results["cne_by_service"].records
        == glosa_results["glosa06_2026q1"]["cne_by_service"].records
    )
    assert (
        results["cne_by_service"].totals == glosa_results["glosa06_2026q1"]["cne_by_service"].totals
    )


def test_one_page_pdf_alone_is_incomplete_and_reports_drift(fixtures_dir: Path) -> None:
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_glosa06_pdf(
            fixtures_dir / "glosa06" / "glosa06_2026q1_p26.pdf", get_source("glosa06_2026q1")
        )
    assert "glosa06_2026q1" in str(excinfo.value)


# --- normalización ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Infectología", "INFECTOLOGIA"),
        ("INFECTOLOGÍA", "INFECTOLOGIA"),
        ("  Cirugía   Bucal ", "CIRUGIA BUCAL"),
        ("Medicina Interna", "MEDICINA INTERNA"),
        ("Odontopediatría*", "ODONTOPEDIATRIA"),
    ],
)
def test_normalize_label(raw: str, expected: str) -> None:
    assert normalize_label(raw) == expected


def test_normalize_label_is_idempotent() -> None:
    for raw in ("Infectología Pediátrica", "CIRUGÍA Y TRAUMATOLOGÍA BUCO MAXILOFACIAL", "x  y"):
        once = normalize_label(raw)
        assert normalize_label(once) == once


def test_specialty_aliases_are_normalized_and_map_variants_together() -> None:
    assert SPECIALTY_ALIASES
    for key, value in SPECIALTY_ALIASES.items():
        assert key == normalize_label(key)
        assert value == normalize_label(value)
    values = set(SPECIALTY_ALIASES.values())
    assert "BUCOMAXILOFACIAL" in values or any("MAXILOFACIAL" in v for v in values)


def test_adulta_and_adulto_variants_end_up_with_the_same_specialty(
    glosa_results: Results,
) -> None:
    """Contrato: ADULTA->ADULTO. 'FISIATRIA ADULTO' (III-2025) y 'FISIATRIA ADULTA)' (I-2026)."""

    def fisiatria(quarter: str) -> list[str]:
        rows = glosa_results[quarter]["cne_medical_by_specialty"].records
        return [r.specialty for r in rows if r.specialty and "FISIATRIA" in r.specialty]

    assert sorted(fisiatria("glosa06_2025q3")) == sorted(fisiatria("glosa06_2026q1"))


# --- DataFrames y salida --------------------------------------------------------------------------


def test_to_frame_uses_the_explicit_schema_and_sorts(glosa_results: Results) -> None:
    records = list(glosa_results["glosa06_2026q1"]["cne_by_service"].records)
    shuffled = list(reversed(records))
    sort = ("source_table", "grain", "health_service_code")
    frame = to_frame(shuffled, WAITLIST_POLARS_SCHEMA, sort)
    assert frame.schema == pl.Schema(WAITLIST_POLARS_SCHEMA)
    assert frame.height == 30
    assert frame["grain"].dtype == pl.String
    assert set(frame["grain"]) == {Grain.HEALTH_SERVICE.value, Grain.NATIONAL.value}
    assert frame.equals(to_frame(records, WAITLIST_POLARS_SCHEMA, sort))
    sorted_ = frame.sort(list(sort), nulls_last=True)
    assert frame.equals(sorted_)
    row = frame.filter(pl.col("health_service_code") == 9).row(0, named=True)
    assert row["waiting_count"] == 132021  # M. Norte, I-2026
    assert row["period"] == date(2026, 3, 31)
    assert row["care_type"] == "consultation"


def test_write_processed_writes_parquet_and_sidecar(tmp_path: Path, glosa_results: Results) -> None:
    records = list(glosa_results["glosa06_2025q4"]["iq_by_service"].records)
    frame = to_frame(
        records, WAITLIST_POLARS_SCHEMA, ("source_table", "grain", "health_service_code")
    )
    processed = tmp_path / "processed"
    path = write_processed(
        frame,
        processed_dir=processed,
        source_id="glosa06_2025q4",
        provenance={"raw_sha256": "abc", "url": "https://example.test/x.pdf", "warnings": ["w1"]},
    )
    assert path == processed / "glosa06_2025q4.parquet"
    assert pl.read_parquet(path).equals(frame)
    assert pl.read_parquet(path).schema == pl.Schema(WAITLIST_POLARS_SCHEMA)
    sidecar = json.loads((processed / "glosa06_2025q4.metadata.json").read_text(encoding="utf-8"))
    assert sidecar["raw_sha256"] == "abc"
    assert sidecar["url"] == "https://example.test/x.pdf"
    assert sidecar["warnings"] == ["w1"]
    assert sidecar["rows"] == 30
    assert sidecar["source_id"] == "glosa06_2025q4"
    assert sorted(p.name for p in processed.iterdir()) == [
        "glosa06_2025q4.metadata.json",
        "glosa06_2025q4.parquet",
    ]


def test_registry_sources_match_the_documented_contract() -> None:
    assert list(SOURCES) == [
        "glosa06_2025q3",
        "glosa06_2025q4",
        "glosa06_2026q1",
        "sis_ges_cases_2026q1",
        "minsal_establishments",
    ]
    assert get_source("glosa06_2025q3").period == date(2025, 9, 30)
    assert get_source("glosa06_2025q4").period == date(2025, 12, 31)
    assert get_source("glosa06_2026q1").period == date(2026, 3, 31)
    assert get_source("sis_ges_cases_2026q1").period == date(2026, 3, 31)
    assert get_source("minsal_establishments").period is None
    for quarter in QUARTERS:
        assert len(get_source(quarter).tables) == 8
    with pytest.raises(KeyError, match="glosa06_2025q3"):
        get_source("no_existe")
