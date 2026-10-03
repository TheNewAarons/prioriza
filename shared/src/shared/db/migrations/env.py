"""Entorno de Alembic: la URL sale de `get_settings()`, no de alembic.ini."""

from alembic import context
from shared.config import get_settings
from shared.db.base import Base
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera SQL sin conectarse a la base."""
    context.configure(
        url=get_settings().sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica migraciones contra la base configurada."""
    engine = create_engine(get_settings().sqlalchemy_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
