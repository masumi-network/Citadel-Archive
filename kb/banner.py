"""Citadel CLI branding — a compact castle banner + TTY-aware ANSI color.

Stdlib only. The banner and color are shown only on a real terminal (and never
in `--json` output), so piped/headless usage stays clean and parseable.
"""

from __future__ import annotations

import os
import sys
from typing import IO

# A crenellated fortress: battlements, walls, two windows. Box-drawing chars
# render in any modern terminal; we simply omit the banner when not a TTY.
_CASTLE_LINES = (
    "  ▙ ▟ ▙ ▟ ▙ ▟ ▙ ▟",
    "  ███████████████",
    "  ██ ▟▀▙   ▟▀▙ ██",
    "  ██ █ █   █ █ ██",
    "  ███████████████",
)
# Right-side labels keyed by castle row, each with its ANSI styles.
_LABELS: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("CITADEL", ("bold", "cyan")),
    2: ("the organization vault", ("dim",)),
}

_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
}


def supports_color(stream: IO[str] | None = None) -> bool:
    """True only on a real TTY that hasn't opted out (NO_COLOR / dumb term)."""
    stream = stream if stream is not None else sys.stdout
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("TERM") == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def paint(text: str, *styles: str, enable: bool = True) -> str:
    """Wrap text in ANSI styles when enabled, e.g. paint('●', 'green')."""
    if not enable or not styles:
        return text
    codes = "".join(_ANSI.get(style, "") for style in styles)
    return f"{codes}{text}{_ANSI['reset']}" if codes else text


def banner(*, color: bool = True) -> str:
    """The Citadel castle banner; cyan walls, bold wordmark, dim tagline."""
    out: list[str] = []
    for index, line in enumerate(_CASTLE_LINES):
        rendered = paint(line, "cyan", enable=color)
        if index in _LABELS:
            text, styles = _LABELS[index]
            rendered += "   " + paint(text, *styles, enable=color)
        out.append(rendered)
    return "\n".join(out)
