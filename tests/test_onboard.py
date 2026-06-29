from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pytest

from kb.cli import _onboard
from kb.onboard import (
    TOKEN_ENV,
    detect_shell_rc,
    ensure_token_in_rc,
    install_pre_push_hook,
    mask_token,
    mcp_server_block,
    merge_claude_settings,
    merge_mcp_config,
)


def test_detect_shell_rc(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert detect_shell_rc(tmp_path).name == ".zshrc"
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    assert detect_shell_rc(tmp_path).name == ".bashrc"
    monkeypatch.setenv("SHELL", "/bin/fish")
    assert detect_shell_rc(tmp_path).name == ".profile"


def test_mask_token() -> None:
    assert mask_token("short") == "****"
    # Only the last 4 chars — no contiguous bytes from the token's start.
    assert mask_token("ctdl_abcdef1234567890") == "…7890"


def test_mcp_block_references_env_not_secret() -> None:
    block = mcp_server_block("https://node.example/")
    assert block["url"] == "https://node.example/mcp/"
    # the token is an env reference, never a literal secret
    assert block["headers"]["Authorization"] == "Bearer ${CITADEL_MCP_ACCESS_TOKEN}"


def test_ensure_token_in_rc_adds_then_idempotent(tmp_path: Path) -> None:
    rc = tmp_path / ".zshrc"
    rc.write_text("# existing\nexport PATH=$PATH:/x\n")

    assert ensure_token_in_rc(rc, "ctdl_secret") == "added"
    body = rc.read_text()
    assert "export CITADEL_MCP_ACCESS_TOKEN='ctdl_secret'" in body
    assert "export PATH=$PATH:/x" in body  # preserved

    # re-run does not duplicate
    assert ensure_token_in_rc(rc, "ctdl_secret") == "present"
    assert rc.read_text().count("CITADEL_MCP_ACCESS_TOKEN") == 1


def test_ensure_token_rotation_updates_in_place(tmp_path: Path) -> None:
    rc = tmp_path / ".zshrc"
    assert ensure_token_in_rc(rc, "ctdl_old") == "added"
    assert ensure_token_in_rc(rc, "ctdl_new") == "updated"
    body = rc.read_text()
    assert "ctdl_new" in body and "ctdl_old" not in body
    assert body.count("CITADEL_MCP_ACCESS_TOKEN") == 1  # rewritten, not appended


def test_ensure_token_shell_quote_safe(tmp_path: Path) -> None:
    import subprocess

    rc = tmp_path / ".bashrc"
    nasty = "ctdl_a'b$(whoami)`id`"  # quotes + shell metachars
    ensure_token_in_rc(rc, nasty)
    out = subprocess.run(
        ["sh", "-c", f". {rc} >/dev/null 2>&1; printf %s \"$CITADEL_MCP_ACCESS_TOKEN\""],
        capture_output=True,
        text=True,
    )
    assert out.stdout == nasty  # sourced value is exactly the token, no execution


def test_merge_claude_settings_corrupt_allowed_envvars_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"httpHookAllowedEnvVars": "not-a-list"}))
    with pytest.raises(ValueError, match="httpHookAllowedEnvVars must be an array"):
        merge_claude_settings(path, python="/usr/bin/python3")


def test_install_pre_push_backs_up_foreign_hook(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    foreign = repo / ".git" / "hooks" / "pre-push"
    foreign.write_text("#!/bin/sh\n# husky\nnpm test\n")

    status = install_pre_push_hook(repo, python="/usr/bin/python3")
    assert "backed up" in status
    backup = repo / ".git" / "hooks" / "pre-push.citadel-bak"
    assert backup.exists() and "husky" in backup.read_text()
    assert "kb.hooks.sync_push" in foreign.read_text()  # new hook installed


def test_merge_mcp_config_preserves_other_servers(tmp_path: Path) -> None:
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"type": "stdio"}}}))

    assert merge_mcp_config(path) == "added"
    data = json.loads(path.read_text())
    assert data["mcpServers"]["other"] == {"type": "stdio"}
    assert data["mcpServers"]["citadel"]["type"] == "http"

    assert merge_mcp_config(path) == "unchanged"


def test_merge_mcp_config_corrupt_raises(tmp_path: Path) -> None:
    path = tmp_path / ".mcp.json"
    path.write_text("{ not json")
    with pytest.raises(ValueError, match="corrupt"):
        merge_mcp_config(path)


