#!/usr/bin/env python3
"""Warm-start context for Citadel — SessionStart hook.

Invoked by a Claude Code ``SessionStart`` hook (matcher ``startup|resume``).
Fetches a compact "recent in the vault" digest from the developer's Citadel node
and prints it to stdout, which Claude Code injects as session context — so a new
session opens already aware of recent org activity, without the agent having to
query for it. This is the read-side counterpart to the ``SessionEnd`` distiller
(``kb/hooks/sync_session.py``).

Design contract (reviewers verify these invariants):

* **Token from env only.** ``CITADEL_MCP_ACCESS_TOKEN`` is read solely from the
  environment and never printed (the digest is recent *contribution* metadata,
  not the token).
* **Fail-silent / non-blocking.** Any problem -> exit 0 with NO output, so the
  hook can never delay or break session start, nor inject an error.
* **Quiet when empty.** Injects ONLY when there is recent activity; an empty or
  unreachable vault prints nothing, so it is never noise-for-nothing.
* **HTTPS only, no redirects.** The token is never sent over plaintext.
* **Stdlib only.**

Hook payload (read from STDIN as JSON): ``session_id``, ``transcript_path``,
``cwd``, ``hook_event_name``, ``source`` — all unused here (we just drain it).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://citadel-archive-production.up.railway.app"
TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
HTTP_TIMEOUT_SECONDS = 5
RECENT_LIMIT = 8


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so a 3xx (esp. https->http) can't leak the token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urllib.request.install_opener(urllib.request.build_opener(_NoRedirectHandler))


def _base_url() -> str:
    configured = os.getenv("CITADEL_BASE_URL")
    return configured.rstrip("/") if configured else DEFAULT_BASE_URL


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


def fetch_recent(base_url: str, token: str, *, limit: int = RECENT_LIMIT) -> list[dict[str, Any]]:
    if not base_url.lower().startswith("https://"):
        raise ValueError("refusing non-HTTPS Citadel base URL")
    url = f"{base_url}/api/contributions/recent?mine=true&limit={limit}"
    request = urllib.request.Request(  # noqa: S310 - https asserted above
        url,
        method="GET",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode()
    data = json.loads(body) if body else {}
    items = data.get("contributions") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def format_digest(items: list[dict[str, Any]]) -> str:
    """A short, plain-text digest. Stdout is injected verbatim as context."""
    lines = ["# Citadel vault — recent activity", ""]
    for item in items[:RECENT_LIMIT]:
        if not isinstance(item, dict):
            continue
        when = str(item.get("created_at") or item.get("timestamp") or "")[:10]
        label = item.get("title") or item.get("action") or item.get("detail") or "—"
        label = " ".join(str(label).split())[:120]
        lines.append(f"- {when}  {label}" if when else f"- {label}")
    return "\n".join(lines)


def run(stream_in: Any) -> int:
    """Hook entrypoint. ALWAYS returns 0 — fail-silent, non-blocking."""
    try:
        read_hook_payload(stream_in)  # drain stdin; fields unused
        token = os.getenv(TOKEN_ENV)
        if not token:
            return 0
        items = fetch_recent(_base_url(), token)
        if not items:
            return 0  # nothing to inject -> stay silent
        sys.stdout.write(format_digest(items) + "\n")
    except Exception:
        # Fail-silent: never block session start, never surface the token.
        return 0
    return 0


def main() -> None:
    sys.exit(run(sys.stdin))


if __name__ == "__main__":
    main()
