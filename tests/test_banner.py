from __future__ import annotations

import io

from kb.banner import banner, banner_large, paint, supports_color


def test_banner_large_is_the_brand_wordmark(monkeypatch) -> None:
    plain = banner_large(color=False)
    assert "____" in plain        # figlet CITADEL
    assert "\033[" not in plain   # plain when piped
    assert len(plain.splitlines()) == 5  # just the wordmark, nothing else

    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    basic = banner_large(color=True)
    assert "\033[1m" in basic and "\033[36m" in basic  # bold cyan fallback

    monkeypatch.setenv("TERM", "xterm-256color")
    approx = banner_large(color=True)
    assert "\033[38;5;" in approx  # 256-color gradient approximation

    monkeypatch.setenv("COLORTERM", "truecolor")
    gradient = banner_large(color=True)
    assert "\033[38;2;250;0;140m" in gradient  # starts at brand magenta #FA008C
    assert "\033[38;2;34;211;238m" in gradient  # ends at brand cyan


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
