from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from kb.cli import _doctor, _ingest, _search
from kb.status import Check, StatusReport


def _ingest_args(**kw):
    base = dict(data="a note", tag=[], json=True, node_url="https://node.example",
                local=False, dataset=None, session=None, no_cognify=True)
    base.update(kw)
    return argparse.Namespace(**base)


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
    assert rc == 0  # all auto-fixable issues were applied → clean exit
    assert out["resolved"] is True
    assert set(out["fixed"]) == {"pre-push hook", "Claude hooks", "MCP server"}
    assert (tmp_path / ".git" / "hooks" / "pre-push").exists()
    # Claude hooks are installed at user scope (#38), isolated via CITADEL_HOME.
    from kb.onboard import claude_user_settings_path

    assert claude_user_settings_path().exists()
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


def test_ingest_http_accepted(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: "ctdl_x")
    monkeypatch.setattr("kb.status.ingest_node", lambda *a, **k: {"accepted": True, "dataset": "seat:alice"})
    rc = asyncio.run(_ingest(_ingest_args()))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is True


def test_ingest_http_rejected_exits_one(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: "ctdl_x")
    monkeypatch.setattr("kb.status.ingest_node", lambda *a, **k: {"accepted": False, "reason": "secret_content"})
    rc = asyncio.run(_ingest(_ingest_args()))
    assert rc == 1  # a hard rejection must not exit 0


def test_ingest_duplicate_is_benign(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: "ctdl_x")
    monkeypatch.setattr("kb.status.ingest_node", lambda *a, **k: {"accepted": False, "reason": "duplicate_in_process"})
    # A duplicate is idempotent: exit 0, friendly message, not a scary failure.
    rc = asyncio.run(_ingest(_ingest_args(json=False)))
    assert rc == 0
    assert "duplicate" in capsys.readouterr().out.lower()


def test_ingest_no_token_exits_one(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: None)
    rc = asyncio.run(_ingest(_ingest_args(json=False)))
    assert rc == 1
    assert "no token" in capsys.readouterr().err


def test_ingest_cognifies_by_default(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli.capture_token", lambda: "ctdl_x")
    seen: dict = {}

    def fake_ingest(base_url, token, data, tags, cognify=False, **k):
        seen["cognify"] = cognify  # the Node is asked to cognify inline
        return {"accepted": True, "dataset": "seat:alice", "cognified": True}

    monkeypatch.setattr("kb.status.ingest_node", fake_ingest)
    rc = asyncio.run(_ingest(_ingest_args(no_cognify=False)))
    assert rc == 0
    assert seen["cognify"] is True
    assert json.loads(capsys.readouterr().out)["cognified"] is True
