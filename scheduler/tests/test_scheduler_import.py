"""Test trivial de importación para scheduler."""


def test_scheduler_import() -> None:
    """Verifica que el módulo scheduler puede importarse."""
    import scheduler

    assert scheduler is not None
