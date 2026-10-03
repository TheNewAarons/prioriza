"""Excepciones de la ingesta."""


class IngestionError(Exception):
    """Error base de la ingesta."""


class DownloadError(IngestionError):
    """Falla al descargar o al verificar una fuente."""


class SchemaDriftError(IngestionError):
    """El formato de la fuente cambió respecto de lo que el parser espera."""

    def __init__(
        self,
        source_id: str,
        table: str,
        detail: str,
        expected: str | None = None,
        found: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.table = table
        self.detail = detail
        self.expected = expected
        self.found = found
        message = f"[{source_id}/{table}] {detail}"
        if expected is not None or found is not None:
            message += f": esperado {expected!r}, encontrado {found!r}"
        message += ". Revise el PDF o actualice TableSpec."
        super().__init__(message)


class DataValidationError(IngestionError):
    """Los datos parseados no pasan una validación de consistencia."""

    def __init__(self, source_id: str, table: str, detail: str) -> None:
        self.source_id = source_id
        self.table = table
        self.detail = detail
        super().__init__(f"[{source_id}/{table}] {detail}")
