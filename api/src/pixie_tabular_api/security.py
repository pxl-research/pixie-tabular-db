from __future__ import annotations

import logging
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

_API_KEY_ENV_VAR = "PIXIE_API_KEY"
_EXPECTED_API_KEY = os.getenv(_API_KEY_ENV_VAR)
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Depends(_API_KEY_HEADER)) -> None:
    if _EXPECTED_API_KEY is None:
        logging.warning(
            "API key security is enabled but environment variable %s is not set",
            _API_KEY_ENV_VAR,
        )
        return

    if not api_key or api_key != _EXPECTED_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


__all__ = ["require_api_key"]
