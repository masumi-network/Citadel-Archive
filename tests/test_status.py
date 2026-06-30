from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from kb import status as status_mod
from kb.cli import _status
from kb.status import (
    Check,
    StatusReport,
    check_local_setup,
    gather_status,
    render_text,
)


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _route(responses: dict[str, dict[str, Any]]):
    """Return a fake opener.open that dispatches by URL substring."""

    def fake_open(request: Any, timeout: float | None = None) -> _FakeResp:
        url = request.full_url
        for needle, payload in responses.items():
            if needle in url:
                return _FakeResp(payload)
        raise AssertionError(f"unexpected URL {url}")

    return fake_open


def test_request_refuses_non_https() -> None:
    with pytest.raises(ValueError, match="non-HTTPS"):
        status_mod._request("GET", "http://node.example/healthz")


def test_check_local_setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_local_token_123")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"citadel": {"type": "http"}}}))
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\n")
    # Session hook lives in user-scope ~/.claude/settings.json (#38), isolated via
    # the CITADEL_HOME autouse fixture.
    from kb.onboard import claude_user_settings_path

    user_settings = claude_user_settings_path()
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_settings.write_text(
        json.dumps({"hooks": {"SessionEnd": [{"hooks": [{"command": status_mod.SESSION_HOOK_MARKER}]}]}})
    )
    cfg = tmp_path / "capture.json"
    cfg.write_text(json.dumps({"roots": [{"path": "/tmp/x", "tags": ["org-work"]}]}))

    checks = {c.name: c for c in check_local_setup(tmp_path, cfg)}
    assert checks["token"].ok
    assert checks["mcp"].ok
    assert checks["pre_push_hook"].ok
    assert checks["session_hook"].ok
    assert checks["capture_roots"].data["count"] == 1


def test_check_local_setup_all_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CITADEL_MCP_ACCESS_TOKEN", raising=False)
    cfg = tmp_path / "absent.json"
    checks = {c.name: c for c in check_local_setup(tmp_path, cfg)}
    assert not checks["token"].ok
    assert not checks["mcp"].ok
    assert not checks["pre_push_hook"].ok
    assert not checks["session_hook"].ok
    assert checks["capture_roots"].ok  # "none" is a valid state


def test_gather_status_healthy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        status_mod._OPENER,
        "open",
        _route(
            {
                "/healthz": {"ok": True, "service": "citadel"},
                "/api/session": {
                    "ok": True,
                    "role": "writer",
                    "seat_slug": "sarthi",
                    "node_label": "Node · sarthi",
                    "capabilities": {"read": True, "write": True, "admin": False},
                    "actor": {"name": "Sarthi"},
                },
                "/search": {"results": [{"id": 1}]},
                "/api/contributions/recent": {"contributions": [{"title": "feat: x", "created_at": "2026-06-27T10:00:00"}]},
            }
        ),
    )
    report = gather_status("https://node.example", "ctdl_tok", repo=tmp_path, config_path=tmp_path / "c.json")
    assert report.healthy
    assert report.identity["seat_slug"] == "sarthi"
    names = {c.name: c.ok for c in report.checks}
    assert names["node"] and names["auth"] and names["search"]
    assert report.recent[0]["title"] == "feat: x"


def test_check_local_setup_corrupt_config_does_not_raise(tmp_path: Path) -> None:
    cfg = tmp_path / "capture.json"
    cfg.write_text("{ broken json")
    checks = {c.name: c for c in check_local_setup(tmp_path, cfg)}
    assert checks["capture_roots"].ok is False
    assert "corrupt" in checks["capture_roots"].detail


def test_check_search_empty_list_is_zero(monkeypatch) -> None:
    monkeypatch.setattr(status_mod._OPENER, "open", _route({"/search": {"results": []}}))
    check = status_mod.check_search("https://node.example", "ctdl_tok")
    # #27: a zero-result smoke search is RED (read path up but data plane empty),
    # not always-green.
    assert check.ok is False and check.data["count"] == 0
    assert "0 result(s)" in check.detail


