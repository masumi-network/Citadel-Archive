"""Citadel CLI branding — a compact castle banner + TTY-aware ANSI color.

Stdlib only. The banner and color are shown only on a real terminal (and never
in `--json` output), so piped/headless usage stays clean and parseable.
"""

from __future__ import annotations

import os
import sys
from typing import IO

# A crenellated fortress: battlements, walls, two windows, an arched gate.
# Box-drawing chars render in any modern terminal; we simply omit the banner
# when not a TTY.
_CASTLE_LINES = (
    "  ▙ ▟ ▙ ▟ ▙ ▟ ▙ ▟",
    "  ███████████████",
    "  ██ ▟▀▙   ▟▀▙ ██",
    "  ██ █ █   █ █ ██",
    "  █████▛▀▀▀▜█████",
)
# Right-side labels keyed by castle row, each with its ANSI styles.
_LABELS: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("CITADEL", ("bold", "cyan")),
    2: ("the organization vault", ("dim",)),
}

# Large hero — just the figlet "CITADEL" wordmark in brand colors. Shown on
# the bare `citadel` home screen; the compact castle `banner()` stays the
# in-command header (it is "the mark", see brand.md).
_WORDMARK = (
    "  ____  ___  _____     _     ____   _____  _     ",
    " / ___||_ _||_   _|   / \\   |  _ \\ | ____|| |    ",
    "| |     | |   | |    / _ \\  | | | ||  _|  | |    ",
    "| |___  | |   | |   / ___ \\ | |_| || |___ | |___ ",
    " \\____||___|  |_|  /_/   \\_\\|____/ |_____||_____|",
)
_HERO_INDENT = "  "
# Brand anchors (see brand.md): Masumi magenta #FA008C (the web brand) fading
# into the terminal's cyan — one gradient tying both brand surfaces together.
_BRAND_MAGENTA = (250, 0, 140)
_BRAND_CYAN = (34, 211, 238)

# Widest hero line — the home screen falls back to the compact banner when the
# terminal is narrower than this.
HERO_WIDTH = len(_HERO_INDENT) + max(len(line) for line in _WORDMARK)


def supports_truecolor() -> bool:
    """24-bit color support, per the de-facto COLORTERM convention."""
    return os.getenv("COLORTERM", "").lower() in ("truecolor", "24bit")


def _lerp_rgb(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(s + (e - s) * t) for s, e in zip(start, end))


def _gradient_line(line: str, *, width: int) -> str:
    """Paint one wordmark row with the brand gradient, column by column."""
    out: list[str] = [_ANSI["bold"]]
    for column, char in enumerate(line):
        if char != " ":
            r, g, b = _lerp_rgb(_BRAND_MAGENTA, _BRAND_CYAN, column / max(width - 1, 1))
            out.append(f"\033[38;2;{r};{g};{b}m")
        out.append(char)
    out.append(_ANSI["reset"])
    return "".join(out)

_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
}

# Semantic status glyphs — one shared vocabulary across home/status/onboard so
# the surfaces read like one product. Shape (not just color) carries pass/fail,
# so the signal survives NO_COLOR and low-DPI terminals where a filled vs hollow
# dot is indistinguishable.
OK = "✓"
FAIL = "✗"
WARN = "!"
SKIP = "⊘"
BULLET = "•"


def supports_color(stream: IO[str] | None = None) -> bool:
    """True on a real TTY (or when forced) that hasn't opted out.

    Opt-outs (NO_COLOR / TERM=dumb) win over force flags. FORCE_COLOR /
    CLICOLOR_FORCE then enable color even when piped (e.g. `… | less -R`).
    """
    stream = stream if stream is not None else sys.stdout
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("TERM") == "dumb":
        return False
    if os.getenv("FORCE_COLOR") or os.getenv("CLICOLOR_FORCE"):
        return True
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


def glyph(ok: bool) -> str:
    """The bare pass/fail glyph (✓ / ✗) — shape carries the signal sans color."""
    return OK if ok else FAIL


def mark(ok: bool, *, enable: bool = True) -> str:
    """The status glyph painted green (pass) or red (fail)."""
    return paint(glyph(ok), "green" if ok else "red", enable=enable)


def banner_large(*, color: bool = True) -> str:
    """The big hero: the CITADEL wordmark in brand colors — a magenta→cyan
    gradient on truecolor terminals, bold cyan elsewhere, plain when piped."""
    width = max(len(line) for line in _WORDMARK)
    out: list[str] = []
    for line in _WORDMARK:
        if color and supports_truecolor():
            out.append(_HERO_INDENT + _gradient_line(line, width=width))
        else:
            out.append(_HERO_INDENT + paint(line, "bold", "cyan", enable=color))
    return "\n".join(out)


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