def test_merge_claude_settings_adds_then_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": []}]}}))

    assert merge_claude_settings(path, python="/usr/bin/python3") == "added"
    data = json.loads(path.read_text())
    assert "PreToolUse" in data["hooks"]  # preserved
    cmds = [
        h["command"]
        for g in data["hooks"]["SessionEnd"]
        for h in g["hooks"]
    ]
    assert any("kb.hooks.sync_session" in c for c in cmds)
    assert TOKEN_ENV in data["httpHookAllowedEnvVars"]
    start_groups = data["hooks"]["SessionStart"]
    start_cmds = [h["command"] for g in start_groups for h in g["hooks"]]
    assert any("kb.hooks.sync_start" in c for c in start_cmds)
    assert start_groups[0]["matcher"] == "startup|resume"

    assert merge_claude_settings(path, python="/usr/bin/python3") == "unchanged"
    data2 = json.loads(path.read_text())
    assert len(data2["hooks"]["SessionEnd"]) == 1  # not duplicated
    assert len(data2["hooks"]["SessionStart"]) == 1  # not duplicated


def _make_repo(tmp_path: Path) -> Path:
    # No vendored skill needed — the hook runs the bundled kb.hooks module.
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    return tmp_path


def test_install_pre_push_hook(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    assert install_pre_push_hook(repo, python="/usr/bin/python3") == "installed"
    dst = repo / ".git" / "hooks" / "pre-push"
    assert dst.exists()
    assert dst.stat().st_mode & 0o100  # executable
    assert "kb.hooks.sync_push" in dst.read_text()
    assert install_pre_push_hook(repo, python="/usr/bin/python3") == "unchanged"


def test_install_pre_push_hook_not_git(tmp_path: Path) -> None:
    assert install_pre_push_hook(tmp_path) == "skipped:not-git"


def test_bundled_hooks_are_importable_modules() -> None:
    # The published CLI installs hooks as `python -m kb.hooks.*`; the modules
    # must import and expose a runnable main() with no server deps.
    from kb.hooks import sync_push, sync_session, sync_start

    assert callable(sync_push.main)
    assert callable(sync_session.main)
    assert callable(sync_start.main)


def test_pre_push_hook_script_is_failsafe() -> None:
    from kb.onboard import pre_push_hook_script

    script = pre_push_hook_script(python="/usr/bin/python3")
    assert script.startswith("#!/bin/sh")
    assert "-m kb.hooks.sync_push" in script
    assert "|| true" in script and script.rstrip().endswith("exit 0")


def test_onboard_non_interactive_full_run(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    rc = tmp_path / ".zshrc"
    args = argparse.Namespace(
        token="ctdl_test_seat_token",
        repo=str(repo),
        shell_rc=str(rc),
        no_mcp=False,
        no_capture=True,
        non_interactive=True,
    )
    rc_code = asyncio.run(_onboard(args))
    assert rc_code == 0

    assert "CITADEL_MCP_ACCESS_TOKEN='ctdl_test_seat_token'" in rc.read_text()
    assert (repo / ".git" / "hooks" / "pre-push").exists()
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    assert any(
        "kb.hooks.sync_session" in h["command"]
        for g in settings["hooks"]["SessionEnd"]
        for h in g["hooks"]
    )
    mcp = json.loads((repo / ".mcp.json").read_text())
    assert mcp["mcpServers"]["citadel"]["url"].endswith("/mcp/")


def test_onboard_no_mcp_flag_skips_mcp(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    args = argparse.Namespace(
        token="ctdl_test",
        repo=str(repo),
        shell_rc=str(tmp_path / ".zshrc"),
        no_mcp=True,
        no_capture=True,
        non_interactive=True,
    )
    assert asyncio.run(_onboard(args)) == 0
    assert not (repo / ".mcp.json").exists()


def test_onboard_no_token_non_interactive_exits_one(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    args = argparse.Namespace(
        token=None,
        repo=str(tmp_path),
        shell_rc=str(tmp_path / ".zshrc"),
        no_mcp=False,
        no_capture=True,
        non_interactive=True,
    )
    rc = asyncio.run(_onboard(args))
    assert rc == 1
    assert "no token" in capsys.readouterr().err
