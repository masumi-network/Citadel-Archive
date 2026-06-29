"""Citadel connectivity + setup status — the shared core.

One stdlib-only place that gathers "am I connected and set up?" so it can be
surfaced three ways:
  * `citadel status` / `citadel status --json`  (humans + AI agents via Bash)
  * the `citadel tui` textual dashboard          (humans, live)
  * any agent/script parsing the JSON.

All network calls are HTTPS-only and never follow redirects (the seat token is
sent to /api/session and /search). Every check captures its own failure instead
of raising, so the report always renders.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kb.capture_config import DEFAULT_NODE_URL, load_capture_config

TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
MCP_SERVER_NAME = "citadel"
SESSION_HOOK_MARKER = "kb.hooks.sync_session"
_TIMEOUT = 8.0
_SEARCH_TIMEOUT = 15.0  # cognee searches are slow when cold; non-gating anyway
_SMOKE_QUERY = "citadel status connectivity smoke"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = _TIMEOUT,
) -> dict[str, Any]:
    if not url.lower().startswith("https://"):
        raise ValueError("refusing non-HTTPS Node URL")
    data = json.dumps(payload).encode() if payload is not None else None
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read().decode()
    return json.loads(body) if body else {}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    latency_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusReport:
    node_url: str
    healthy: bool
    identity: dict[str, Any]
    checks: list[Check]
    recent: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_url": self.node_url,
            "healthy": self.healthy,
            "identity": self.identity,
            "checks": [asdict(c) for c in self.checks],
            "recent": self.recent,
        }


def _mask(token: str | None) -> str:
    if not token:
        return "(none)"
    token = token.strip()
    # Only the last 4 chars — never contiguous bytes from the secret's start.
    return f"…{token[-4:]}" if len(token) > 10 else "****"


def check_node_health(base_url: str, *, timeout: float = _TIMEOUT) -> Check:
    started = time.monotonic()
    try:
        data = _request("GET", f"{base_url.rstrip('/')}/healthz", timeout=timeout)
    except Exception as exc:
        return Check("node", ok=False, detail=str(exc))
    latency = int((time.monotonic() - started) * 1000)
    ok = bool(data.get("ok"))
    return Check("node", ok=ok, detail="healthy" if ok else "unhealthy", latency_ms=latency)


def check_auth(base_url: str, token: str | None, *, timeout: float = _TIMEOUT) -> Check:
    if not token:
        return Check("auth", ok=False, detail="no token (CITADEL_MCP_ACCESS_TOKEN unset)")
    try:
        data = _request(
            "GET", f"{base_url.rstrip('/')}/api/session", token=token, timeout=timeout
        )
    except Exception as exc:
        return Check("auth", ok=False, detail=str(exc))
    identity = {
        "seat_slug": data.get("seat_slug"),
        "node_label": data.get("node_label"),
        "role": data.get("role"),
        "capabilities": data.get("capabilities", {}),
        "actor": (data.get("actor") or {}).get("name"),
    }
    return Check("auth", ok=bool(data.get("ok")), detail="valid", data=identity)


def check_search(base_url: str, token: str | None, *, timeout: float = _SEARCH_TIMEOUT) -> Check:
    if not token:
        return Check("search", ok=False, detail="skipped (no token)")
    try:
        data = _request(
            "POST",
            f"{base_url.rstrip('/')}/search",
            token=token,
            payload={"query": _SMOKE_QUERY, "top_k": 1},
            timeout=timeout,
        )
    except TimeoutError:
        return Check("search", ok=False, detail=f"timed out (>{int(timeout)}s, node warming up)")
    except Exception as exc:
        return Check("search", ok=False, detail=str(exc))
    results = data.get("results")
    if results is None:
        results = data.get("matches")
    count = len(results) if isinstance(results, list) else 0
    return Check("search", ok=True, detail=f"{count} result(s)", data={"count": count})


def search_node(
    base_url: str,
    token: str,
    query: str,
    top_k: int = 10,
    *,
    timeout: float = _SEARCH_TIMEOUT,
) -> list[dict[str, Any]]:
    """POST a query to the Node's /search (the same endpoint MCP citadel_search uses).

    Zero-dep, HTTPS-only. The Node resolves the dataset from the token's seat, so
    callers pass only query + top_k. Returns the results list (``results`` or the
    legacy ``matches`` key), or [] if the shape is unexpected.
    """
    data = _request(
        "POST",
        f"{base_url.rstrip('/')}/search",
        token=token,
        payload={"query": query, "top_k": top_k},
        timeout=timeout,
    )
    results = data.get("results")
    if results is None:
        results = data.get("matches")
    return results if isinstance(results, list) else []


def check_local_setup(repo: Path, config_path: Path | None = None) -> list[Check]:
    checks: list[Check] = []
    checks.append(
        Check("token", ok=bool(os.getenv(TOKEN_ENV)), detail=_mask(os.getenv(TOKEN_ENV)))
    )

    mcp_path = repo / ".mcp.json"
    mcp_ok = False
    if mcp_path.exists():
        try:
            servers = (json.loads(mcp_path.read_text()).get("mcpServers") or {})
            mcp_ok = MCP_SERVER_NAME in servers
        except ValueError:
            mcp_ok = False
    checks.append(Check("mcp", ok=mcp_ok, detail="citadel server present" if mcp_ok else "not configured"))

    pre_push = repo / ".git" / "hooks" / "pre-push"
    checks.append(
        Check("pre_push_hook", ok=pre_push.exists(), detail="installed" if pre_push.exists() else "missing")
    )

    settings = repo / ".claude" / "settings.json"
    session_ok = False
    if settings.exists():
        try:
            session_ok = SESSION_HOOK_MARKER in settings.read_text()
        except OSError:
            session_ok = False
    checks.append(
        Check("session_hook", ok=session_ok, detail="installed" if session_ok else "missing")
    )

    try:
        config = load_capture_config(config_path) if config_path else load_capture_config()
    except ValueError as exc:
        # A corrupt capture.json must not break the whole status report.
        checks.append(Check("capture_roots", ok=False, detail=f"corrupt config ({exc})"))
        return checks
    if config.roots:
        tags = sorted({tag for root in config.roots for tag in root.tags})
        detail = f"{len(config.roots)} root(s): {', '.join(tags)}"
    else:
        detail = "none (push hook captures every repo)"
    checks.append(Check("capture_roots", ok=True, detail=detail, data={"count": len(config.roots)}))
    return checks


def fetch_recent(
    base_url: str, token: str | None, *, limit: int = 5, timeout: float = _TIMEOUT
) -> list[dict[str, Any]]:
    if not token:
        return []
    try:
        data = _request(
            "GET",
            f"{base_url.rstrip('/')}/api/contributions/recent?mine=true&limit={limit}",
            token=token,
            timeout=timeout,
        )
    except Exception:
        return []
    return data.get("contributions") or []


def gather_status(
    base_url: str = DEFAULT_NODE_URL,
    token: str | None = None,
    *,
    repo: Path | None = None,
    config_path: Path | None = None,
    with_search: bool = True,
    with_recent: bool = True,
    timeout: float = _TIMEOUT,
) -> StatusReport:
    base_url = base_url.rstrip("/")
    repo = repo or Path.cwd()

    node = check_node_health(base_url, timeout=timeout)
    auth = check_auth(base_url, token, timeout=timeout)
    checks = [node, auth]
    if with_search:
        checks.append(check_search(base_url, token))  # uses its own longer timeout
    checks.extend(check_local_setup(repo, config_path))

    recent = fetch_recent(base_url, token, timeout=timeout) if with_recent else []
    return StatusReport(
        node_url=base_url,
        healthy=node.ok and auth.ok,
        identity=auth.data,
        checks=checks,
        recent=recent,
    )


# Checks split into two sections; everything not here is "Local setup".
_CONNECTIVITY = ("node", "auth", "search")
# Human labels — the raw snake_case names read like debug output.
_CHECK_LABELS = {
    "node": "Node",
    "auth": "Auth",
    "search": "Search",
    "token": "Token",
    "mcp": "MCP server",
    "pre_push_hook": "Pre-push hook",
    "session_hook": "SessionEnd hook",
    "capture_roots": "Capture roots",
}


def render_text(report: StatusReport, *, color: bool = False) -> str:
    from kb.banner import mark, paint

    ident = report.identity
    seat = ident.get("seat_slug") or ident.get("actor") or "—"
    role = ident.get("role") or "—"
    lines = [
        f"seat: {paint(str(seat), 'bold', enable=color)}   role: {role}",
        paint(f"node: {report.node_url}", "dim", enable=color),
        "",
    ]

    def _row(check: Check) -> str:
        label = _CHECK_LABELS.get(check.name, check.name)
        latency = f"  ({check.latency_ms}ms)" if check.latency_ms is not None else ""
        return f"  {mark(check.ok, enable=color)} {label:<16} {check.detail}{latency}"

    conn = [c for c in report.checks if c.name in _CONNECTIVITY]
    local = [c for c in report.checks if c.name not in _CONNECTIVITY]
    if conn:
        lines.append(paint("Connectivity", "bold", enable=color))
        lines.extend(_row(c) for c in conn)
        lines.append("")
    if local:
        lines.append(paint("Local setup", "bold", enable=color))
        lines.extend(_row(c) for c in local)

    if report.recent:
        lines.append("")
        lines.append("Recent activity")
        for item in report.recent[:5]:
            when = item.get("created_at") or item.get("timestamp") or ""
            label = item.get("title") or item.get("action") or item.get("detail") or "—"
            lines.append(f"  · {str(when)[:19]}  {label}")

    lines.append("")
    total = len(report.checks)
    ok_count = sum(1 for c in report.checks if c.ok)
    failing = [_CHECK_LABELS.get(c.name, c.name) for c in report.checks if not c.ok]
    if report.healthy and not failing:
        lines.append(paint("All systems go.", "green", enable=color))
    elif report.healthy:
        # Connected to the Node, but some local setup is still incomplete.
        lines.append(paint("All systems go.", "green", enable=color))
        lines.append(
            paint(f"  setup incomplete ({ok_count}/{total}) — {', '.join(failing)}", "yellow", enable=color)
        )
    else:
        lines.append(
            paint(
                f"Not fully connected ({ok_count}/{total} ok) — check: "
                f"{', '.join(failing)}.  Try `citadel onboard`.",
                "yellow",
                enable=color,
            )
        )
    return "\n".join(lines)
