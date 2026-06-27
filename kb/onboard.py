"""`citadel onboard` — one-shot teammate setup.

Collapses the manual rollout (token + git hook + SessionEnd hook + MCP server +
capture roots) into a single idempotent command. Every step is safe to re-run
and merges into existing config rather than clobbering it.

Security: the seat token is written to exactly one place (the shell rc). The
`.mcp.json` block references it via ``${CITADEL_MCP_ACCESS_TOKEN}`` — the secret
is never duplicated into project config.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from kb.capture_config import DEFAULT_NODE_URL

TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
MCP_SERVER_NAME = "citadel"
_SESSION_HOOK_MARKER = "skills/citadel-proactive-ingest/scripts/sync_session.py"
_PRE_PUSH_TEMPLATE = "skills/citadel-proactive-ingest/templates/git-pre-push.sh"


def git_root_or_cwd() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def detect_shell_rc(home: Path | None = None) -> Path:
    home = home or Path.home()
    shell = os.getenv("SHELL", "")
    if "zsh" in shell:
        return home / ".zshrc"
    if "bash" in shell:
        return home / ".bashrc"
    return home / ".profile"


def mask_token(token: str) -> str:
    token = token.strip()
    if len(token) <= 10:
        return "****"
    return f"{token[:6]}…{token[-4:]}"


def mcp_server_block(base_url: str = DEFAULT_NODE_URL) -> dict[str, Any]:
    return {
        "type": "http",
        "url": f"{base_url.rstrip('/')}/mcp/",
        "headers": {"Authorization": "Bearer ${" + TOKEN_ENV + "}"},
    }


def _session_hook() -> dict[str, Any]:
    return {
        "type": "command",
        "command": f'python3 "$CLAUDE_PROJECT_DIR/{_SESSION_HOOK_MARKER}"',
        "timeout": 20,
        "allowedEnvVars": [TOKEN_ENV],
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ValueError(f"corrupt {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"corrupt {path}: expected a JSON object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def ensure_token_in_rc(rc_path: Path, token: str) -> str:
    """Append ``export CITADEL_MCP_ACCESS_TOKEN=…`` to the shell rc, idempotently."""
    token = token.strip()
    existing = rc_path.read_text() if rc_path.exists() else ""
    for raw in existing.splitlines():
        stripped = raw.strip()
        if stripped.startswith(f"export {TOKEN_ENV}=") or stripped.startswith(f"{TOKEN_ENV}="):
            return "present"
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    with rc_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n# Citadel seat token (added by `citadel onboard`)\nexport {TOKEN_ENV}='{token}'\n")
    return "added"


def merge_mcp_config(path: Path, base_url: str = DEFAULT_NODE_URL) -> str:
    """Merge the citadel MCP server into .mcp.json, preserving other servers."""
    data = _load_json_object(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"corrupt {path}: mcpServers must be an object")
    block = mcp_server_block(base_url)
    if servers.get(MCP_SERVER_NAME) == block:
        return "unchanged"
    status = "updated" if MCP_SERVER_NAME in servers else "added"
    servers[MCP_SERVER_NAME] = block
    _write_json(path, data)
    return status


def merge_claude_settings(path: Path) -> str:
    """Merge the SessionEnd hook into .claude/settings.json without duplicating it."""
    data = _load_json_object(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"corrupt {path}: hooks must be an object")
    session_end = hooks.setdefault("SessionEnd", [])
    if not isinstance(session_end, list):
        raise ValueError(f"corrupt {path}: hooks.SessionEnd must be an array")

    has_marker = any(
        isinstance(group, dict)
        and any(
            isinstance(hook, dict) and _SESSION_HOOK_MARKER in str(hook.get("command", ""))
            for hook in group.get("hooks", [])
        )
        for group in session_end
    )
    changed = False
    if not has_marker:
        session_end.append({"hooks": [_session_hook()]})
        changed = True
    allowed = data.setdefault("httpHookAllowedEnvVars", [])
    if isinstance(allowed, list) and TOKEN_ENV not in allowed:
        allowed.append(TOKEN_ENV)
        changed = True
    if not changed:
        return "unchanged"
    _write_json(path, data)
    return "added"


def install_pre_push_hook(repo: Path) -> str:
    """Copy the vendored pre-push template into .git/hooks/pre-push (executable)."""
    if not (repo / ".git").is_dir():
        return "skipped:not-git"
    src = repo / _PRE_PUSH_TEMPLATE
    if not src.exists():
        return "skipped:no-template"
    dst = repo / ".git" / "hooks" / "pre-push"
    payload = src.read_text()
    if dst.exists() and dst.read_text() == payload:
        return "unchanged"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(payload)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return "installed"
