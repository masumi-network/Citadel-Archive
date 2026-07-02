"""Interactive terminal prompts — stdlib only.

`checkbox_select` is an arrow-key multi-select (↑/↓ move, space toggle, enter
apply) used by `citadel onboard` for the coding-tools step. On terminals where
raw mode isn't available (no termios — e.g. Windows — or stdin/stdout not a
real TTY) it degrades to a numeric toggle prompt, so the same call works
everywhere the wizard runs.
"""

from __future__ import annotations

import os
import sys

from kb.banner import OK, paint, supports_color

_HELP = "↑/↓ move · space toggle · a all · n none · enter apply · q skip"


def _read_key(stream) -> str:
    """One keypress, decoding the 3-byte arrow-key escape sequences."""
    ch = stream.read(1)
    if ch == "\x1b" and stream.read(1) == "[":
        return "\x1b[" + stream.read(1)
    return ch


def _render_rows(options: list[str], checked: set[int], cursor: int, *, color: bool) -> list[str]:
    rows = []
    for index, label in enumerate(options):
        box = paint(f"[{OK}]", "green", enable=color) if index in checked else "[ ]"
        pointer = paint("❯", "bold", "cyan", enable=color) if index == cursor else " "
        text = paint(label, "bold", enable=color) if index == cursor else label
        rows.append(f"  {pointer} {box} {text}")
    return rows


def _select_raw(header: str, options: list[str], checked: set[int]) -> set[int] | None:
    """Arrow-key checkbox UI. Repaints in place; cursor hidden while active."""
    import termios
    import tty

    color = supports_color()
    cursor = 0
    out = sys.stdout
    drawn = 0

    def render() -> None:
        nonlocal drawn
        if drawn:
            out.write(f"\033[{drawn}A")  # jump back to the top of our block
        rows = [header, *_render_rows(options, checked, cursor, color=color),
                "  " + paint(_HELP, "dim", enable=color)]
        for row in rows:
            out.write("\033[2K" + row + "\n")
        drawn = len(rows)
        out.flush()

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    out.write("\033[?25l")
    try:
        # cbreak (not raw): keypresses arrive unbuffered but Ctrl-C still
        # signals, so the global KeyboardInterrupt → exit 130 path holds.
        tty.setcbreak(fd)
        while True:
            render()
            key = _read_key(sys.stdin)
            if key in ("\x1b[A", "k"):
                cursor = (cursor - 1) % len(options)
            elif key in ("\x1b[B", "j"):
                cursor = (cursor + 1) % len(options)
            elif key == " ":
                checked.symmetric_difference_update({cursor})
            elif key in ("a", "A"):
                checked = set(range(len(options)))
            elif key in ("n", "N"):
                checked = set()
            elif key in ("\r", "\n"):
                return checked
            elif key in ("q", "Q"):
                return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        out.write("\033[?25h")
        out.flush()


def _select_lines(header: str, options: list[str], checked: set[int]) -> set[int] | None:
    """Line-based fallback: toggle by number, Enter applies, q skips."""
    color = supports_color()
    print(header)
    while True:
        for index, label in enumerate(options, 1):
            box = paint(f"[{OK}]", "green", enable=color) if index - 1 in checked else "[ ]"
            print(f"    {box} {index}. {label}")
        raw = input("  Toggle by number (e.g. 1 3), a all, n none, q skip — Enter to apply: ").strip().lower()
        if not raw:
            return checked
        if raw in ("q", "quit"):
            return None
        if raw == "a":
            checked = set(range(len(options)))
            continue
        if raw == "n":
            checked = set()
            continue
        for part in raw.replace(",", " ").split():
            if part.isdigit() and 1 <= int(part) <= len(options):
                checked.symmetric_difference_update({int(part) - 1})


def checkbox_select(header: str, options: list[str], checked: set[int]) -> set[int] | None:
    """Multi-select over `options`; returns chosen indexes, or None on skip.

    `checked` marks the preselected rows. Uses the arrow-key UI on a capable
    TTY, the numeric fallback everywhere else.
    """
    if not options:
        return set()
    checked = {i for i in checked if 0 <= i < len(options)}
    raw_capable = (
        os.getenv("TERM", "") != "dumb"
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
    if raw_capable:
        try:
            return _select_raw(header, options, set(checked))
        except (ImportError, OSError, ValueError):
            pass  # no termios / odd tty — fall through to the line prompt
    return _select_lines(header, options, set(checked))
