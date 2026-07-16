"""Citadel connectivity + setup status — the shared core.

One stdlib-only place that gathers "am I connected and set up?" so it can be
surfaced two ways:
  * `citadel status` / `citadel status --json`  (humans + AI agents via Bash)
  * any agent/script parsing the JSON.

All network calls are HTTPS-only and never follow redirects (the seat token is
sent to /api/session and /search). Every check captures its own failure instead
of raising, so the report always renders.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kb.capture_config import DEFAULT_NODE_URL, load_capture_config

TOKEN_ENV = "CITADEL_MCP_ACCESS_TOKEN"
MCP_SERVER_NAME = "citadel"
SESSION_HOOK_MARKER = "kb.hooks.sync_session"
_TIMEOUT = 8.0
_SEARCH_TIMEOUT = 15.0  # cognee searches are slow when cold; non-gating anyway
_INGEST_TIMEOUT = 60.0  # /ingest does real write work (and cold nodes are slow)
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


def _humanize_net_error(exc: Exception) -> str:
    """Human words for the common network failures — raw urllib reasons read
    like C errno dumps ('nodename nor servname provided, or not known')."""
    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, urllib.error.HTTPError):
        return text
    if "nodename nor servname" in lowered or "name or service not known" in lowered or "getaddrinfo" in lowered:
        return "cannot resolve host"
    if "connection refused" in lowered:
        return "connection refused"
    if isinstance(exc, TimeoutError) or "timed out" in lowered:
        return "timed out"
    return text


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
    repo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_url": self.node_url,
            "healthy": self.healthy,
            "identity": self.identity,
            "checks": [asdict(c) for c in self.checks],
            "recent": self.recent,
            "repo": self.repo,
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
        return Check("node", ok=False, detail=_humanize_net_error(exc))
    latency = int((time.monotonic() - started) * 1000)
    ok = bool(data.get("ok"))
    return Check("node", ok=ok, detail="healthy" if ok else "unhealthy", latency_ms=latency)


def check_auth(base_url: str, token: str | None, *, timeout: float = _TIMEOUT) -> Check:
    if not token:
        return Check("auth", ok=False, detail="no token (CITADEL_MCP_ACCESS_TOKEN unset)")
    started = time.monotonic()
    try:
        data = _request(
            "GET", f"{base_url.rstrip('/')}/api/session", token=token, timeout=timeout
        )
    except Exception as exc:
        return Check("auth", ok=False, detail=_humanize_net_error(exc))
    latency = int((time.monotonic() - started) * 1000)
    identity = {
        "seat_slug": data.get("seat_slug"),
        "node_label": data.get("node_label"),
        "role": data.get("role"),
        "capabilities": data.get("capabilities", {}),
        "actor": (data.get("actor") or {}).get("name"),
    }
    return Check("auth", ok=bool(data.get("ok")), detail="valid", latency_ms=latency, data=identity)


def check_search(base_url: str, token: str | None, *, timeout: float = _SEARCH_TIMEOUT) -> Check:
    if not token:
        return Check("search", ok=False, detail="skipped (no token)")
    started = time.monotonic()
    try:
        data = _request(
            "POST",
            f"{base_url.rstrip('/')}/search",
            token=token,
            payload={"query": _SMOKE_QUERY, "top_k": 1},
            timeout=timeout,
        )
    except TimeoutError:
        return Check(
            "search", ok=False,
            detail=f"timed out after {int(timeout)}s — node warming up",
            data={"timed_out": True},
        )
    except Exception as exc:
        return Check("search", ok=False, detail=_humanize_net_error(exc))
    latency = int((time.monotonic() - started) * 1000)
    results = data.get("results")
    if results is None:
        results = data.get("matches")
    count = len(results) if isinstance(results, list) else 0
    # A zero-result smoke search means the read path is up but the data plane is
    # empty/broken — report it honestly instead of always-green (#27).
    return Check("search", ok=count > 0, detail=f"{count} result(s)", latency_ms=latency, data={"count": count})


def check_corpus(base_url: str, token: str | None, *, timeout: float = _TIMEOUT) -> Check | None:
    """Data-plane corpus health from the Node's honest /readyz (#27).

    Returns None (non-gating) when there is no token or /readyz is unreachable;
    /readyz answers 503 with a body when the corpus gate or canary is RED, so we
    parse the body off the HTTPError too.
    """
    if not token:
        return None
    url = f"{base_url.rstrip('/')}/readyz"
    try:
        data = _request("GET", url, token=token, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 503:
            return None
        try:
            data = json.loads(exc.read().decode() or "{}")
        except (ValueError, OSError):
            return None
    except Exception:
        return None
    corpus = data.get("corpus") or {}
    canary = data.get("canary")
    indexed = corpus.get("indexed_docs")
    tracked = corpus.get("tracked_sources")
    ok = bool(corpus.get("ok", True)) and (canary is None or bool(canary.get("ok", True)))
    detail = "ok" if indexed is None else f"{indexed} indexed / {tracked} tracked"
    return Check("corpus", ok=ok, detail=detail, data={"canary": canary})


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


def ingest_node(
    base_url: str,
    token: str,
    data: str,
    tags: list[str] | tuple[str, ...] = (),
    cognify: bool = False,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST a note to the Node's /ingest (same endpoint MCP citadel_ingest uses).

    Sends no dataset, so the seat token routes the write to the dev's private
    node (personal-by-default), mirroring the SessionEnd hook. With cognify=True
    the Node builds the graph inline and blocks until done (so the note is
    immediately searchable). Returns the response (``accepted``, ``reason``,
    ``dataset``, and ``cognified`` when cognify was requested).
    """
    payload: dict[str, Any] = {"data": data, "tags": list(tags)}
    if cognify:
        payload["cognify"] = True
    resolved = timeout if timeout is not None else (_COGNIFY_TIMEOUT if cognify else _INGEST_TIMEOUT)
    return _request(
        "POST",
        f"{base_url.rstrip('/')}/ingest",
        token=token,
        payload=payload,
        timeout=resolved,
    )


