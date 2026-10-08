"""Corrida sintética de juguete para los tests de noshow (sin red, sin BD, sin ``synthetic``).

Imita el layout de ``prioriza-synth generate``: un directorio con ``manifest.json`` y los parquet
que lee ``noshow.data``. Las inasistencias dependen de la especialidad, la anticipación y una
fragilidad por paciente, de modo que el historial previo tiene señal.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

AS_OF = date(2025, 9, 30)
SPECIALTIES = {
    "cne_medical:cardiologia": ("consultation", -1.4),
    "cne_medical:dermatologia": ("consultation", -1.9),
    "cne_medical:neurologia": ("consultation", -1.6),
    "iq:traumatologia": ("surgery", -2.8),
}


def make_run(
    root: Path,
    n_patients: int = 400,
    seed: int = 0,
    window_days: int = 730,
    mean_appointments: float = 3.0,
) -> Path:
    """Escribe una corrida de juguete en ``root/<run_id>/`` y devuelve ese directorio."""
    rng = np.random.default_rng(seed)
    run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"noshow-test:{seed}:{n_patients}")
    codes = sorted(SPECIALTIES)
    patient_ids = [str(uuid.uuid5(run_id, f"patient:{i}")) for i in range(n_patients)]
    frailty = rng.normal(0.0, 1.0, size=n_patients)
    k = np.maximum(rng.poisson(mean_appointments, size=n_patients), 1)
    pat_idx = np.repeat(np.arange(n_patients), k)
    total = len(pat_idx)
    spec = rng.integers(0, len(codes), size=total)
    lead = rng.integers(7, 91, size=total)
    days_before = rng.integers(1, window_days + 1, size=total)
    base = datetime(AS_OF.year, AS_OF.month, AS_OF.day, 12, tzinfo=UTC)
    z = (
        np.array([SPECIALTIES[codes[s]][1] for s in spec])
        + 0.1 * np.log2(1.0 + lead / 7.0)
        + frailty[pat_idx]
    )
    p = 1.0 / (1.0 + np.exp(-z))
    no_show = rng.random(total) < p
    appt_ids = [str(uuid.uuid5(run_id, f"appointment:{i}")) for i in range(total)]
    appointment = pl.DataFrame(
        {
            "id": appt_ids,
            "run_id": [str(run_id)] * total,
            "patient_id": [patient_ids[i] for i in pat_idx],
            "entry_id": [None] * total,
            "slot_id": [None] * total,
            "origin": ["history"] * total,
            "status": np.where(no_show, "no_show", "attended").tolist(),
            "scheduled_start": [base - timedelta(days=int(d)) for d in days_before],
            "duration_min": [20] * total,
            "lead_days": lead.astype(np.int64),
            "specialty_code": [codes[s] for s in spec],
        },
        schema_overrides={
            "entry_id": pl.String,
            "slot_id": pl.String,
            "scheduled_start": pl.Datetime("us", "UTC"),
        },
    )
    patient = pl.DataFrame(
        {
            "id": patient_ids,
            "run_id": [str(run_id)] * n_patients,
            "health_service_code": rng.integers(1, 4, size=n_patients),
            "commune_code": [f"0{c}101" for c in rng.integers(1, 4, size=n_patients)],
            "age_group": rng.choice(["0_14", "20_44", "65_plus"], size=n_patients).tolist(),
            "insurance": rng.choice(["fonasa_a", "fonasa_d"], size=n_patients).tolist(),
        }
    )
    entries = pl.DataFrame(
        {
            "id": [str(uuid.uuid5(run_id, f"entry:{i}")) for i in range(n_patients)],
            "patient_id": patient_ids,
            "entry_date": [
                AS_OF - timedelta(days=int(d)) for d in rng.integers(1, 500, n_patients)
            ],
        }
    )
    specialty = pl.DataFrame(
        {"code": codes, "name": codes, "care_type": [SPECIALTIES[c][0] for c in codes]}
    )
    truth = pl.DataFrame(
        {"appointment_id": appt_ids, "run_id": [str(run_id)] * total, "true_noshow_prob": p}
    )
    latent = pl.DataFrame(
        {"patient_id": patient_ids, "run_id": [str(run_id)] * n_patients, "noshow_frailty": frailty}
    )
    run_dir = root / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "appointment": appointment,
        "patient": patient,
        "waitlist_entry": entries,
        "catalog_specialty": specialty,
        "appointment_truth": truth,
        "patient_latent": latent,
    }
    for name, frame in tables.items():
        frame.write_parquet(run_dir / f"{name}.parquet")
    run: dict[str, Any] = {
        "id": str(run_id),
        "seed": seed,
        "size": n_patients,
        "scenario": "baseline",
        "as_of": AS_OF.isoformat(),
        "generator_version": "test",
        "targets_sha256": "0" * 64,
        "params_sha256": "0" * 64,
        "dataset_sha256": f"{seed:064d}",
    }
    (run_dir / "manifest.json").write_text(json.dumps({"run": run}), encoding="utf-8")
    return run_dir
