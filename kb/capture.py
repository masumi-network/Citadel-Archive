"""`citadel capture` — summarize Approved Capture Roots and POST to the seat Node.

ADR-0007 P4.2. v1 is summary-based (git metadata + README blurb), not a raw file
dump: payloads stay small and we avoid shipping file bodies. The server Security
Finding gate and per-seat Capture Policy deny globs remain the authoritative
secret guard on the Node side.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from kb.capture_config import CaptureRoot, normalize_tags

CAPTURE_TAG = "capture"
_README_NAMES = ("README.md", "README.rst", "README.txt", "README")


def capture_token() -> str:
    """Resolve the seat write token from the environment (never stored on disk)."""
    return (
        os.getenv("CITADEL_MCP_ACCESS_TOKEN")
        or os.getenv("CITADEL_WRITER_KEYS", "").split(",")[0].strip()
        or os.getenv("CITADEL_ADMIN_KEY", "")
    )


def _git(root: str, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _readme_blurb(path: Path, limit: int = 6) -> str:
    for name in _README_NAMES:
        readme = path / name
        if not readme.exists():
            continue
        lines: list[str] = []
        for line in readme.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
            if len(lines) >= limit:
                break
        return " ".join(lines)
    return ""


def summarize_root(root: CaptureRoot) -> str:
    """Build a compact markdown summary of a single approved root."""
    path = Path(root.path)
    name = path.name or root.path
    lines = [
        f"# Capture summary: {name}",
        "",
        f"- Path: `{root.path}`",
        f"- Capture Root Tags: {', '.join(root.tags)}",
    ]
    if not path.exists():
        lines.append("- Status: path not found on this machine")
        return "\n".join(lines)

    blurb = _readme_blurb(path)
    if (path / ".git").exists():
        remote = _git(root.path, "remote", "get-url", "origin")
        branch = _git(root.path, "rev-parse", "--abbrev-ref", "HEAD")
        last = _git(root.path, "log", "-1", "--format=%h %s")
        recent = _git(root.path, "log", "-5", "--format=- %h %s")
        if remote:
            lines.append(f"- Remote: {remote}")
        if branch:
            lines.append(f"- Branch: `{branch}`")
        if last:
            lines.append(f"- Latest: {last}")
        if blurb:
            lines += ["", "## README", blurb]
        if recent:
            lines += ["", "## Recent commits", recent]
    else:
        lines.append("- Status: non-git folder")
        if blurb:
            lines += ["", "## README", blurb]
    return "\n".join(lines)


def build_capture_payload(root: CaptureRoot) -> dict[str, Any]:
    """Ingest payload for a root: summary plus its tags and a `capture` marker."""
    tags = list(normalize_tags([*root.tags, CAPTURE_TAG]))
    return {"data": summarize_root(root), "tags": tags}


def post_capture(
    node_url: str, token: str, payload: dict[str, Any], *, timeout: float = 120
) -> dict[str, Any]:
    """POST a capture summary to the Node `/ingest` endpoint."""
    req = urllib.request.Request(
        f"{node_url.rstrip('/')}/ingest",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted Node URL)
        return json.loads(resp.read().decode())
