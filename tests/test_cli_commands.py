from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from kb.cli import _doctor, _search
from kb.status import Check, StatusReport


def _report(checks: list[Check], *, healthy: bool = True) -> StatusReport:
    return StatusReport(
        node_url="https://node.example",
        healthy=healthy,
        identity={"seat_slug": "alice", "role": "writer"},
        checks=checks,
        recent=[],
    )


def _all_ok() -> list[Check]:
    return [
        Check("node", True, "healthy"),
        Check("auth", True, "valid"),
        Check("token", True, "…1234"),
        Check("mcp", True, "present"),
        Check("pre_push_hook", True, "installed"),
        Check("session_hook", True, "installed"),
        Check("capture_roots", True, "none"),
    ]


def test_doctor_clean_reports_ok(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_x")
    monkeypatch.setattr("kb.cli.gather_status", lambda *a, **k: _report(_all_ok()))
    args = argparse.Namespace(
        repo=str(tmp_path), config=str(tmp_path / "cap.json"),
        node_url=None, json=True, fix=False,
    )
    rc = asyncio.run(_doctor(args))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["issues"] == []


def test_doctor_fix_installs_missing_local_setup(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_x")
    broken = [
        Check("node", True, "healthy"),
        Check("auth", True, "valid"),
        Check("mcp", False, "not configured"),
        Check("pre_push_hook", False, "missing"),
        Check("session_hook", False, "missing"),
    ]
    monkeypatch.setattr("kb.cli.gather_status", lambda *a, **k: _report(broken))
    args = argparse.Namespace(
        repo=str(tmp_path), config=str(tmp_path / "cap.json"),
        node_url="https://node.example", json=True, fix=True,
    )
    rc = asyncio.run(_doctor(args))
    out = json.loads(capsys.readouterr().out)
    assert rc == 1  # issues were found (doctor reports even after fixing)
    assert set(out["fixed"]) == {"pre-push hook", "Claude hooks", "MCP server"}
    assert (tmp_path / ".git" / "hooks" / "pre-push").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".mcp.json").exists()


def test_search_http_renders_results(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: "ctdl_x")
    monkeypatch.setattr("kb.status.search_node", lambda *a, **k: [{"text": "hello vault"}])
    args = argparse.Namespace(
        query="hi", top_k=10, json=True, node_url="https://node.example",
        local=False, dataset=None, session=None,
    )
    rc = asyncio.run(_search(args))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == [{"text": "hello vault"}]


def test_search_no_token_exits_one(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: None)
    args = argparse.Namespace(
        query="hi", top_k=10, json=False, node_url=None,
        local=False, dataset=None, session=None,
    )
    rc = asyncio.run(_search(args))
    assert rc == 1
    assert "no token" in capsys.readouterr().err
