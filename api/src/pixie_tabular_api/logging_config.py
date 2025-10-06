"""Central logging configuration for the Pixie Tabular API."""

from __future__ import annotations

import logging

from .config import get_settings


def configure_logging() -> None:
    """Configure standard logging format and level once per process."""
    settings = get_settings()
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,
    )


__all__ = ["configure_logging"]
