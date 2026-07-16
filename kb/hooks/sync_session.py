#!/usr/bin/env python3
"""Autonomous personal-KB sync for Citadel Archive — SessionEnd hook.

This script is invoked by a Claude Code ``SessionEnd`` hook (see
``templates/claude-settings.json``). On every session close it distills a
short, deterministic note from the session transcript and POSTs it to the
developer's PRIVATE Citadel node (``seat:{slug}``), so org devs get
zero-per-session knowledge capture after a one-time token setup.

Design contract (reviewers verify these invariants):

* **One-token setup / personal-by-default.** The only secret is
  ``CITADEL_MCP_ACCESS_TOKEN`` (a ``ctdl_`` seat-writer token), read solely
  from the environment. A seat-writer token has ``default_dataset=seat:{slug}``,
  so the POST sends **NO** ``dataset`` field — the server's
  ``resolve_write_targets`` routes the write to the dev's private node. The
  token is never printed, echoed, or written to any file.
* **Distilled, not raw.** We emit a short deterministic summary (1-2 line
  recap, key decisions, files changed, notable facts) built with plain string
  logic — there is **no local LLM call**. Server-side LLM enrichment
  (``CITADEL_LLM_ENRICHMENT_ENABLED``) handles any further structuring.
* **Fail-silent / non-blocking.** Every failure is swallowed; the script always
  exits 0 and never raises out of the hook, so it can never block session close.
* **HTTPS only.** The POST is refused unless the base URL is ``https://``.
* **Size cap.** The note is truncated to ``CITADEL_MCP_MAX_INGEST_BYTES``
  (default 200000) before sending.
* **Stdlib only.** Uses ``urllib`` from the standard library — no extra deps.

Hook payload (read from STDIN as JSON): ``transcript_path``, ``cwd``,
``session_id``, ``hook_event_name``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from typing import Any

# Mirror kb/mcp_server.py: DEFAULT_MAX_INGEST_BYTES = 200_000.
DEFAULT_MAX_INGEST_BYTES = 200_000
DEFAULT_BASE_URL = "https://citadel-archive-production.up.railway.app"
TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
HTTP_TIMEOUT_SECONDS = 10


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow HTTP redirects.

    A 3xx response (especially an https->http downgrade) must never make urllib
    re-send the ``Authorization`` header over plaintext. Returning ``None`` makes
    urllib raise ``HTTPError`` for the 3xx instead of following it; ``run()``
    swallows that as a silent failure. The HTTPS guard in ``post_ingest`` only
    checks the initial URL, so this closes the redirect token-leak gap.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# One-shot hook process: install a no-redirect opener so the simple ``urlopen``
# call site (and its tests) keep working while redirects are refused globally.
urllib.request.install_opener(urllib.request.build_opener(_NoRedirectHandler))


def _max_ingest_bytes() -> int:
    """Resolve the size cap, mirroring kb/mcp_server.py._max_ingest_bytes."""
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
    """Truncate ``text`` so its UTF-8 encoding is at most ``max_bytes`` bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Cut on a byte boundary, then drop any partial trailing multibyte char.
    return encoded[:max_bytes].decode("utf-8", "ignore")


def read_hook_payload(stream: Any) -> dict[str, Any]:
    """Parse the hook JSON from STDIN defensively; return {} on any problem."""
    try:
        raw = stream.read()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _iter_transcript(transcript_path: str) -> list[dict[str, Any]]:
    """Read a transcript JSONL file, skipping malformed lines. Never raises."""
    entries: list[dict[str, Any]] = []
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    # Malformed line -> skip, keep going.
                    continue
                if isinstance(obj, dict):
                    entries.append(obj)
    except Exception:
        return entries
    return entries


def _content_blocks(entry: dict[str, Any]) -> list[Any]:
    message = entry.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _text_of(block: Any) -> str:
    if isinstance(block, dict) and isinstance(block.get("text"), str):
        return block["text"].strip()
    if isinstance(block, str):
        return block.strip()
    return ""


def _first_user_prompt(entries: list[dict[str, Any]]) -> str:
    for entry in entries:
        if entry.get("type") != "user":
            continue
        for block in _content_blocks(entry):
            text = _text_of(block)
            # Skip tool_result echoes that arrive as user-role entries.
            if isinstance(block, dict) and block.get("type") == "tool_result":
                continue
            if text:
                return text
    return ""


