"""Motor y sesiones de SQLAlchemy."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    """Devuelve el motor (cacheado por URL); sin URL usa `Settings.sqlalchemy_url`."""
    return create_engine(url or get_settings().sqlalchemy_url, pool_pre_ping=True)


def session_factory() -> sessionmaker[Session]:
    """Fábrica de sesiones ligada al motor por defecto."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)