_COGNIFY_TIMEOUT = 180.0  # /ingest cognifies inline; give the combined call room


def fetch_mesh(base_url: str, token: str | None, *, timeout: float = _TIMEOUT) -> dict[str, Any]:
    """Best-effort GET /api/mesh snapshot (knowledge-graph stats). {} on any error."""
    if not token:
        return {}
    try:
        data = _request("GET", f"{base_url.rstrip('/')}/api/mesh", token=token, timeout=timeout)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def fetch_events(
    base_url: str,
    token: str | None,
    *,
    after_id: int | None = None,
    limit: int = 20,
    event_type: str | None = None,
    timeout: float = _TIMEOUT,
) -> dict[str, Any]:
    """Best-effort GET /api/knowledge/events (the caller-scoped Vault Activity
    timeline). Returns ``{}`` on any error / missing token. ``after_id`` resumes
    after the last seen event id (for --watch polling)."""
    if not token:
        return {}
    query = f"limit={max(1, min(int(limit), 160))}"
    if after_id is not None:
        query += f"&after_id={int(after_id)}"
    if event_type:
        query += f"&type={urllib.parse.quote(event_type)}"
    try:
        data = _request(
            "GET", f"{base_url.rstrip('/')}/api/knowledge/events?{query}", token=token, timeout=timeout
        )
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


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

    # Session hooks live in user-scope ~/.claude/settings.json (cross-repo), not
    # the project's .claude/settings.json (#38).
    from kb.onboard import claude_user_settings_path

    settings = claude_user_settings_path()
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

    # The network checks are independent, so they run concurrently — wall time
    # is the slowest check (search, when cold), not the sum of all of them.
    # Each check still captures its own failure, so a thread never raises.
    with ThreadPoolExecutor(max_workers=5) as pool:
        node_f = pool.submit(check_node_health, base_url, timeout=timeout)
        auth_f = pool.submit(check_auth, base_url, token, timeout=timeout)
        search_f = pool.submit(check_search, base_url, token) if with_search else None
        corpus_f = pool.submit(check_corpus, base_url, token, timeout=timeout)
        recent_f = (
            pool.submit(fetch_recent, base_url, token, timeout=timeout) if with_recent else None
        )
        node = node_f.result()
        auth = auth_f.result()
        checks = [node, auth]
        if search_f is not None:
            checks.append(search_f.result())  # uses its own longer timeout
        corpus = corpus_f.result()
        if corpus is not None:
            checks.append(corpus)
        recent = recent_f.result() if recent_f is not None else []
    checks.extend(check_local_setup(repo, config_path))
    # A RED corpus gate (sources tracked but graph empty, or the canary failed)
    # makes the whole report unhealthy — no more green over a broken data plane (#27).
    corpus_ok = corpus.ok if corpus is not None else True
    return StatusReport(
        node_url=base_url,
        healthy=node.ok and auth.ok and corpus_ok,
        identity=auth.data,
        checks=checks,
        recent=recent,
        repo=str(repo),
    )


