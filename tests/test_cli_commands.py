from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kb.cli import _doctor, _ingest, _search, _token_set, _update, _wizard_roots
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


# ---- citadel token set --------------------------------------------------------


def _token_set_args(tmp_path: Path, **kw) -> argparse.Namespace:
    base = dict(
        token="ctdl_rotated_4567890",
        shell_rc=str(tmp_path / ".zshrc"),
        node_url="https://node.example",
        skip_verify=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_token_set_verifies_then_writes_rc(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "kb.status.check_auth",
        lambda *a, **k: Check("auth", True, "valid", data={"seat_slug": "sarthi", "role": "writer"}),
    )
    rc = asyncio.run(_token_set(_token_set_args(tmp_path)))
    assert rc == 0
    assert "ctdl_rotated_4567890" in (tmp_path / ".zshrc").read_text()
    assert "…7890" in capsys.readouterr().out


def test_token_set_rejected_token_writes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "kb.status.check_auth", lambda *a, **k: Check("auth", False, "HTTP Error 401: Unauthorized")
    )
    rc = asyncio.run(_token_set(_token_set_args(tmp_path)))
    assert rc == 1
    assert not (tmp_path / ".zshrc").exists()  # a bad token must not clobber a working one
    assert "nothing written" in capsys.readouterr().err


def test_token_set_skip_verify_writes_offline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kb.status.check_auth", lambda *a, **k: pytest.fail("verified despite --skip-verify")
    )
    rc = asyncio.run(_token_set(_token_set_args(tmp_path, skip_verify=True)))
    assert rc == 0
    assert "ctdl_rotated_4567890" in (tmp_path / ".zshrc").read_text()


def test_token_set_no_token_no_tty_exits_two(tmp_path: Path, capsys) -> None:
    rc = asyncio.run(_token_set(_token_set_args(tmp_path, token=None)))
    assert rc == 2
    assert "no TTY" in capsys.readouterr().err


# ---- citadel update -----------------------------------------------------------


def test_update_editable_install_is_left_alone(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli._install_channel", lambda: ("editable", "file:///src/citadel"))
    monkeypatch.setattr("kb.cli.subprocess.run", lambda *a, **k: pytest.fail("must not shell out"))
    rc = asyncio.run(_update(argparse.Namespace()))
    assert rc == 0
    assert "git pull" in capsys.readouterr().out


def test_update_pipx_already_latest(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli._install_channel", lambda: ("pipx", "/usr/bin/pipx"))
    monkeypatch.setattr(
        "kb.cli.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="citadel-archive is already at latest version 0.2.1 (location: …)",
            stderr="",
        ),
    )
    rc = asyncio.run(_update(argparse.Namespace()))
    assert rc == 0
    assert "already up to date" in capsys.readouterr().out


def test_update_pipx_upgraded(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli._install_channel", lambda: ("pipx", "/usr/bin/pipx"))
    monkeypatch.setattr(
        "kb.cli.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="upgraded package citadel-archive from 0.2.1 to 0.3.0 (location: …)",
            stderr="",
        ),
    )
    rc = asyncio.run(_update(argparse.Namespace()))
    assert rc == 0
    assert "upgraded package citadel-archive" in capsys.readouterr().out


def test_update_pipx_failure_exits_one(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli._install_channel", lambda: ("pipx", "/usr/bin/pipx"))
    monkeypatch.setattr(
        "kb.cli.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    rc = asyncio.run(_update(argparse.Namespace()))
    assert rc == 1
    assert "boom" in capsys.readouterr().err


def test_update_unmanaged_install_prints_instructions(monkeypatch, capsys) -> None:
    monkeypatch.setattr("kb.cli._install_channel", lambda: ("other", ""))
    rc = asyncio.run(_update(argparse.Namespace()))
    assert rc == 0
    assert "pip install --upgrade citadel-archive" in capsys.readouterr().out


# ---- capture-roots wizard -----------------------------------------------------


def test_wizard_offers_home_relative_guess_for_missing_root(tmp_path: Path, monkeypatch, capsys) -> None:
    # "/masumi" for ~/masumi is the common typo — the wizard should offer the
    # home-relative dir that actually exists instead of recording a dead root.
    from kb.capture_config import CaptureConfig

    (tmp_path / "masumi").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    answers = iter(["/masumi", "", "", ""])  # path → accept guess → default tags → finish
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config = _wizard_roots(CaptureConfig(node_url="https://node.example"))
    assert [root.path for root in config.roots] == [str(tmp_path / "masumi")]


def test_wizard_enter_accepts_default_root(tmp_path: Path, monkeypatch) -> None:
    # The dir the user ran `citadel` from is offered as a press-Enter default —
    # no copy-pasting the path you're already standing in.
    from kb.capture_config import CaptureConfig

    answers = iter(["", "", ""])  # accept default → default tags → finish
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config = _wizard_roots(CaptureConfig(node_url="https://node.example"), default_root=str(tmp_path))
    assert [root.path for root in config.roots] == [str(tmp_path)]
    assert "personal" in config.roots[0].tags


def test_wizard_default_suppressed_when_already_approved(tmp_path: Path, monkeypatch) -> None:
    from kb.capture_config import CaptureConfig

    existing = CaptureConfig(node_url="https://node.example").with_root(str(tmp_path), ("personal",))
    answers = iter([""])  # no default on offer → Enter just finishes
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config = _wizard_roots(existing, default_root=str(tmp_path))
    assert len(config.roots) == 1  # not duplicated
