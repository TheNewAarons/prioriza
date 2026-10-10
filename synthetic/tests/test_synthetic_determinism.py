"""Determinismo: misma semilla => mismo digest y frames idénticos."""

from __future__ import annotations

import os
import subprocess
import sys

from synthetic.digest import dataset_digest

N = 5_000


def test_misma_semilla_mismo_digest_y_frames(make_dataset):
    """Dos corridas con la misma semilla producen digest y DataFrames idénticos."""
    a = make_dataset(N, 7)
    b = make_dataset(N, 7)
    assert a.digest == b.digest
    assert a.digest == dataset_digest(
        {**a.tables, **{f"catalog_{k}": v for k, v in a.catalogs.items()}}
    )
    assert set(a.tables) == set(b.tables)
    for name in a.tables:
        assert a.tables[name].equals(b.tables[name]), name


def test_semilla_distinta_digest_distinto(make_dataset):
    """Semillas distintas producen digests distintos."""
    assert make_dataset(N, 7).digest != make_dataset(N, 8).digest


def test_escenario_distinto_digest_distinto(make_dataset):
    """Cambiar el escenario cambia el digest (la verdad de inasistencia difiere)."""
    assert make_dataset(N, 7, "baseline").digest != make_dataset(N, 7, "neutral").digest


def test_digest_es_sha256_hex(ds1k):
    """El digest es una cadena hexadecimal de 64 caracteres."""
    assert len(ds1k.digest) == 64
    int(ds1k.digest, 16)


# Digest de referencia (N=3.000, semilla 42, baseline). Si cambia a propósito el generador,
# se actualiza aquí; si cambia sin querer (p. ej. por PYTHONHASHSEED) este test lo detecta.
DIGEST_N3000_SEED42_BASELINE = "aa783cbf5ed51904c9da7d215aa8bf048fc2c14df06a5bc6d88ea1ce22e71995"

_SCRIPT = (
    "from shared.db.enums import NoShowScenario\n"
    "from synthetic.config import RunConfig\n"
    "from synthetic.pipeline import generate\n"
    "cfg = RunConfig(size=3000, seed=42, scenario=NoShowScenario('baseline'))\n"
    "print(generate(cfg).digest)\n"
)


def test_digest_fijo_n3000_seed42(make_dataset):
    """El digest de referencia no cambia (detecta no determinismo accidental)."""
    assert make_dataset(3_000, 42).digest == DIGEST_N3000_SEED42_BASELINE


def test_digest_independiente_de_pythonhashseed():
    """Un subproceso con PYTHONHASHSEED distinto produce el mismo digest."""
    env = {**os.environ, "PYTHONHASHSEED": "987"}
    out = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
    )
    assert out.stdout.strip().splitlines()[-1] == DIGEST_N3000_SEED42_BASELINE