# Checks split into two sections; everything not here is "Local setup".
_CONNECTIVITY = ("node", "auth", "search", "corpus")
# Human labels — the raw snake_case names read like debug output.
_CHECK_LABELS = {
    "node": "Node",
    "auth": "Auth",
    "search": "Search",
    "corpus": "Data plane",
    "token": "Token",
    "mcp": "MCP server",
    "pre_push_hook": "Pre-push hook",
    "session_hook": "SessionEnd hook",
    "capture_roots": "Capture roots",
}


def _fmt_latency(latency_ms: int | None) -> str:
    """Humanized latency: '143ms' below a second, '5.8s' above."""
    if latency_ms is None:
        return ""
    if latency_ms >= 1000:
        return f"{latency_ms / 1000:.1f}s"
    return f"{latency_ms}ms"


# A check slower than this gets its latency called out instead of dimmed.
_SLOW_MS = 3000


def render_text(report: StatusReport, *, color: bool = False, verdict: bool = True) -> str:
    from kb.banner import WARN, mark, paint

    ident = report.identity
    seat = ident.get("seat_slug") or ident.get("actor") or "—"
    role = ident.get("role") or "—"
    identity_line = f"seat: {paint(str(seat), 'bold', enable=color)}   role: {role}"
    # Where this token writes — the onboard identity panel's "writes" fact,
    # surfaced here too so status answers it without a second command.
    if ident.get("capabilities", {}).get("write"):
        writes = f"seat:{ident['seat_slug']}" if ident.get("seat_slug") else "shared org dataset"
        identity_line += f"   writes: {writes}"
    lines = [
        identity_line,
        paint(f"node: {report.node_url}", "dim", enable=color),
        "",
    ]

    cols = shutil.get_terminal_size((80, 24)).columns

    def _row(check: Check, detail_width: int) -> str:
        label = _CHECK_LABELS.get(check.name, check.name)
        latency = _fmt_latency(check.latency_ms)
        detail = check.detail
        budget = cols - 22 - len(latency)  # 2 indent + glyph + space + 16 label + space + gap
        if budget > 8 and len(detail) > budget:
            detail = detail[: budget - 1] + "…"
        if latency:
            slow = (check.latency_ms or 0) >= _SLOW_MS
            pad = " " * max(detail_width - len(detail) + 2, 2)
            latency = pad + paint(latency, "yellow" if slow else "dim", enable=color)
        sigil = mark(check.ok, enable=color)
        if not check.ok and check.name == "search":
            # Search never gates health — a red ✗ next to a green verdict reads
            # as a contradiction, so the non-gating failure warns instead.
            sigil = paint(WARN, "yellow", enable=color)
        return f"  {sigil} {label:<16} {detail}{latency}"

    conn = [c for c in report.checks if c.name in _CONNECTIVITY]
    local = [c for c in report.checks if c.name not in _CONNECTIVITY]

    def _section(title: str, checks: list[Check], note: str = "") -> list[str]:
        # Latencies form one aligned (and dimmed) column per section, so the
        # details read as a block instead of a ragged mix of text and numbers.
        width = min(max((len(c.detail) for c in checks), default=0), max(cols - 30, 8))
        header = paint(title, "bold", enable=color) + (paint(note, "dim", enable=color) if note else "")
        return [header, *(_row(c, width) for c in checks)]

    if conn:
        lines.extend(_section("Connectivity", conn))
        lines.append("")
    if local:
        # Local checks are repo-relative — name the repo, so a ✗ from the wrong
        # directory reads as "wrong directory", not "broken setup".
        note = f"  — {report.repo}" if report.repo else ""
        lines.extend(_section("Local setup", local, note))

    if report.recent:
        lines.append("")
        lines.append(paint("Recent activity", "bold", enable=color))
        for item in report.recent[:5]:
            when = item.get("created_at") or item.get("timestamp") or ""
            label = item.get("title") or item.get("action") or item.get("detail") or "—"
            lines.append(f"  · {paint(str(when)[:19], 'dim', enable=color)}  {label}")

    if verdict:
        lines.append("")
        lines.append(render_verdict(report, color=color))
    return "\n".join(lines)


