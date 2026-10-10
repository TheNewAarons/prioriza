"""Tests de la configuración compartida (sin red ni base de datos)."""

import pytest
from shared.config import Settings, get_settings

_VARS = [
    "DATABASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "SEED",
    "ENVIRONMENT",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_url_from_postgres_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_DB", "d")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.sqlalchemy_url == "postgresql+psycopg://u:p@db:5432/d"


def test_database_url_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://a:b@h:1/x")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.sqlalchemy_url == "postgresql+psycopg://a:b@h:1/x"


def test_default_seed_and_cache() -> None:
    assert Settings(_env_file=None).seed == 42  # type: ignore[call-arg]
    assert get_settings() is get_settings()


def test_production_rechaza_password_por_defecto() -> None:
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD") as info:
        Settings(environment="production", _env_file=None)  # type: ignore[call-arg]
    assert "change-me" not in str(info.value)


def test_production_rechaza_password_vacia() -> None:
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings(environment="production", postgres_password="", _env_file=None)  # type: ignore[call-arg,arg-type]


def test_production_acepta_password_propia_o_database_url() -> None:
    own = Settings(environment="production", postgres_password="s3cr3to", _env_file=None)  # type: ignore[call-arg,arg-type]
    assert "s3cr3to" in own.sqlalchemy_url
    url = Settings(environment="production", database_url="postgresql://u:p@h/d", _env_file=None)  # type: ignore[call-arg]
    assert url.sqlalchemy_url == "postgresql+psycopg://u:p@h/d"


def test_development_permite_password_por_defecto() -> None:
    assert Settings(_env_file=None).environment == "development"  # type: ignore[call-arg]
