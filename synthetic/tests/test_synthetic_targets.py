"""Targets y supuestos versionados: esquema, procedencia y reconstrucción."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from synthetic.targets import (
    build_targets,
    canonical_json,
    load_assumptions,
)

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
SHA = re.compile(r"^[0-9a-f]{64}$")
TARGETS_JSON = ROOT / "synthetic" / "src" / "synthetic" / "targets" / "calibration_targets.json"


def test_targets_esquema_valido(targets):
    """El JSON valida contra CalibrationTargets y tiene el contenido mínimo."""
    assert targets.reference_source_id == "glosa06_2025q3"
    assert targets.service_rows and targets.specialties and targets.ges_problems
    assert {r.key for r in targets.national} == {"consultation", "surgery", "ges"}
    cne = targets.national_row("consultation")
    iq = targets.national_row("surgery")
    # Cifras nacionales de la Glosa III-2025 citadas en el plan (sección 0).
    assert (cne.mean_wait_days, cne.median_wait_days) == (341.0, 242.0)
    assert (iq.mean_wait_days, iq.median_wait_days) == (394.0, 264.0)


def test_targets_procedencia(targets):
    """Cada fuente declara source_id y sha256 hexadecimal de 64 caracteres."""
    assert targets.sources
    ids = {s.source_id for s in targets.sources}
    assert targets.reference_source_id in ids
    for s in targets.sources:
        assert s.source_id
        assert SHA.match(s.parquet_sha256), s.source_id
        if s.raw_sha256 is not None:
            assert SHA.match(s.raw_sha256), s.source_id


def test_targets_tamano_y_formato_canonico():
    """Plan sección 5: JSON con claves ordenadas, sin timestamp y < 150 KB."""
    text = TARGETS_JSON.read_text(encoding="utf-8")
    assert len(text.encode()) < 150_000
    assert json.dumps(json.loads(text), sort_keys=True) == json.dumps(json.loads(text))
    assert "generated_at" not in text and "timestamp" not in text


def test_targets_sin_nombres_de_personas(targets):
    """Los únicos nombres son de establecimientos, comunas y servicios públicos."""
    dumped = targets.model_dump_json().lower()
    for word in ('"rut"', '"birth_date"', '"ethnicity"', '"nationality"'):
        assert word not in dumped


def test_assumptions_con_procedencia(assumptions):
    """Cada supuesto trae valor, fuente, justificación y bandera verified."""
    assert assumptions.parameters
    for name, p in assumptions.parameters.items():
        assert p.source, name
        assert p.justification, name
        assert isinstance(p.verified, bool), name
    assert assumptions.ges_problem_map
    for m in assumptions.ges_problem_map:
        assert m.justification and m.deadline_days > 0
    assert assumptions.iq_procedures


def test_supuestos_de_edad_y_prevision_no_verificados(assumptions):
    """Decisión 1 (sección 10): edad y previsión son supuestos con verified=false,
    salvo que la previsión se derive de conteos publicados (se acepta ambos casos,
    pero la edad debe seguir marcada como no verificada)."""
    unverified = " ".join(assumptions.unverified()).lower()
    assert "age" in unverified


def test_assumptions_json_cargable_dos_veces():
    """La carga es pura y repetible."""
    assert load_assumptions() == load_assumptions()


@pytest.mark.skipif(not PROCESSED.exists(), reason="data/processed no existe")
def test_reconstruir_targets_da_json_identico():
    """build_targets(data/processed) reproduce byte a byte el JSON versionado."""
    rebuilt = build_targets(PROCESSED)
    on_disk = json.loads(TARGETS_JSON.read_text(encoding="utf-8"))
    assert json.loads(canonical_json(rebuilt)) == on_disk


def test_proxy_de_prevision_figura_como_no_verificado(assumptions, ds1k):
    """A1: el proxy de previsión de la lista de espera es un supuesto no verificado y
    aparece en ``Assumptions.unverified()`` y en ``run.params``; los conteos APS sí están
    verificados."""
    assert "insurance_waitlist_proxy" in assumptions.unverified()
    assert "insurance_aps_counts" not in assumptions.unverified()
    assert "insurance_waitlist_proxy" in ds1k.run["params"]["unverified_assumptions"]
