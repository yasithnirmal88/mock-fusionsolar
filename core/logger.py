"""
Logging configuration for the application.

Provides a small helper to configure the standard Python logging module in a
consistent manner for production or development use.
"""
from __future__ import annotations

import logging
from logging import Logger
from typing import Optional


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with a sensible default format.

    Args:
        level: string name of the logging level (e.g. "DEBUG", "INFO").
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Basic configuration - in production a more advanced setup (handlers,
    # formatters, external monitoring) may be used.
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def get_logger(name: Optional[str] = None) -> Logger:
    """Return a logger for the given name or the root logger."""
    return logging.getLogger(name)
