#!/usr/bin/env python3
"""Autonomous personal-KB sync for Citadel Archive — git pre-push hook.

Invoked from ``templates/git-pre-push.sh`` on every ``git push``. Snapshots
commit metadata (hash, message, author, branch, changed paths) and POSTs a
short note to the developer's private Citadel **Node** (``seat:{slug}``).

Commit snapshot payload (markdown ``data`` field):

* ``# Git commit snapshot``
* Commit full + short hash, author, ISO commit time
* Branch, remote name/ref, repo basename
* Subject + optional body (trimmed)
* ``## Changed files`` — paths from ``git diff-tree --name-only``

Design contract (same invariants as ``sync_session.py``):

* **One-token setup / personal-by-default.** ``CITADEL_MCP_ACCESS_TOKEN`` only;
  POST omits ``dataset`` so the seat-writer token routes to ``seat:{slug}``.
* **Metadata, not raw diffs.** File paths and commit message only — no patch bodies.
* **Fail-silent / non-blocking.** Always exits 0; never blocks ``git push``.
* **HTTPS only.** Refuses non-``https://`` base URLs.
* **Size cap.** Truncates to ``CITADEL_MCP_MAX_INGEST_BYTES`` (default 200000).
* **Stdlib only.**

Pre-push stdin (one line per ref)::

    <local ref> SP <local sha1> SP <remote ref> SP <remote sha1> LF

Zero sha on local side means branch delete — skipped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MAX_INGEST_BYTES = 200_000
DEFAULT_BASE_URL = "https://citadel-archive-production.up.railway.app"
TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
HTTP_TIMEOUT_SECONDS = 10
MAX_CHANGED_FILES = 80
MAX_BODY_LINES = 24


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urllib.request.install_opener(urllib.request.build_opener(_NoRedirectHandler))


def _max_ingest_bytes() -> int:
    raw_value = os.getenv("CITADEL_MCP_MAX_INGEST_BYTES")
    if not raw_value:
        return DEFAULT_MAX_INGEST_BYTES
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_INGEST_BYTES
    return max(1, value)


def _base_url() -> str:
    configured = os.getenv("CITADEL_BASE_URL")
    if configured:
        return configured.rstrip("/")
    return DEFAULT_BASE_URL


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", "ignore")


def _git_run(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or None,
        capture_output=True,
        text=True,
        timeout=8,
    )


def git_toplevel(cwd: str = "") -> str:
    try:
        result = _git_run(cwd, "rev-parse", "--show-toplevel")
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return cwd or os.getcwd()


def ref_branch_name(ref: str) -> str:
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref.rsplit("/", 1)[-1] if ref else ""


def capture_config_path() -> Path:
    """Locate ~/.citadel/capture.json (the Approved Capture Roots allowlist)."""
    override = os.getenv("CITADEL_CAPTURE_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    home = os.getenv("CITADEL_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".citadel"
    return base / "capture.json"


def _norm_path(value: str) -> str:
    """Expand ~/$VARs, make absolute, and resolve symlinks (realpath).

    Symlink resolution matters on macOS where ``git rev-parse --show-toplevel``
    reports the physical path (``/private/tmp/x``) while a config root may be the
    symlinked path (``/tmp/x``); without it, an approved repo would be skipped.
    """
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    return os.path.realpath(os.path.abspath(expanded))


def load_capture_roots() -> list[dict[str, Any]] | None:
    """Approved Capture Roots from the local config.

    Returns ``None`` only when no config file exists — the user has not opted
    into the allowlist, so the hook keeps its original always-capture behavior.
    A config that exists but is empty/corrupt returns ``[]`` (approve nothing):
    once a user opts into the allowlist we fail CLOSED, never silently re-enable
    global capture.
    """
    path = capture_config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    roots: list[dict[str, Any]] = []
    for item in data.get("roots") or []:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            continue
        roots.append(
            {
                "path": _norm_path(raw_path),
                "tags": [
                    str(tag).strip().lower()
                    for tag in (item.get("tags") or [])
                    if str(tag).strip()
                ],
            }
        )
    return roots


def matched_root(repo_root: str, roots: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the approved root containing ``repo_root``, if any."""
    target = _norm_path(repo_root)
    for root in roots:
        base = _norm_path(root["path"])
        prefix = base.rstrip(os.sep) + os.sep  # handles a root of "/" and trailing slashes
        if target == base or target.startswith(prefix):
            return root
    return None


