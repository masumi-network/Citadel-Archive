from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("textual")

from kb import status_tui  # noqa: E402
from kb.cli import _tui  # noqa: E402
from kb.status import Check, StatusReport  # noqa: E402


def _report(healthy: bool = True) -> StatusReport:
    return StatusReport(
        node_url="https://node.example",
        healthy=healthy,
        identity={"seat_slug": "sarthi", "role": "writer"},
        checks=[
            Check("node", ok=True, detail="healthy", latency_ms=38),
            Check("auth", ok=healthy, detail="valid"),
        ],
        recent=[{"title": "feat: x", "created_at": "2026-06-27T10:00:00"}],
    )


def test_markup_helpers() -> None:
    report = _report()
    assert "sarthi" in status_tui._identity_markup(report)
    assert "connected" in status_tui._identity_markup(report)
    assert "node" in status_tui._checks_markup(report)
    assert "feat: x" in status_tui._recent_markup(report)


def test_markup_unhealthy() -> None:
    assert "not connected" in status_tui._identity_markup(_report(healthy=False))


def test_app_renders_status(monkeypatch) -> None:
    monkeypatch.setattr(status_tui, "gather_status", lambda *a, **k: _report())
    captured: dict[str, StatusReport] = {}
    original_render = status_tui.StatusApp._render

    def spy(self: status_tui.StatusApp, report: StatusReport) -> None:
        captured["report"] = report
        original_render(self, report)  # exercise the real widget .update() calls

    monkeypatch.setattr(status_tui.StatusApp, "_render", spy)

    async def _run() -> None:
        app = status_tui.StatusApp(
            "https://node.example", "ctdl_tok", repo=Path("/tmp"), config_path=None, refresh_seconds=0
        )
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(_run())
    assert captured["report"].identity["seat_slug"] == "sarthi"


def test_app_survives_untrusted_markup(monkeypatch) -> None:
    # Node-supplied titles/identity containing Rich markup must NOT crash the
    # render (MarkupError) or inject styling/links. Common benign case: "[WIP]".
    report = _report()
    report.recent = [
        {"title": "fix [/] thing", "created_at": "2026-06-27T10:00:00"},
        {"title": "[link=http://evil]click[/link]", "created_at": "2026-06-27T09:00:00"},
        {"title": "[red]PWNED[/] [WIP]", "created_at": "2026-06-27T08:00:00"},
    ]
    report.identity = {"seat_slug": "se[at]", "role": "wr[i]ter"}
    monkeypatch.setattr(status_tui, "gather_status", lambda *a, **k: report)

    rendered: list[bool] = []
    original = status_tui.StatusApp._render
    monkeypatch.setattr(
        status_tui.StatusApp,
        "_render",
        lambda self, rep: (rendered.append(True), original(self, rep))[1],
    )

    async def _run() -> None:
        app = status_tui.StatusApp(
            "https://node.example", "ctdl_tok", repo=Path("/tmp"), config_path=None, refresh_seconds=0
        )
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(_run())  # must not raise WorkerFailed/MarkupError
    assert rendered  # the real render ran with the malicious data and survived


def test_tui_handler_launches(monkeypatch, tmp_path: Path) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("kb.status_tui.run_tui", lambda *a, **k: calls.append(True))
    args = argparse.Namespace(
        node_url="https://node.example", repo=str(tmp_path), config=str(tmp_path / "c.json")
    )
    assert asyncio.run(_tui(args)) == 0
    assert calls


def test_tui_handler_missing_textual(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setitem(sys.modules, "kb.status_tui", None)
    args = argparse.Namespace(
        node_url="https://node.example", repo=str(tmp_path), config=str(tmp_path / "c.json")
    )
    assert asyncio.run(_tui(args)) == 1
    assert "textual" in capsys.readouterr().err
