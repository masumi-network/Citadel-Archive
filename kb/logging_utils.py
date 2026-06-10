from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def resolve_log_level(value: str | None = None) -> str:
    level = (value or os.getenv("CITADEL_LOG_LEVEL") or "INFO").strip().upper()
    return level if level in VALID_LEVELS else "INFO"


def configure_logging(level: str | None = None) -> None:
    """Configure stdlib logging once at startup.

    Level comes from ``CITADEL_LOG_LEVEL`` (default INFO). Safe to call more than
    once: an already-configured root logger is left untouched except for level.
    """
    resolved = resolve_log_level(level)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=resolved, format=LOG_FORMAT)
    root.setLevel(resolved)