def render_verdict(report: StatusReport, *, color: bool = False) -> str:
    """The one-line (plus hints) bottom-line summary — always the last thing printed."""
    from kb.banner import paint

    lines: list[str] = []
    conn = [c for c in report.checks if c.name in _CONNECTIVITY]
    local = [c for c in report.checks if c.name not in _CONNECTIVITY]
    conn_fail = [c for c in conn if not c.ok]
    local_fail = [c for c in local if not c.ok]
    # A cold-node Search TIMEOUT is non-gating noise; a hard Search error is not.
    search_fail = [c for c in conn if c.name == "search" and not c.ok]
    search_warming = any((c.data or {}).get("timed_out") for c in search_fail)
    search_degraded = any(not (c.data or {}).get("timed_out") for c in search_fail)

    if report.healthy and not conn_fail and not local_fail:
        lines.append(paint("All systems go.", "green", enable=color))
    elif report.healthy:
        # node + auth are OK — say so plainly, then call out only real gaps.
        lines.append(paint("Connected to the Node.", "green", enable=color))
        if local_fail:
            labels = ", ".join(_CHECK_LABELS.get(c.name, c.name) for c in local_fail)
            lines.append(
                paint(
                    f"  Local setup incomplete ({len(local) - len(local_fail)}/{len(local)}) — {labels}.",
                    "yellow",
                    enable=color,
                )
            )
            lines.append(paint("  Run `citadel doctor --fix` to repair.", "dim", enable=color))
        if search_warming:
            lines.append(paint("  Search is still warming up — retry in a minute.", "dim", enable=color))
        elif search_degraded:
            detail = next((c.detail for c in search_fail), "")
            lines.append(paint(f"  Search degraded — {detail}. Not blocking.", "yellow", enable=color))
    else:
        node_auth_fail = [c for c in conn_fail if c.name in ("node", "auth")]
        corpus_fail = next((c for c in conn if c.name == "corpus" and not c.ok), None)
        if node_auth_fail:
            labels = ", ".join(_CHECK_LABELS.get(c.name, c.name) for c in node_auth_fail) or "Node/Auth"
            lines.append(
                paint(
                    f"Not connected — {labels} failing. Check the Node URL / token, or run `citadel onboard`.",
                    "yellow",
                    enable=color,
                )
            )
        elif corpus_fail is not None:
            # The Node is up, but the data plane is broken (sources tracked, graph
            # empty, or the cognify canary failed) — the exact #27 failure mode.
            lines.append(
                paint(
                    f"Data plane broken — {corpus_fail.detail}. The Node is up but search "
                    "returns nothing; ingested data is not being indexed.",
                    "red",
                    enable=color,
                )
            )
        else:
            labels = ", ".join(_CHECK_LABELS.get(c.name, c.name) for c in conn_fail) or "Node/Auth"
            lines.append(
                paint(
                    f"Not connected — {labels} failing. Check the Node URL / token, or run `citadel onboard`.",
                    "yellow",
                    enable=color,
                )
            )
    return "\n".join(lines)