def test_check_corpus_red_when_readyz_503(monkeypatch) -> None:
    # #27: /readyz answers 503 + body when the corpus gate trips; check_corpus
    # parses the body and reports RED.
    import io
    import urllib.error

    body = json.dumps(
        {"ok": False, "corpus": {"ok": False, "tracked_sources": 200, "indexed_docs": 0}, "canary": None}
    ).encode()

    def raise_503(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, io.BytesIO(body))

    monkeypatch.setattr(status_mod._OPENER, "open", raise_503)
    check = status_mod.check_corpus("https://node.example", "ctdl_tok")
    assert check is not None
    assert check.ok is False
    assert "0 indexed / 200 tracked" in check.detail


def test_check_corpus_ok_when_readyz_healthy(monkeypatch) -> None:
    monkeypatch.setattr(
        status_mod._OPENER,
        "open",
        _route({"/readyz": {"ok": True, "corpus": {"ok": True, "tracked_sources": 200, "indexed_docs": 280}, "canary": {"ok": True}}}),
    )
    check = status_mod.check_corpus("https://node.example", "ctdl_tok")
    assert check is not None and check.ok is True
    assert "280 indexed / 200 tracked" in check.detail


def test_gather_status_node_down(tmp_path: Path) -> None:
    import kb.status as s

    def boom(request: Any, timeout: float | None = None) -> None:
        raise OSError("connection refused")

    original = s._OPENER.open
    s._OPENER.open = boom  # type: ignore[assignment]
    try:
        report = gather_status("https://node.example", "ctdl_tok", repo=tmp_path, config_path=tmp_path / "c.json")
    finally:
        s._OPENER.open = original  # type: ignore[assignment]
    assert not report.healthy
    assert any(c.name == "node" and not c.ok for c in report.checks)


def test_auth_no_token() -> None:
    report = gather_status(
        "https://node.example", None, with_search=False, with_recent=False, repo=Path("/tmp")
    )
    auth = next(c for c in report.checks if c.name == "auth")
    assert not auth.ok
    assert "no token" in auth.detail


def test_render_text_smoke() -> None:
    report = StatusReport(
        node_url="https://node.example",
        healthy=True,
        identity={"seat_slug": "sarthi", "role": "writer"},
        checks=[Check("node", ok=True, detail="healthy", latency_ms=38)],
        recent=[],
    )
    out = render_text(report)
    assert "seat: sarthi" in out
    assert "All systems go." in out
    assert "✓" in out


def test_status_command_json_and_exit(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        status_mod._OPENER,
        "open",
        _route({"/healthz": {"ok": True}, "/api/session": {"ok": True, "role": "writer", "seat_slug": "s"}, "/search": {"results": []}, "/api/contributions/recent": {"contributions": []}}),
    )
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_tok")
    args = argparse.Namespace(
        json=True,
        node_url="https://node.example",
        repo=str(tmp_path),
        config=str(tmp_path / "c.json"),
        no_search=False,
        no_recent=False,
    )
    rc = asyncio.run(_status(args))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["healthy"] is True
    assert payload["identity"]["seat_slug"] == "s"


def test_status_command_unhealthy_exits_one(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("CITADEL_MCP_ACCESS_TOKEN", raising=False)

    def boom(request: Any, timeout: float | None = None) -> None:
        raise OSError("down")

    monkeypatch.setattr(status_mod._OPENER, "open", boom)
    args = argparse.Namespace(
        json=False,
        node_url="https://node.example",
        repo=str(tmp_path),
        config=str(tmp_path / "c.json"),
        no_search=True,
        no_recent=True,
    )
    rc = asyncio.run(_status(args))
    assert rc == 1
    assert "Not connected" in capsys.readouterr().out
