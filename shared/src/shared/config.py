"""Configuración de la aplicación, leída desde variables de entorno o `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes globales. Ningún valor sensible tiene un default real."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "prioriza"
    postgres_password: SecretStr = SecretStr("change-me")
    postgres_db: str = "prioriza"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    # Si se define, tiene prioridad sobre los campos POSTGRES_*.
    database_url: str | None = Field(default=None)

    api_port: int = 8000
    dashboard_port: int = 8050
    environment: str = "development"
    seed: int = 42
    # Directorio raíz de datos (raw/ y processed/ cuelgan de aquí).
    data_dir: Path = Path("data")

    @property
    def sqlalchemy_url(self) -> str:
        """URL de SQLAlchemy con el driver psycopg 3 (`postgresql+psycopg://`)."""
        if self.database_url:
            url = self.database_url
            for prefix in ("postgresql://", "postgres://"):
                if url.startswith(prefix):
                    return "postgresql+psycopg://" + url[len(prefix) :]
            return url
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes (cacheados por proceso)."""
    return Settings()
