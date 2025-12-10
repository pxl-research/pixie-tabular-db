from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import quote_plus

from .internal_defaults import DEFAULT_POSTGRES


@dataclass(frozen=True)
class Settings:
    postgres_db: str = DEFAULT_POSTGRES["db"]
    postgres_user: str = DEFAULT_POSTGRES["user"]
    postgres_password: str = DEFAULT_POSTGRES["password"]
    postgres_host: str = DEFAULT_POSTGRES["host"]
    postgres_port: int = DEFAULT_POSTGRES["port"]

    tabular_api_key: Optional[str] = None

    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: Optional[str] = None
    azure_openai_model_version: Optional[str] = None

    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
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
        tabular_api_key=os.getenv("TABULAR_API_KEY"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=os.getenv("BASE_AZURE_OPENAI_API_VERSION"),
        azure_openai_model_version=os.getenv("BASE_AZURE_OPENAI_MODEL_VERSION"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance loaded from environment."""
    return _read_settings()


__all__ = ["Settings", "get_settings"]
