from __future__ import annotations

import io

from kb.banner import banner, banner_large, paint, supports_color


def test_banner_large_has_castle_and_figlet() -> None:
    plain = banner_large(color=False)
    assert "▛▜" in plain          # crenellations
    assert "▛▀▀▀▜" in plain       # the arched gate lintel
    assert "▌   ▐" in plain       # the open gate
    assert "____" in plain        # figlet CITADEL
    assert "\033[" not in plain
    lengths = {len(line) for line in plain.splitlines()}
    assert max(lengths) - min(lengths) <= 1  # walls stay aligned (merlon row is rstripped)
    colored = banner_large(color=True)
    assert "\033[1m" in colored and "\033[36m" in colored  # bold figlet + cyan walls
    assert "\033[33m" in colored  # lit (yellow) windows


def test_banner_plain_has_wordmark_and_no_ansi() -> None:
    out = banner(color=False)
    assert "CITADEL" in out
    assert "the organization vault" in out
    assert "█" in out  # the castle walls
    assert "\033[" not in out  # no ANSI when color off


def test_banner_color_has_ansi() -> None:
    out = banner(color=True)
    assert "\033[36m" in out  # cyan walls
    assert "\033[1m" in out  # bold wordmark
    assert "\033[0m" in out  # reset


def test_paint_passthrough_when_disabled() -> None:
    assert paint("x", "green", enable=False) == "x"
    assert paint("x", enable=True) == "x"  # no styles
    assert paint("x", "green", enable=True) == "\033[32mx\033[0m"


def test_supports_color_false_for_non_tty() -> None:
    assert supports_color(io.StringIO()) is False


def test_supports_color_respects_no_color(monkeypatch) -> None:
    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert supports_color(_Tty()) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert supports_color(_Tty()) is False