def parse_pre_push_lines(text: str) -> list[dict[str, str]]:
    """Parse pre-push stdin into push ref dicts."""
    rows: list[dict[str, str]] = []
    zero = "0" * 40
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        if local_sha == zero:
            continue
        rows.append(
            {
                "local_ref": local_ref,
                "local_sha": local_sha,
                "remote_ref": remote_ref,
                "remote_sha": remote_sha,
            }
        )
    return rows


def _commit_fields(cwd: str, sha: str) -> dict[str, str]:
    result = _git_run(
        cwd,
        "show",
        "-s",
        "--format=%H%x00%h%x00%an%x00%ae%x00%ci%x00%s%x00%b",
        sha,
    )
    if result.returncode != 0:
        return {}
    parts = result.stdout.split("\x00", 6)
    if len(parts) < 6:
        return {}
    keys = ("hash", "short", "author", "email", "committed_at", "subject", "body")
    data = dict(zip(keys, parts + [""] * (len(keys) - len(parts)), strict=False))
    return {key: value.strip() for key, value in data.items()}


def _changed_files(cwd: str, sha: str) -> list[str]:
    result = _git_run(cwd, "diff-tree", "--no-commit-id", "--name-only", "-r", sha)
    if result.returncode != 0:
        return []
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return files[:MAX_CHANGED_FILES]


def _repo_name(cwd: str) -> str:
    top = git_toplevel(cwd)
    return os.path.basename(top.rstrip("/")) if top else ""


def format_commit_snapshot(
    *,
    commit_hash: str,
    short_hash: str,
    author: str,
    email: str,
    committed_at: str,
    subject: str,
    body: str,
    branch: str,
    remote_name: str,
    remote_ref: str,
    repo_name: str,
    changed_files: list[str],
) -> str:
    """Build the markdown note posted to Citadel (pure function for tests)."""
    lines = ["# Git commit snapshot", ""]
    lines.append(f"- **Commit:** `{short_hash}` (`{commit_hash}`)")
    if author:
        lines.append(f"- **Author:** {author} <{email}>".rstrip())
    if committed_at:
        lines.append(f"- **Committed:** {committed_at}")
    if branch:
        lines.append(f"- **Branch:** {branch}")
    if remote_name:
        remote_bit = remote_name
        if remote_ref:
            remote_bit = f"{remote_name} ({ref_branch_name(remote_ref)})"
        lines.append(f"- **Remote:** {remote_bit}")
    if repo_name:
        lines.append(f"- **Repo:** {repo_name}")

    lines.append("")
    lines.append(f"**{subject or '(no subject)'}**")
    if body:
        trimmed = [ln for ln in body.splitlines() if ln.strip()][:MAX_BODY_LINES]
        if trimmed:
            lines.append("")
            lines.extend(trimmed)

    if changed_files:
        lines.append("")
        lines.append("## Changed files")
        for path in changed_files:
            lines.append(f"- {path}")

    return "\n".join(lines).strip()


def build_commit_snapshot(
    cwd: str,
    sha: str,
    *,
    local_ref: str = "",
    remote_name: str = "",
    remote_ref: str = "",
) -> str:
    """Collect git metadata and format the snapshot note."""
    root = git_toplevel(cwd)
    fields = _commit_fields(root, sha)
    if not fields:
        return ""
    return format_commit_snapshot(
        commit_hash=fields.get("hash") or sha,
        short_hash=fields.get("short") or sha[:7],
        author=fields.get("author", ""),
        email=fields.get("email", ""),
        committed_at=fields.get("committed_at", ""),
        subject=fields.get("subject", ""),
        body=fields.get("body", ""),
        branch=ref_branch_name(local_ref) if local_ref else _git_branch(root),
        remote_name=remote_name,
        remote_ref=remote_ref,
        repo_name=_repo_name(root),
        changed_files=_changed_files(root, sha),
    )


