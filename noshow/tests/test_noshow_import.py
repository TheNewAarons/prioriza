"""Test trivial de importación para noshow."""


def test_noshow_import() -> None:
    """Verifica que el módulo noshow puede importarse."""
    import noshow

    assert noshow is not None