def distill_transcript(entries: list[dict[str, Any]]) -> str:
    """Build a short, deterministic note from transcript entries (NO LLM).

    Sections: a 1-2 line recap from the first user prompt + last assistant
    text, files touched (Edit/Write/MultiEdit/NotebookEdit), and a small
    sample of decision-ish assistant statements. Pure string logic.
    """
    files: list[str] = []
    seen_files: set[str] = set()
    last_assistant_text = ""
    decisions: list[str] = []
    decision_markers = (
        "decided",
        "decision",
        "chose",
        "we'll use",
        "going with",
        "approach",
        "instead of",
        "root cause",
    )

    for entry in entries:
        etype = entry.get("type")
        for block in _content_blocks(entry):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                name = block.get("name")
                inp = block.get("input")
                if isinstance(inp, dict) and name in (
                    "Edit",
                    "Write",
                    "MultiEdit",
                    "NotebookEdit",
                ):
                    path = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(path, str) and path and path not in seen_files:
                        seen_files.add(path)
                        files.append(path)
            elif btype == "text" and etype == "assistant":
                text = _text_of(block)
                if not text:
                    continue
                last_assistant_text = text
                lowered = text.lower()
                if any(marker in lowered for marker in decision_markers):
                    # Keep the first sentence-ish slice only.
                    snippet = text.replace("\n", " ").strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200].rstrip() + "..."
                    if snippet not in decisions:
                        decisions.append(snippet)

    first_prompt = _first_user_prompt(entries)

    lines: list[str] = ["# Dev session note"]

    recap_bits: list[str] = []
    if first_prompt:
        recap = first_prompt.replace("\n", " ").strip()
        if len(recap) > 280:
            recap = recap[:280].rstrip() + "..."
        recap_bits.append(f"Task: {recap}")
    if last_assistant_text:
        outcome = last_assistant_text.replace("\n", " ").strip()
        if len(outcome) > 280:
            outcome = outcome[:280].rstrip() + "..."
        recap_bits.append(f"Outcome: {outcome}")
    if not recap_bits:
        recap_bits.append("Session captured (no extractable prompt/outcome text).")
    lines.append("")
    lines.extend(recap_bits)

    if decisions:
        lines.append("")
        lines.append("## Key decisions / facts")
        for item in decisions[:8]:
            lines.append(f"- {item}")

    if files:
        lines.append("")
        lines.append("## Files changed")
        for path in files[:40]:
            lines.append(f"- {path}")

    return "\n".join(lines).strip()


def _git_branch(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = result.stdout.strip()
        if result.returncode == 0 and branch and branch != "HEAD":
            return branch
    except Exception:
        pass
    return ""


def _repo_name(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=5,
        )
        top = result.stdout.strip()
        if result.returncode == 0 and top:
            return os.path.basename(top)
    except Exception:
        pass
    if cwd:
        return os.path.basename(cwd.rstrip("/"))
    return ""


def build_tags(cwd: str) -> list[str]:
    tags = ["dev-session"]
    branch = _git_branch(cwd)
    if branch:
        tags.append(branch)
    repo = _repo_name(cwd)
    if repo and repo not in tags:
        tags.append(repo)
    return tags


def post_ingest(base_url: str, token: str, data: str, tags: list[str]) -> None:
    """POST {data, tags} to {base}/ingest over HTTPS. No dataset field.

    Personal-by-default: omitting ``dataset`` lets the seat-writer token's
    ``default_dataset=seat:{slug}`` route the write to the dev's private node.
    HTTPS is required. Raises on any transport problem; the caller swallows it.
    """
    if not base_url.lower().startswith("https://"):
        # HTTPS-only invariant: never send a token over plaintext.
        raise ValueError("refusing non-HTTPS Citadel base URL")
    url = f"{base_url}/ingest"
    body = json.dumps({"data": data, "tags": tags}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - scheme is asserted https above
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        # Drain so the connection closes cleanly; status is enough.
        response.read()


def run(stream_in: Any) -> int:
    """Hook entrypoint. ALWAYS returns 0 — fail-silent, non-blocking."""
    try:
        payload = read_hook_payload(stream_in)
        token = os.getenv(TOKEN_ENV)
        if not token:
            # No token configured -> nothing to sync. Clean no-op exit.
            return 0

        transcript_path = payload.get("transcript_path")
        cwd = payload.get("cwd") or os.getcwd()
        entries = (
            _iter_transcript(transcript_path)
            if isinstance(transcript_path, str) and transcript_path
            else []
        )

        note = distill_transcript(entries)
        if not note.strip():
            return 0

        note = _truncate_utf8(note, _max_ingest_bytes())
        tags = build_tags(cwd if isinstance(cwd, str) else "")

        post_ingest(_base_url(), token, note, tags)
        # DX-5 receipt: make the silent session capture visible (never raises,
        # never surfaces the token; any failure is caught below).
        from kb.hooks.receipt import write_receipt

        write_receipt("session", "session captured → your Node")
    except Exception:
        # Fail-silent: never block session close, never surface the token.
        return 0
    return 0


def main() -> None:
    sys.exit(run(sys.stdin))


if __name__ == "__main__":
    main()
