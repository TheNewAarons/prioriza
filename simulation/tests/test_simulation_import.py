"""Test trivial de importación para simulation."""


def test_simulation_import() -> None:
    """Verifica que el módulo simulation puede importarse."""
    import simulation

    assert simulation is not None
