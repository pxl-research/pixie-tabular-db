from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Settings:
    postgres_db: str = "pixie_tabular"
    postgres_user: str = "pixie"
    postgres_password: str | None = None
    postgres_host: str = "db"
    postgres_port: int = 5432

    pixie_api_key: Optional[str] = None

    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: Optional[str] = None
    azure_openai_model_version: Optional[str] = None

    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        if self.postgres_password is None:
            raise RuntimeError("POSTGRES_PASSWORD must be configured")

        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def azure_llm_configured(self) -> bool:
        return all(
            [
                self.azure_openai_endpoint,
                self.azure_openai_api_key,
                self.azure_openai_api_version,
                self.azure_openai_model_version,
            ]
        )


def _read_settings() -> Settings:
    return Settings(
        postgres_db=os.getenv("POSTGRES_DB") or "pixie_tabular",
        postgres_user=os.getenv("POSTGRES_USER") or "pixie",
        postgres_password=os.getenv("POSTGRES_PASSWORD"),
        postgres_host=os.getenv("DB_HOST") or "db",
        postgres_port=int(os.getenv("DB_PORT", 5432)),
        pixie_api_key=os.getenv("PIXIE_API_KEY"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_openai_model_version=os.getenv("AZURE_OPENAI_MODEL_VERSION"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance loaded from environment."""
    return _read_settings()


__all__ = ["Settings", "get_settings"]
