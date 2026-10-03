"""Test trivial de importación para ingestion."""


def test_ingestion_import() -> None:
    """Verifica que el módulo ingestion puede importarse."""
    import ingestion

    assert ingestion is not None