def _git_branch(cwd: str) -> str:
    try:
        result = _git_run(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        branch = result.stdout.strip()
        if result.returncode == 0 and branch and branch != "HEAD":
            return branch
    except Exception:
        pass
    return ""


def build_tags(cwd: str, branch: str = "") -> list[str]:
    tags = ["git-push"]
    if branch:
        tags.append(branch)
    repo = _repo_name(cwd)
    if repo and repo not in tags:
        tags.append(repo)
    return tags


def post_ingest(base_url: str, token: str, data: str, tags: list[str]) -> None:
    if not base_url.lower().startswith("https://"):
        raise ValueError("refusing non-HTTPS Citadel base URL")
    url = f"{base_url}/ingest"
    body = json.dumps({"data": data, "tags": tags}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        response.read()


def _sync_one(
    cwd: str,
    sha: str,
    *,
    local_ref: str,
    remote_name: str,
    remote_ref: str,
    token: str,
    capture_tags: list[str] | tuple[str, ...] = (),
) -> None:
    note = build_commit_snapshot(
        cwd,
        sha,
        local_ref=local_ref,
        remote_name=remote_name,
        remote_ref=remote_ref,
    )
    if not note.strip():
        return
    note = _truncate_utf8(note, _max_ingest_bytes())
    branch = ref_branch_name(local_ref) if local_ref else _git_branch(cwd)
    tags = build_tags(cwd, branch)
    for tag in capture_tags:
        if tag not in tags:
            tags.append(tag)
    post_ingest(_base_url(), token, note, tags)


def run(stdin: Any, remote_name: str = "") -> int:
    """Hook entrypoint. ALWAYS returns 0 — fail-silent, non-blocking."""
    try:
        token = os.getenv(TOKEN_ENV)
        if not token:
            return 0

        cwd = git_toplevel()

        # ADR-0007 P4.3: once the user opts into the local allowlist
        # (~/.citadel/capture.json exists), only push from an Approved Capture
        # Root captures; other repos are skipped with a warning.
        roots = load_capture_roots()
        capture_tags: list[str] = []
        if roots is not None:
            match = matched_root(cwd, roots)
            if match is None:
                sys.stderr.write(
                    f"citadel: {cwd} is not an Approved Capture Root; skipping "
                    "capture (run `citadel setup` to approve it).\n"
                )
                return 0
            capture_tags = list(match["tags"])

        raw = stdin.read() if hasattr(stdin, "read") else ""
        pushes = parse_pre_push_lines(raw)

        if pushes:
            seen: set[str] = set()
            for row in pushes:
                sha = row["local_sha"]
                if sha in seen:
                    continue
                seen.add(sha)
                _sync_one(
                    cwd,
                    sha,
                    local_ref=row["local_ref"],
                    remote_name=remote_name,
                    remote_ref=row["remote_ref"],
                    token=token,
                    capture_tags=capture_tags,
                )
            return 0

        # Manual invocation (no pre-push stdin): snapshot HEAD once.
        head = _git_run(cwd, "rev-parse", "HEAD")
        if head.returncode != 0:
            return 0
        sha = head.stdout.strip()
        if not sha:
            return 0
        _sync_one(
            cwd,
            sha,
            local_ref="",
            remote_name=remote_name,
            remote_ref="",
            token=token,
            capture_tags=capture_tags,
        )
    except Exception:
        return 0
    return 0


def main() -> None:
    remote = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit(run(sys.stdin, remote_name=remote))


if __name__ == "__main__":
    main()
