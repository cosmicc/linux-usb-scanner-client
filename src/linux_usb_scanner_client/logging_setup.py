"""Logging setup for the service and CLI."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import LoggingConfig


def configure_logging(config: LoggingConfig, *, to_stderr: bool = True) -> None:
    """Configure Python logging without exposing raw scan payloads."""

    level = getattr(logging, config.log_level, logging.INFO)
    handlers: list[logging.Handler] = []
    if config.log_file:
        Path(config.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.log_file, encoding="utf-8"))
    if to_stderr:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setLevel(level)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
