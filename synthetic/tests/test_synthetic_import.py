"""Test trivial de importación para synthetic."""


def test_synthetic_import() -> None:
    """Verifica que el módulo synthetic puede importarse."""
    import synthetic

    assert synthetic is not None
