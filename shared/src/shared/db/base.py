"""Base declarativa común de todos los modelos ORM."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Clase base de los modelos SQLAlchemy 2; su `metadata` alimenta a Alembic."""
