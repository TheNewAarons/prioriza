"""Determinismo: misma semilla => mismo digest y frames idénticos."""

from __future__ import annotations

from synthetic.digest import dataset_digest

N = 5_000


def test_misma_semilla_mismo_digest_y_frames(make_dataset):
    """Dos corridas con la misma semilla producen digest y DataFrames idénticos."""
    a = make_dataset(N, 7)
    b = make_dataset(N, 7)
    assert a.digest == b.digest
    assert a.digest == dataset_digest(a.tables)
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
