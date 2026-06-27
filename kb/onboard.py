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
import sys
from pathlib import Path
from typing import Any

from kb.capture_config import DEFAULT_NODE_URL

TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
MCP_SERVER_NAME = "citadel"
PUSH_MODULE = "kb.hooks.sync_push"
SESSION_MODULE = "kb.hooks.sync_session"
# Used both to install the SessionEnd hook and to detect it on re-run.
_SESSION_HOOK_MARKER = SESSION_MODULE


def _hook_python() -> str:
    """The interpreter that has `kb` installed (so the hooks can import it)."""
    return sys.executable or "python3"


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
    # Reveal only the last 4 chars — no contiguous bytes from the secret's start.
    token = token.strip()
    return f"…{token[-4:]}" if len(token) > 10 else "****"


def _sh_single_quote(value: str) -> str:
    """POSIX-safe single-quoting (close, escaped quote, reopen) for shell rc."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def mcp_server_block(base_url: str = DEFAULT_NODE_URL) -> dict[str, Any]:
    return {
        "type": "http",
        "url": f"{base_url.rstrip('/')}/mcp/",
        "headers": {"Authorization": "Bearer ${" + TOKEN_ENV + "}"},
    }


def _session_hook(python: str | None = None) -> dict[str, Any]:
    py = python or _hook_python()
    return {
        "type": "command",
        "command": f'"{py}" -m {SESSION_MODULE}',
        "timeout": 20,
        "allowedEnvVars": [TOKEN_ENV],
    }


def pre_push_hook_script(python: str | None = None) -> str:
    """Self-contained git pre-push hook that runs the bundled module, fail-silent."""
    py = python or _hook_python()
    return (
        "#!/bin/sh\n"
        "# Citadel autosync — installed by `citadel onboard`.\n"
        "# Fail-silent: never blocks `git push`.\n"
        f'"{py}" -m {PUSH_MODULE} "$@" 2>/dev/null || true\n'
        "exit 0\n"
    )


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
    """Write ``export CITADEL_MCP_ACCESS_TOKEN=…`` to the shell rc.

    Idempotent, and rotation-aware: if the var is already exported with a
    *different* value, that line is rewritten (returns ``updated``) instead of
    being left stale. The token is single-quoted POSIX-safely.
    """
    token = token.strip()
    export_line = f"export {TOKEN_ENV}={_sh_single_quote(token)}"
    lines = rc_path.read_text().splitlines() if rc_path.exists() else []
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith(f"export {TOKEN_ENV}=") or stripped.startswith(f"{TOKEN_ENV}="):
            if stripped == export_line:
                return "present"
            lines[index] = export_line
            rc_path.write_text("\n".join(lines) + "\n")
            return "updated"
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    with rc_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n# Citadel seat token (added by `citadel onboard`)\n{export_line}\n")
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


def merge_claude_settings(path: Path, python: str | None = None) -> str:
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
        session_end.append({"hooks": [_session_hook(python)]})
        changed = True
    allowed = data.setdefault("httpHookAllowedEnvVars", [])
    if not isinstance(allowed, list):
        raise ValueError(f"corrupt {path}: httpHookAllowedEnvVars must be an array")
    if TOKEN_ENV not in allowed:
        allowed.append(TOKEN_ENV)
        changed = True
    if not changed:
        return "unchanged"
    _write_json(path, data)
    return "added"


def install_pre_push_hook(repo: Path, python: str | None = None) -> str:
    """Install a self-contained pre-push hook that runs the bundled sync module.

    Merge-not-clobber: a pre-existing *foreign* hook (not Citadel-managed) is
    backed up to ``pre-push.citadel-bak`` rather than silently destroyed.
    """
    if not (repo / ".git").is_dir():
        return "skipped:not-git"
    dst = repo / ".git" / "hooks" / "pre-push"
    payload = pre_push_hook_script(python)
    result = "installed"
    if dst.exists():
        existing = dst.read_text()
        if existing == payload:
            return "unchanged"
        if "Citadel autosync" not in existing:
            dst.with_name("pre-push.citadel-bak").write_text(existing)
            result = "installed (backed up existing hook → pre-push.citadel-bak)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(payload)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return result
