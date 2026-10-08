"""Base declarativa común de todos los modelos ORM."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Convención de nombres: hace deterministas las migraciones y los downgrade.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base de los modelos SQLAlchemy 2; su `metadata` alimenta a Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
