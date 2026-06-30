from __future__ import annotations

import argparse
import asyncio
import difflib
import functools
import getpass
import http.client
import json
import os
import re
import shutil
import sys
import threading
import urllib.error
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any, NoReturn

# Lightweight client modules only — the heavy server stack (kb.service,
# kb.github_sync, …) is imported lazily inside the server handlers so the base
# `citadel-archive` install (onboard/status/capture) needs no server deps.
from kb.capture_config import (
    DEFAULT_NODE_URL,
    DEFAULT_ROOT_TAG,
    PRESET_ROOT_TAGS,
    CaptureConfig,
    capture_config_path,
    load_capture_config,
    normalize_path,
    normalize_tags,
    save_capture_config,
)
from kb.capture import build_capture_payload, capture_token, post_capture
from kb.onboard import (
    TOKEN_ENV,
    claude_user_settings_path,
    detect_shell_rc,
    ensure_env_in_rc,
    ensure_token_in_rc,
    git_root_or_cwd,
    install_pre_push_hook,
    mask_token,
    merge_claude_settings,
    merge_mcp_config,
)
from kb.banner import SKIP, banner, banner_large, mark, paint, supports_color
from kb.access_client import (
    AccessClientError,
    create_seat,
    create_token,
    issue_seat_token,
    list_seats,
    revoke_token,
)
from kb.promotion_client import (
    PromotionClientError,
    approve_pending,
    list_pending,
    node_base_url,
    reject_pending,
    run_promotion,
)
from kb.status import fetch_mesh, gather_status, render_text


def _print_json(value: Any) -> None:
    print(json.dumps(value, default=str, indent=2))


class _Spinner:
    """An animated stdlib progress indicator on stderr (so stdout stays clean).

    A cyan knight-rider bar that bounces while work runs, with an elapsed-seconds
    readout once an op is slow. Active only on a real stderr TTY; a no-op
    otherwise (CI, pipes, --json), so it never pollutes captured output.
    """

    _INTERVAL = 0.11
    # A 7-cell bounce: a bright block sweeps back and forth over dim cells.
    _WIDTH = 7
    _POSITIONS = list(range(_WIDTH)) + list(range(_WIDTH - 2, 0, -1))

    def __init__(self, message: str) -> None:
        self.message = message
        self.enable = sys.stderr.isatty()
        self._color = supports_color(sys.stderr)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _frame(self, step: int) -> str:
        pos = self._POSITIONS[step % len(self._POSITIONS)]
        cells = "".join("▰" if i == pos else "▱" for i in range(self._WIDTH))
        return paint(cells, "cyan", enable=self._color)

    def _run(self) -> None:
        step = 0
        while not self._stop.is_set():
            elapsed = int(step * self._INTERVAL)
            tail = paint(f"  {elapsed}s", "dim", enable=self._color) if elapsed >= 2 else ""
            sys.stderr.write(f"\r{self._frame(step)} {self.message}{tail} ")
            sys.stderr.flush()
            step += 1
            self._stop.wait(self._INTERVAL)

    def __enter__(self) -> "_Spinner":
        if self.enable:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
            sys.stderr.write("\r\033[K")  # erase the indicator line
            sys.stderr.flush()


def _needs_server(
    fn: Callable[[argparse.Namespace], Awaitable[Any]],
) -> Callable[[argparse.Namespace], Awaitable[Any]]:
    """Wrap a server-only handler: turn a missing [server] dep into a clean hint."""

    @functools.wraps(fn)
    async def wrapper(args: argparse.Namespace) -> Any:
        cmd = getattr(args, "command", "") or ""
        try:
            return await fn(args)
        except ImportError as exc:
            missing = getattr(exc, "name", None) or str(exc)
            print(
                f"`citadel {cmd}` needs the server extra:\n"
                "  pip install 'citadel-archive[server]'"
                "    (pipx: pipx install --force 'citadel-archive[server]')\n"
                f"  (missing dependency: {missing})",
                file=sys.stderr,
            )
            return 2
        except Exception as exc:
            # Operational failure (network, cognee, bad dataset): a clean stderr
            # line and a nonzero exit — never a raw traceback dumped at the user.
            print(f"citadel {cmd}: {exc}", file=sys.stderr)
            return 1

    return wrapper


def _result_exit(value: Any) -> int:
    """Exit 1 when a result payload carries ``ok: False``; else 0.

    Closes the 'JSON says failed but exit 0' gap without each handler having to
    special-case it. Values without an ``ok`` key (lists, plain results) → 0.
    """
    data = value if isinstance(value, dict) else getattr(value, "__dict__", {})
    if isinstance(data, dict) and (data.get("ok") is False or data.get("accepted") is False):
        return 1
    return 0


async def _ingest(args: argparse.Namespace) -> int:
    """Add a note to your Node over HTTP (like MCP citadel_ingest). `--local`
    runs the in-process server stack (needs the [server] extra)."""
    if getattr(args, "local", False):
        return await _ingest_local(args)
    base_url = node_base_url(getattr(args, "node_url", None))
    token = capture_token()
    if not token:
        print(
            "citadel ingest: no token — set CITADEL_MCP_ACCESS_TOKEN or run `citadel onboard`.",
            file=sys.stderr,
        )
        return 1
    from kb.status import ingest_node

    # Cognify inline (server-side) by default so the note is immediately
    # searchable; the one request blocks until cognify finishes (--no-cognify skips).
    cognify = not getattr(args, "no_cognify", False)
    as_json = getattr(args, "json", False)
    spinner_msg = "Ingesting + building the graph…" if cognify else "Ingesting to your Node…"
    try:
        with _Spinner(spinner_msg):
            result = await asyncio.to_thread(ingest_node, base_url, token, args.data, args.tag, cognify)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200] if exc.fp else exc.reason
        print(f"citadel ingest: HTTP {exc.code} {detail}", file=sys.stderr)
        return 1
    except TimeoutError:
        print(
            "citadel ingest: the Node is still working (cognify can be slow). Your note is "
            "saved — it'll be searchable shortly; check `citadel search`.",
            file=sys.stderr,
        )
        return 1
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        print(f"citadel ingest: {exc}", file=sys.stderr)
        return 1
    if not isinstance(result, dict):  # a misconfigured Node could return non-dict JSON
        result = {"accepted": False, "reason": "unexpected response from the Node"}
    accepted = result.get("accepted", True)
    # A duplicate is a benign, idempotent no-op — not a failure.
    duplicate = (not accepted) and "duplicate" in str(result.get("reason") or "")
    cognified = result.get("cognified")  # True/False from the Node, or None (not requested / old Node)
    color = supports_color()
    dataset = result.get("dataset") or "your node"
    scope = "your private seat" if str(dataset).startswith("seat:") else "shared org vault"

    if as_json:
        _print_json(result)
        return 0 if (accepted or duplicate) else 1

    if accepted:
        print(
            f"  {mark(True, enable=color)} ingested to {paint(dataset, 'cyan', enable=color)}  "
            f"{paint('(' + scope + ')', 'dim', enable=color)}"
        )
        if cognified is True:
            print(f"  {mark(True, enable=color)} cognified — now searchable")
        elif cognified is False:
            print(f"  {paint(SKIP, 'yellow', enable=color)} ingested, but cognify didn't finish — the next Node sync will pick it up")
        elif cognify:
            # Requested cognify but the Node didn't report it (older Node, pre inline-cognify).
            print(paint("  (graph update will happen on the next Node sync)", "dim", enable=color))
    elif duplicate:
        print(
            f"  {paint(SKIP, 'yellow', enable=color)} already in your vault (duplicate) — nothing new to add"
        )
    else:
        reason = str(result.get("reason") or "rejected").replace("_", " ")
        print(f"  {mark(False, enable=color)} not accepted: {reason}", file=sys.stderr)
    return 0 if (accepted or duplicate) else 1


@_needs_server
async def _ingest_local(args: argparse.Namespace) -> int:
    from kb.service import Citadel

    kb = Citadel.from_env()
    result = await kb.ingest(
        args.data,
        dataset=args.dataset,
        tags=args.tag,
        session_id=args.session,
    )
    _print_json(result.__dict__)
    return _result_exit(result)


def _render_search(results: list[Any], query: str) -> None:
    color = supports_color()
    if not results:
        print(paint(f'No results for "{query}".', "dim", enable=color))
        return
    print(f'{len(results)} result(s) for "{query}":\n')
    for index, item in enumerate(results, 1):
        if isinstance(item, dict):
            text = (
                item.get("text") or item.get("content") or item.get("summary")
                or item.get("title") or item.get("name") or json.dumps(item, default=str)
            )
        else:
            text = str(item)
        text = " ".join(str(text).split())
        snippet = text[:300] + ("…" if len(text) > 300 else "")
        print(f"  {paint(f'{index}.', 'cyan', enable=color)} {snippet}")


async def _search(args: argparse.Namespace) -> int:
    """Search the Organization Vault over HTTP (the Node), like MCP citadel_search.

    Zero-dep: hits the Node's /search with the seat token, so base-install
    teammates can query the same vault their agent sees. `--local` runs the
    in-process server stack instead (needs the [server] extra).
    """
    if getattr(args, "local", False):
        return await _search_local(args)
    base_url = node_base_url(getattr(args, "node_url", None))
    token = capture_token()
    if not token:
        print(
            "citadel search: no token — set CITADEL_MCP_ACCESS_TOKEN or run `citadel onboard`.",
            file=sys.stderr,
        )
        return 1
    from kb.status import search_node

    try:
        with _Spinner("Searching the vault…"):
            results = await asyncio.to_thread(search_node, base_url, token, args.query, args.top_k)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200] if exc.fp else exc.reason
        print(f"citadel search: HTTP {exc.code} {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        print(f"citadel search: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        _print_json(results)
    else:
        _render_search(results, args.query)
    return 0


@_needs_server
async def _search_local(args: argparse.Namespace) -> int:
    from kb.service import Citadel

    kb = Citadel.from_env()
    results = await kb.search(
        args.query,
        dataset=args.dataset,
        session_id=args.session,
        top_k=args.top_k,
    )
    _print_json(results)
    return _result_exit(results)


@_needs_server
async def _feedback(args: argparse.Namespace) -> None:
    from kb.models import FeedbackRequest
    from kb.service import Citadel

    kb = Citadel.from_env()
    result = await kb.feedback(
        FeedbackRequest(
            qa_id=args.qa_id,
            score=args.score,
            text=args.text,
            session_id=args.session,
            dataset=args.dataset,
        )
    )
    _print_json(result.__dict__)
    return _result_exit(result)


@_needs_server
async def _improve(args: argparse.Namespace) -> None:
    from kb.service import Citadel

    kb = Citadel.from_env()
    result = await kb.improve(dataset=args.dataset, session_ids=args.session_id)
    _print_json(result)
    return _result_exit(result)


@_needs_server
async def _cognify(args: argparse.Namespace) -> None:
    from kb.service import Citadel

    kb = Citadel.from_env()
    result = await kb.cognify_dataset(dataset=args.dataset, verify=args.verify)
    _print_json(result)
    return _result_exit(result)


@_needs_server
async def _sync_github(args: argparse.Namespace) -> None:
    from kb.github_sync import GitHubOrgSyncer
    from kb.service import Citadel

    syncer = GitHubOrgSyncer(
        Citadel.from_env(),
        org=args.org,
        state_path=args.state_path,
        max_repos=args.max_repos,
        max_events=args.max_events,
        max_commits_per_repo=args.max_commits_per_repo,
        include_commits=not args.skip_commits,
        ingest_unchanged=not args.skip_unchanged,
        run_improve=not args.skip_improve,
    )
    result = await syncer.run(force=args.force, dry_run=args.dry_run)
    _print_json(result)
    return _result_exit(result)


@_needs_server
async def _sync_repo_content(args: argparse.Namespace) -> None:
    from kb.repo_content_sync import RepoContentSyncer
    from kb.service import Citadel

    syncer = RepoContentSyncer(Citadel.from_env())
    result = await syncer.run(force=args.force, dry_run=args.dry_run)
    _print_json(result)
    return _result_exit(result)


@_needs_server
async def _learn(args: argparse.Namespace) -> None:
    from kb.learning_agent import LearningAgent

    agent = LearningAgent.from_env()
    result = await agent.status() if args.status else await agent.run(
        force=args.force,
        dry_run=args.dry_run,
        post_to_chat=args.post_to_chat,
        include_digest_preview=not args.hide_digest_preview,
    )
    _print_json(result)
    return _result_exit(result)


def _parse_root_arg(raw: str) -> tuple[str, tuple[str, ...]]:
    """Parse a non-interactive ``--root`` value: ``PATH`` or ``PATH=tag1,tag2``."""
    path, sep, tags_str = raw.partition("=")
    tags = tuple(tags_str.split(",")) if sep else ()
    return path, tags


def _wizard_roots(config: CaptureConfig) -> CaptureConfig:
    print(
        "\nAdd Approved Capture Roots — folders auto-captured to your Node.\n"
        "Leave the path empty to finish."
    )
    while True:
        raw = input("  Root path: ").strip()
        if not raw:
            break
        normalized = normalize_path(raw)
        if not Path(normalized).exists():
            print(f"  ! {normalized} does not exist yet (added anyway)")
        print(
            f"  Tags — presets: {', '.join(PRESET_ROOT_TAGS)}; "
            f"'personal' never promotes. Default: {DEFAULT_ROOT_TAG}."
        )
        tags_raw = input("  Tags (comma-separated): ").strip()
        tags = tuple(tags_raw.split(",")) if tags_raw else (DEFAULT_ROOT_TAG,)
        config = config.with_root(normalized, tags)
        print(f"  + {normalized}  [{', '.join(normalize_tags(tags))}]")
    return config


def _load_config_or_exit(args: argparse.Namespace, command: str) -> CaptureConfig | None:
    """Load config, printing a clean error (and signalling exit 1) on corruption."""
    config_path = Path(args.config).expanduser() if args.config else capture_config_path()
    try:
        return load_capture_config(config_path)
    except ValueError as exc:
        print(f"citadel {command}: {exc}", file=sys.stderr)
        return None


async def _setup(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser() if args.config else capture_config_path()
    config = _load_config_or_exit(args, "setup")
    if config is None:
        return 1

    if args.show:
        _print_json(config.to_dict())
        return 0

    node_url = (args.node_url or config.node_url or DEFAULT_NODE_URL).rstrip("/")
    interactive = (
        not args.non_interactive
        and not args.root
        and not getattr(args, "json", False)
        and sys.stdin.isatty()
    )

    if interactive:
        prompt = f"Node URL [{node_url}]: "
        node_url = (input(prompt).strip() or node_url).rstrip("/")

    config = CaptureConfig(node_url=node_url, roots=config.roots, version=config.version)

    if args.root:
        for raw in args.root:
            path, tags = _parse_root_arg(raw)
            config = config.with_root(path, tags or (DEFAULT_ROOT_TAG,))
    elif interactive:
        config = _wizard_roots(config)

    written = save_capture_config(
        config, path=config_path, updated_at=datetime.now(timezone.utc).isoformat()
    )
    if getattr(args, "json", False):
        _print_json(load_capture_config(config_path).to_dict())
    else:
        print(f"\nSaved {len(config.roots)} approved root(s) to {written}")
    return 0


async def _capture(args: argparse.Namespace) -> int:
    config = _load_config_or_exit(args, "capture")
    if config is None:
        return 1

    if not config.roots:
        print("No approved roots to capture. Run `citadel setup` first.", file=sys.stderr)
        return 1

    roots = config.roots
    if args.root:
        wanted = {normalize_path(raw) for raw in args.root}
        roots = tuple(root for root in config.roots if root.path in wanted)
        if not roots:
            print(f"No configured root matches: {', '.join(args.root)}", file=sys.stderr)
            return 1

    payloads = [(root, build_capture_payload(root)) for root in roots]

    if args.dry_run:
        _print_json(
            [
                {
                    "root": root.path,
                    "tags": payload["tags"],
                    "chars": len(payload["data"]),
                    "preview": payload["data"][:500],
                }
                for root, payload in payloads
            ]
        )
        return 0

    token = capture_token()
    if not token:
        print(
            "citadel capture: no token — set CITADEL_MCP_ACCESS_TOKEN or run `citadel onboard`.",
            file=sys.stderr,
        )
        return 1

    as_json = getattr(args, "json", False)
    results: list[dict[str, Any]] = []
    failures = 0
    for root, payload in payloads:
        try:
            response = post_capture(config.node_url, token, payload)
            status = response.get("cognee_result", {}).get("status") or response.get("status")
            results.append({"root": root.path, "ok": True, "status": status, "tags": payload["tags"]})
            if not as_json:
                print(f"OK  {root.path} ({status})")
        except urllib.error.HTTPError as exc:
            failures += 1
            detail = exc.read().decode(errors="replace")[:200]
            results.append({"root": root.path, "ok": False, "error": f"HTTP {exc.code} {detail}"})
            if not as_json:
                print(f"FAIL {root.path}: HTTP {exc.code} {detail}", file=sys.stderr)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Node unreachable / DNS / timeout / non-HTTPS URL — isolate per root.
            failures += 1
            results.append({"root": root.path, "ok": False, "error": str(exc)})
            if not as_json:
                print(f"FAIL {root.path}: {exc}", file=sys.stderr)
    if as_json:
        _print_json({"ok": failures == 0, "results": results})
    # Human mode already printed a per-root OK/FAIL line during the loop.
    return 1 if failures else 0


def _promotion_base_url(args: argparse.Namespace) -> str:
    return node_base_url(getattr(args, "node_url", None))


def _promotion_exit(exc: PromotionClientError, *, as_json: bool) -> int:
    if as_json:
        _print_json({"ok": False, "error": str(exc), "status": exc.status, "body": exc.body})
    else:
        print(f"citadel promotion: {exc}", file=sys.stderr)
    return 1


@_needs_server
async def _promotion_list(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = list_pending(
            base_url=_promotion_base_url(args),
            status=args.status,
        )
    except PromotionClientError as exc:
        return _promotion_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
    else:
        items = result.get("items") or []
        print(f"Promotion queue ({result.get('status', args.status)}): {len(items)} item(s)")
        for item in items:
            preview = item.get("preview") or "(no preview)"
            print(
                f"  {item.get('id')}  seat={item.get('seat_slug')}  "
                f"ref={item.get('reference_status')}  {preview}"
            )
    return 0


@_needs_server
async def _promotion_approve(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = approve_pending(
            args.item_id,
            base_url=_promotion_base_url(args),
            note=args.note,
        )
    except PromotionClientError as exc:
        return _promotion_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
    else:
        promoted = result.get("promoted")
        print(f"Approved {args.item_id} (promoted={promoted})")
    return 0 if result.get("ok") else 1


@_needs_server
async def _promotion_reject(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = reject_pending(
            args.item_id,
            base_url=_promotion_base_url(args),
            note=args.note,
        )
    except PromotionClientError as exc:
        return _promotion_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
    else:
        print(f"Rejected {args.item_id}")
    return 0 if result.get("ok") else 1


@_needs_server
async def _promotion_run(args: argparse.Namespace) -> int:
    as_json = args.json
    dry_run = not args.execute
    try:
        result = run_promotion(
            base_url=_promotion_base_url(args),
            dataset=args.dataset,
            dry_run=dry_run,
            max_items=args.max_items,
        )
    except PromotionClientError as exc:
        return _promotion_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
    else:
        mode = "dry-run" if dry_run else "execute"
        print(
            f"Promotion {mode} on {result.get('dataset')}: "
            f"candidates={result.get('candidates')} "
            f"proposed={result.get('proposed')} "
            f"promoted={result.get('promoted')} "
            f"queued={result.get('queued')}"
        )
    return 0 if result.get("ok") else 1


def _access_exit(exc: AccessClientError, *, as_json: bool) -> int:
    if as_json:
        _print_json({"ok": False, "error": str(exc), "status": exc.status, "body": exc.body})
    else:
        print(f"citadel: {exc}", file=sys.stderr)
    return 1


def _print_minted_token(token: str, api_token: dict[str, Any], *, color: bool) -> None:
    """Print a freshly minted token once, with its write-scope + adopt steps."""
    print()
    print(paint("  Token (shown once — copy it now, it cannot be retrieved later):", "yellow", enable=color))
    print("    " + paint(token, "bold", enable=color))
    dataset = api_token.get("default_dataset")
    if dataset and str(dataset).startswith("seat:"):
        scope = f"ingests go to {dataset} (their private seat) only"
    elif dataset:
        scope = f"ingests go to {dataset}"
    else:
        scope = "ingests go to the org default dataset — NOT a private seat"
    print(paint(f"  scope: {scope}  ·  role={api_token.get('role')}", "dim", enable=color))
    print(paint("  Adopt:  citadel onboard --token <token-above>   ·   share over a private channel", "dim", enable=color))


async def _seat_list(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = list_seats(base_url=node_base_url(args.node_url))
    except AccessClientError as exc:
        return _access_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
        return 0
    color = supports_color()
    seats = result.get("seats") or []
    print(f"Seats ({len(seats)}):")
    for seat in seats:
        disabled = paint("  [disabled]", "red", enable=color) if seat.get("disabled") else ""
        slug = paint(str(seat.get("seat_slug") or "—"), "cyan", enable=color)
        print(
            f"  {slug}  {seat.get('name', '')}  role={seat.get('role')}  "
            f"tokens={seat.get('active_token_count', 0)}{disabled}"
        )
    return 0


async def _seat_create(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = create_seat(
            base_url=node_base_url(args.node_url),
            name=args.name,
            slug=args.slug,
            email=args.email,
            role=args.role,
            issue_token=not args.no_token,
        )
    except AccessClientError as exc:
        return _access_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
        return 0
    color = supports_color()
    principal = result.get("principal", {})
    print(
        paint(
            f"Seat created: {principal.get('seat_slug')}  (dataset {principal.get('default_dataset')})",
            "green",
            enable=color,
        )
    )
    token = result.get("token")
    if token:
        _print_minted_token(token, result.get("api_token", {}), color=color)
    else:
        print("  (no token issued — re-run without --no-token to mint one)")
    return 0


async def _seat_token(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = issue_seat_token(args.slug, base_url=node_base_url(args.node_url))
    except AccessClientError as exc:
        return _access_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
        return 0
    color = supports_color()
    principal = result.get("principal", {})
    print(
        paint(
            f"New token for seat {principal.get('seat_slug')}  (dataset {principal.get('default_dataset')})",
            "green",
            enable=color,
        )
    )
    if result.get("token"):
        _print_minted_token(result["token"], result.get("api_token", {}), color=color)
    return 0


async def _token_create(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = create_token(
            base_url=node_base_url(args.node_url),
            name=args.name,
            role=args.role,
            kind=args.kind,
            default_dataset=args.dataset,
            expires_at=args.expires_at,
        )
    except AccessClientError as exc:
        return _access_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
        return 0
    color = supports_color()
    print(paint(f"Token created  (principal {result.get('principal', {}).get('id')})", "green", enable=color))
    if result.get("token"):
        _print_minted_token(result["token"], result.get("api_token", {}), color=color)
    # Standalone tokens are NOT seat-scoped — steer teammate tokens to seats.
    api_token = result.get("api_token", {})
    if not str(api_token.get("default_dataset") or "").startswith("seat:"):
        print(
            paint(
                "  Note: this is a standalone token (not a private seat). For a teammate, use "
                "`citadel seat create \"Name\" slug` so their writes land in their own seat.",
                "yellow",
                enable=color,
            )
        )
    return 0


async def _token_revoke(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        result = revoke_token(args.token_id, base_url=node_base_url(args.node_url))
    except AccessClientError as exc:
        return _access_exit(exc, as_json=as_json)
    if as_json:
        _print_json(result)
        return 0
    print(f"Revoked {args.token_id}")
    return 0 if result.get("ok") else 1


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _wire_detected_tools(node_url: str, *, color: bool) -> None:
    """Interactive: offer to add Citadel's MCP server to each detected tool.

    Write-tier tools (token stays in the rc via an env reference) are merged on
    confirmation; snippet-tier tools print a paste-in block on request; Pi gets
    a note. Used only on an interactive `citadel onboard`.
    """
    from kb import tool_detect

    detected = tool_detect.detect()
    if not detected:
        return
    print("\n" + paint("Coding tools", "bold", enable=color))
    for name in detected:
        spec = tool_detect.SPECS[name]
        if spec.mode == "write":
            answer = input(f"  Add Citadel MCP to {spec.label}? [Y/n]: ").strip().lower()
            if answer not in ("", "y", "yes"):
                continue
            result = tool_detect.apply(name, node_url=node_url)
            sigil = mark(result.action != "error", enable=color)
            print(f"  {sigil} {spec.label}  {paint(f'{result.action} · {result.detail}', 'dim', enable=color)}")
        elif spec.mode == "snippet":
            answer = input(f"  Show paste-in MCP snippet for {spec.label}? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                continue
            result = tool_detect.apply(name, node_url=node_url)
            print(paint(f"    → {spec.config_hint}", "dim", enable=color))
            print(_indent(result.snippet or ""))
        else:  # note (e.g. Pi)
            result = tool_detect.apply(name, node_url=node_url)
            print(f"  {paint('•', 'dim', enable=color)} {spec.label}: {paint(result.detail, 'dim', enable=color)}")


async def _mcp_add(args: argparse.Namespace) -> int:
    from kb import tool_detect

    node_url = node_base_url(args.node_url)
    color = supports_color()
    targets = tool_detect.ALL_TOOLS if args.tool == "all" else [args.tool]
    rc = 0
    for name in targets:
        if name not in tool_detect.SPECS:
            print(f"citadel mcp add: unknown tool {name!r} "
                  f"(choose from: {', '.join(tool_detect.ALL_TOOLS)}, all)", file=sys.stderr)
            rc = 1
            continue
        spec = tool_detect.SPECS[name]
        result = tool_detect.apply(name, node_url=node_url)
        if spec.mode == "write":
            ok = result.action != "error"
            rc = rc or (0 if ok else 1)
            print(f"  {mark(ok, enable=color)} {spec.label}  "
                  f"{paint(f'{result.action} · {result.detail}', 'dim', enable=color)}")
        elif spec.mode == "snippet":
            print(paint(f"{spec.label} — paste into {spec.config_hint}:", "bold", enable=color))
            print(_indent(result.snippet or ""))
        else:
            print(f"{spec.label}: {result.detail}")
    return rc


async def _mcp_list(args: argparse.Namespace) -> int:
    from kb import tool_detect

    color = supports_color()
    detected = tool_detect.detect()
    if not detected:
        print("No known coding tools detected.")
        return 0
    print(f"Detected coding tools ({len(detected)}):")
    for name in detected:
        spec = tool_detect.SPECS[name]
        mode = {"write": "auto-write", "snippet": "snippet", "note": "note"}[spec.mode]
        print(f"  {paint(name.ljust(9), 'cyan', enable=color)} {mode:<10} {paint(spec.config_hint, 'dim', enable=color)}")
    return 0


async def _status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser() if args.repo else git_root_or_cwd()
    config_path = Path(args.config).expanduser() if args.config else capture_config_path()
    try:
        node_url = args.node_url or load_capture_config(config_path).node_url
    except ValueError:
        node_url = args.node_url or DEFAULT_NODE_URL
    token = capture_token() or None

    async def _gather() -> Any:
        return await asyncio.to_thread(
            gather_status,
            node_url,
            token,
            repo=repo,
            config_path=config_path,
            with_search=not args.no_search,
            with_recent=not args.no_recent,
        )

    if args.json:
        report = await _gather()
        payload = report.to_dict()
        payload["mesh"] = await asyncio.to_thread(fetch_mesh, node_url, token)
        _print_json(payload)
    else:
        # The search check can take ~15s cold — spin so it doesn't look hung.
        with _Spinner("Checking Citadel…"):
            report = await _gather()
            mesh = await asyncio.to_thread(fetch_mesh, node_url, token)
        use_color = supports_color()
        print(banner(color=use_color))
        print()
        print(render_text(report, color=use_color))
        mesh_block = _render_mesh(mesh, use_color)
        if mesh_block:
            print()
            print(mesh_block)
    return 0 if report.healthy else 1


def _render_mesh(mesh: dict[str, Any], color: bool) -> str:
    """Compact knowledge-mesh summary for `citadel status` (the 'your data' view)."""
    stats = (mesh or {}).get("stats")
    if not isinstance(stats, dict) or not stats:
        return ""

    def num(key: str) -> int:
        value = stats.get(key)
        return value if isinstance(value, int) else 0

    lines = [
        paint("Knowledge mesh", "bold", enable=color),
        f"  documents {paint(str(num('documents')), 'bold', enable=color)}   "
        f"nodes {num('nodes')}   edges {num('edges')}   searches {num('searches')}",
    ]
    last = stats.get("last_indexed_at")
    if last:
        lines.append(paint(f"  last indexed {str(last)[:19]}", "dim", enable=color))
    return "\n".join(lines)


def _mcp_node_url(path: Path) -> str | None:
    """The Node base URL wired into .mcp.json (citadel server), sans /mcp/ suffix."""
    try:
        servers = json.loads(path.read_text()).get("mcpServers", {})
        url = (servers.get("citadel") or {}).get("url", "")
    except (OSError, ValueError, AttributeError):
        return None
    for suffix in ("/mcp/", "/mcp"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url or None


async def _doctor(args: argparse.Namespace) -> int:
    """Diagnose common Citadel misconfigs and (with --fix) repair the safe ones."""
    repo = Path(args.repo).expanduser() if args.repo else git_root_or_cwd()
    config_path = Path(args.config).expanduser() if args.config else capture_config_path()
    try:
        cap_node = load_capture_config(config_path).node_url
    except ValueError:
        cap_node = None
    node_url = args.node_url or cap_node or DEFAULT_NODE_URL
    token = capture_token() or None
    as_json = getattr(args, "json", False)
    color = supports_color() and not as_json

    async def _gather() -> Any:
        return await asyncio.to_thread(
            gather_status, node_url, token, repo=repo, config_path=config_path,
            with_search=False, with_recent=False,
        )

    if as_json:
        report = await _gather()
    else:
        with _Spinner("Diagnosing Citadel…"):
            report = await _gather()
    checks = {c.name: c for c in report.checks}

    issues: list[dict[str, Any]] = []
    env_token = bool(os.getenv(TOKEN_ENV))
    rc_path = detect_shell_rc()
    try:
        rc_has = rc_path.exists() and f"{TOKEN_ENV}=" in rc_path.read_text()
    except OSError:
        rc_has = False
    if not env_token and rc_has:
        issues.append({"problem": f"token is in {rc_path} but not this shell's env",
                       "fix": f"source {rc_path}  (or open a new shell)"})
    elif not env_token and not rc_has:
        issues.append({"problem": "no seat token configured", "fix": "citadel onboard"})

    node = checks.get("node")
    if node and not node.ok:
        issues.append({"problem": f"Node unreachable at {node_url} ({node.detail})",
                       "fix": "check the Node URL / network"})
    auth = checks.get("auth")
    # Only call it a token rejection when the Node is actually reachable — when
    # the Node is down, auth fails too, and we must not tell the user to rotate
    # a perfectly valid token.
    if node and node.ok and token and auth and not auth.ok:
        issues.append({"problem": f"Node rejected the token ({auth.detail})",
                       "fix": "token revoked/expired or wrong Node — re-mint (`citadel seat create`) or re-onboard"})

    mcp_node = _mcp_node_url(repo / ".mcp.json")
    if mcp_node and cap_node and mcp_node.rstrip("/") != cap_node.rstrip("/"):
        issues.append({"problem": f".mcp.json Node ({mcp_node}) disagrees with capture config ({cap_node})",
                       "fix": f"citadel onboard --node-url {cap_node}"})

    if checks.get("pre_push_hook") and not checks["pre_push_hook"].ok:
        issues.append({"problem": "git pre-push autosync hook missing", "fix": "citadel doctor --fix", "kind": "pre_push"})
    if checks.get("session_hook") and not checks["session_hook"].ok:
        issues.append({"problem": "Claude SessionEnd/SessionStart hooks missing", "fix": "citadel doctor --fix", "kind": "session"})
    if checks.get("mcp") and not checks["mcp"].ok:
        issues.append({"problem": ".mcp.json missing the citadel MCP server", "fix": "citadel doctor --fix", "kind": "mcp"})

    fixed: list[str] = []
    fixed_kinds: set[str] = set()
    if getattr(args, "fix", False):
        for issue in issues:
            kind = issue.get("kind")
            try:
                if kind == "pre_push":
                    if not install_pre_push_hook(repo).startswith("skipped"):
                        fixed.append("pre-push hook")
                        fixed_kinds.add(kind)
                elif kind == "session":
                    merge_claude_settings(claude_user_settings_path())
                    fixed.append("Claude hooks")
                    fixed_kinds.add(kind)
                elif kind == "mcp":
                    merge_mcp_config(repo / ".mcp.json", node_url)
                    fixed.append("MCP server")
                    fixed_kinds.add(kind)
            except (ValueError, OSError):
                pass

    # After --fix, an auto issue whose fix was applied is resolved; manual issues
    # (no kind) always remain. Exit 0 only when nothing is left unresolved.
    unresolved = [i for i in issues if not i.get("kind") or i.get("kind") not in fixed_kinds]
    rc = 1 if unresolved else 0

    if as_json:
        _print_json({
            "ok": not issues,
            "node_url": node_url,
            "issues": [{k: v for k, v in i.items() if k != "kind"} for i in issues],
            "fixed": fixed,
            "resolved": not unresolved,
        })
        return rc

    print(banner(color=color))
    print()
    if not issues:
        print(paint("✓ No problems found.", "green", enable=color))
        return 0
    print(paint(f"Found {len(issues)} issue(s):", "yellow", enable=color))
    for issue in issues:
        print(f"  {mark(False, enable=color)} {issue['problem']}")
        print(f"      {paint('fix: ' + issue['fix'], 'dim', enable=color)}")
    if fixed and not unresolved:
        print()
        print(paint(f"✓ Fixed: {', '.join(fixed)}. All clear.", "green", enable=color))
    elif fixed:
        print()
        print(paint(f"Applied: {', '.join(fixed)}. Remaining items need you (see above).", "yellow", enable=color))
    elif any(i.get("kind") for i in issues):
        print()
        print(paint("Run `citadel doctor --fix` to apply the auto-fixable ones.", "dim", enable=color))
    return rc


def _humanize_status(status: str) -> tuple[str, bool, bool]:
    """Map a raw onboard step status → (human text, ok, skipped).

    Step functions return machine tokens like ``skipped:not-git``; humans should
    never see those. Skipped steps are not failures (they render with ⊘).
    """
    if status.startswith("skipped:"):
        reason = status.split(":", 1)[1].replace("-", " ")
        reason = {"not git": "not a git repo"}.get(reason, reason)
        return f"skipped ({reason})", True, True
    return status, True, False


def _print_banner_animated(text: str, color: bool) -> None:
    """Reveal the banner line-by-line for a little ceremony (TTY + color only)."""
    if not (color and sys.stdout.isatty()):
        print(text)
        return
    import time

    for line in text.split("\n"):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        time.sleep(0.035)


def _render_onboard_identity(auth: Any, node_url: str, color: bool) -> str:
    """Who this token belongs to — seat, role, access — shown on onboard."""
    if not getattr(auth, "ok", False):
        detail = getattr(auth, "detail", "could not verify")
        return (
            f"  {mark(False, enable=color)} "
            + paint(f"token not verified ({detail}) — saved anyway; run `citadel status` to recheck.", "yellow", enable=color)
        )
    ident = getattr(auth, "data", None) or {}
    seat = ident.get("seat_slug") or ident.get("actor") or "—"
    caps = ident.get("capabilities") or {}
    access = " · ".join(
        flag for flag, on in (("read", caps.get("read")), ("write", caps.get("write")), ("admin", caps.get("admin"))) if on
    ) or "—"
    writes = f"seat:{seat}" if ident.get("seat_slug") else "shared org dataset"
    return "\n".join([
        paint(f"  {mark(True, enable=color)} authenticated", "green", enable=color),
        f"      seat     {paint(str(seat), 'cyan', enable=color)}",
        f"      role     {ident.get('role') or '—'}",
        f"      access   {access}",
        f"      writes   {writes}",
        paint(f"      node     {node_url}", "dim", enable=color),
    ])


async def _onboard(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser() if args.repo else git_root_or_cwd()
    as_json = getattr(args, "json", False)
    interactive = sys.stdin.isatty() and not args.non_interactive and not as_json
    color = supports_color() and not as_json
    node_url = (getattr(args, "node_url", None) or DEFAULT_NODE_URL).rstrip("/")

    if interactive:
        _print_banner_animated(banner(color=color), color)

    token = (args.token or os.environ.get(TOKEN_ENV) or "").strip()
    if not token and interactive:
        # Guide the new user to the token instead of dead-ending on an error.
        print(
            f"\nGet your seat token from the Citadel dashboard:  "
            f"{paint(node_url, 'cyan', enable=color)}\n"
            "  (log in with the admin key → Create Seat → copy the ctdl_… token)\n"
        )
        try:
            # getpass: the pasted secret is not echoed to the screen/scrollback.
            token = getpass.getpass("Paste your Citadel seat token (ctdl_…): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
    if not token:
        print(
            "citadel onboard: no token — pass --token or set CITADEL_MCP_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        return 1

    # Verify the token + resolve its identity (seat / role / access) to show the
    # user who they're onboarding as. Interactive-only: keeps scripts/CI offline.
    auth = None
    if interactive:
        from kb.status import check_auth

        with _Spinner("Verifying your token…"):
            auth = await asyncio.to_thread(check_auth, node_url, token)

    rc_path = Path(args.shell_rc).expanduser() if args.shell_rc else detect_shell_rc()
    steps: list[tuple[str, str]] = []
    try:
        steps.append((f"token → {rc_path}", ensure_token_in_rc(rc_path, token)))
        steps.append(("git pre-push hook", install_pre_push_hook(repo)))
        # Session hooks go to the USER-scope settings so they fire across every
        # repo, not only the onboard repo (#38).
        steps.append(("SessionEnd hook", merge_claude_settings(claude_user_settings_path())))
        if not args.no_mcp:
            steps.append(("MCP server (.mcp.json)", merge_mcp_config(repo / ".mcp.json", node_url)))
    except ValueError as exc:
        print(f"citadel onboard: {exc}", file=sys.stderr)
        return 1

    # A custom --node-url is persisted to the capture config so MCP and capture
    # target the same Node (no split-brain). Done before the roots wizard, which
    # preserves node_url when it re-saves.
    if getattr(args, "node_url", None):
        try:
            cfg_path = capture_config_path()
            existing = load_capture_config(cfg_path)
            save_capture_config(
                CaptureConfig(node_url=node_url, roots=existing.roots, version=existing.version),
                path=cfg_path,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            steps.append((f"node url → {cfg_path}", node_url))
        except ValueError:
            pass

    # Optionally collect an OpenRouter key so local `cognify`/`cognify --verify`
    # and proactive-ingest work out of the box (#35). Interactive-only; written
    # to the shell rc next to the seat token.
    if interactive:
        try:
            llm_key = getpass.getpass(
                "Optional: paste an OpenRouter API key for local cognify "
                "(enter to skip): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            llm_key = ""
        if llm_key:
            steps.append(
                (
                    f"OpenRouter key → {rc_path}",
                    ensure_env_in_rc(
                        rc_path,
                        "OPENROUTER_API_KEY",
                        llm_key,
                        comment="OpenRouter key for Citadel local cognify (added by `citadel onboard`)",
                    ),
                )
            )
        print(
            "  (local cognify also needs: pipx install 'citadel-archive[server]')"
        )

    # Always seed the repo toplevel as a capture root (unless --no-capture) so the
    # pre-push hook is not a guaranteed no-op out of the box (#43/#35). The wizard
    # only runs interactively, but a default root is persisted either way.
    if not args.no_capture:
        cfg_path = capture_config_path()
        cfg = load_capture_config(cfg_path)
        if not cfg.roots:
            cfg = cfg.with_root(str(repo), (DEFAULT_ROOT_TAG,))  # 'personal' never promotes
        if interactive:
            answer = input("\nSet up Approved Capture Roots now? [Y/n]: ").strip().lower()
            if answer in ("", "y", "yes"):
                cfg = _wizard_roots(cfg)
        save_capture_config(
            cfg, path=cfg_path, updated_at=datetime.now(timezone.utc).isoformat()
        )
        steps.append((f"capture roots → {cfg_path}", f"{len(cfg.roots)} root(s)"))

    if interactive and not getattr(args, "no_tools", False):
        _wire_detected_tools(node_url, color=color)

    if as_json:
        _print_json(
            {
                "ok": True,
                "repo": str(repo),
                "shell_rc": str(rc_path),
                "token_masked": mask_token(token),
                "steps": [{"name": name, "status": status} for name, status in steps],
            }
        )
        return 0

    if not interactive:
        print(banner(color=color))
    if auth is not None:
        print()
        print(_render_onboard_identity(auth, node_url, color))
    print(f"\nCitadel onboarding for {repo}  (token {mask_token(token)}):")
    for label, status in steps:
        text, ok, skipped = _humanize_status(status)
        sigil = paint(SKIP, "yellow", enable=color) if skipped else mark(ok, enable=color)
        print(f"  {sigil} {label}  {paint(text, 'dim', enable=color)}")
    done = sum(1 for _, status in steps if not status.startswith("skipped"))
    print()
    print(paint(f"Citadel configured — {done}/{len(steps)} steps wired.", "green", enable=color))
    print(
        f"\nNext: restart your shell (or `source {rc_path}`), then in your agent ask:\n"
        '  "use citadel_search to find what we decided about the vault"'
    )
    return 0


_HOME_MENU = (
    ("Get started", (
        ("onboard", "one-command setup — token · hooks · MCP · capture roots"),
        ("status", "connection · identity · local setup (--json for agents)"),
        ("doctor", "diagnose setup problems · --fix to repair"),
    )),
    ("Capture", (
        ("setup", "declare Approved Capture Roots (~/.citadel/capture.json)"),
        ("capture", "push summaries of approved roots to your Node"),
        ("promotion", "list · approve · reject · run the Promotion Agent queue"),
    )),
    ("Knowledge", (
        ("search", "search the Organization Vault"),
        ("ingest", "add a durable note to your Node"),
    )),
    ("Connect & admin", (
        ("mcp", "add Citadel MCP to Claude · Cursor · Codex · …"),
        ("seat", "create · list seats and mint tokens (admin)"),
        ("token", "create · revoke standalone tokens (admin)"),
    )),
)


def _already_onboarded() -> bool:
    """Network-free check: has the user ever completed onboarding?

    Onboarding is "done" once the token is wired (any one ⇒ onboarded), checked
    offline so the home screen and the first-run gate stay instant and work
    without the Node:
      1. CITADEL_MCP_ACCESS_TOKEN in the environment (current shell)
      2. an ``export CITADEL_MCP_ACCESS_TOKEN=`` line in the shell rc — the signal
         that survives a fresh post-install shell, where the env var isn't set yet

    A capture config alone is NOT a signal: ``citadel setup`` writes one without
    ever wiring a token, so counting it would falsely suppress first-run
    onboarding and show "✓ set up" with no token.
    """
    if os.environ.get(TOKEN_ENV):
        return True
    try:
        rc = detect_shell_rc()
        if rc.exists() and f"{TOKEN_ENV}=" in rc.read_text():
            return True
    except OSError:
        pass
    return False


def _print_home() -> None:
    color = supports_color()
    print(banner_large(color=color))
    print()
    print("  " + paint("the organization vault", "dim", enable=color))
    if _already_onboarded():
        state = mark(True, enable=color) + " " + paint("set up", "green", enable=color)
    else:
        state = (
            mark(False, enable=color)
            + " "
            + paint("not set up", "red", enable=color)
            + paint(" — run ", "dim", enable=color)
            + paint("citadel onboard", "cyan", enable=color)
        )
    print("  " + state)
    print()
    # Pad command names to the widest, so descriptions form a clean column.
    pad = max(len(name) for _, rows in _HOME_MENU for name, _ in rows) + 2
    cols = shutil.get_terminal_size((80, 24)).columns
    desc_budget = cols - 4 - pad - 1  # indent + name column + gap
    for title, rows in _HOME_MENU:
        print("  " + paint(title, "bold", enable=color))
        for name, desc in rows:
            # Truncate the RAW description (never the ANSI codes) so narrow
            # terminals don't wrap and collide the next row.
            if desc_budget > 12 and len(desc) > desc_budget:
                desc = desc[: desc_budget - 1] + "…"
            label = paint(name.ljust(pad), "cyan", enable=color)
            print(f"    {label} {paint(desc, 'dim', enable=color)}")
        print()
    print("  " + paint("Run `citadel <command> --help` for details.", "dim", enable=color))


class CitadelParser(argparse.ArgumentParser):
    """argparse parser with a friendly, suggestion-aware unknown-command error."""

    def error(self, message: str) -> NoReturn:
        color = supports_color(sys.stderr)
        top = self.prog == "citadel"

        # 1) Typo / unknown choice — at the top level OR inside any group.
        if "invalid choice:" in message:
            # A bad value to a --flag with choices= is NOT an unknown command;
            # only positionals/subparser dests are (their arg name has no dash).
            arg_match = re.search(r"argument ([^:]+): invalid choice:", message)
            if arg_match and arg_match.group(1).lstrip().startswith("-"):
                return super().error(message)
            bad_match = re.search(r"invalid choice: '([^']*)'", message)
            bad = bad_match.group(1) if bad_match else ""
            choices_match = re.search(r"\(choose from (.+)\)\s*$", message)
            choices = (
                [c.strip().strip("'\"") for c in choices_match.group(1).split(",")]
                if choices_match
                else []
            )
            noun = "command" if top else "subcommand"
            lines = [paint(f"✗ unknown {noun}: {bad!r}", "red", enable=color), ""]
            matches = difflib.get_close_matches(bad, choices, n=3, cutoff=0.5)
            if matches:
                lines.append("  did you mean?")
                lines += [
                    "    " + paint(f"{self.prog} {name}", "bold", "cyan", enable=color)
                    for name in matches
                ]
                lines.append("")
            elif choices:
                lines.append("  available: " + ", ".join(paint(c, "cyan", enable=color) for c in choices))
                lines.append("")
            if top:
                lines.append("  run " + paint("citadel", "cyan", enable=color) + " to see all commands.")
            else:
                lines.append("  run " + paint(f"{self.prog} --help", "cyan", enable=color) + " for options.")
            sys.stderr.write("\n".join(lines) + "\n")
            raise SystemExit(2)

        # 2) Missing required argument(s).
        req_match = re.search(r"the following arguments are required: (.+)$", message)
        if req_match:
            missing = [m.strip() for m in req_match.group(1).split(",")]
            sub_action = next(
                (a for a in self._actions if isinstance(a, argparse._SubParsersAction)), None
            )
            # A subcommand group was invoked bare → list its subcommands.
            if sub_action and any(m.endswith("command") for m in missing):
                help_by_name = {
                    a.dest: (a.help or "") for a in getattr(sub_action, "_choices_actions", [])
                }
                pad = max((len(n) for n in sub_action.choices), default=8) + 2
                lines = [paint(f"✗ {self.prog} needs a subcommand:", "red", enable=color), ""]
                for name in sub_action.choices:
                    label = paint(name.ljust(pad), "cyan", enable=color)
                    lines.append(f"  {label}{paint(help_by_name.get(name, ''), 'dim', enable=color)}")
                lines.append("")
                lines.append(
                    "  e.g. " + paint(f"{self.prog} {next(iter(sub_action.choices))}", "bold", "cyan", enable=color)
                )
                sys.stderr.write("\n".join(lines) + "\n")
                raise SystemExit(2)
            # Otherwise a positional is missing → show what + how.
            lines = [
                paint(f"✗ {self.prog}: missing {', '.join(missing)}", "red", enable=color),
                "  " + self.format_usage().strip(),
                "  run " + paint(f"{self.prog} --help", "cyan", enable=color) + " for details.",
            ]
            sys.stderr.write("\n".join(lines) + "\n")
            raise SystemExit(2)

        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = CitadelParser(
        prog="citadel",
        description="Citadel — your Organization Vault. Search, capture, and share team knowledge.",
        epilog="Run `citadel` with no command for the guided home screen, "
        "or `citadel <command> --help` for any command.",
    )
    try:
        _version = _pkg_version("citadel-archive")
    except PackageNotFoundError:
        from kb import __version__ as _version
    parser.add_argument("--version", action="version", version=f"citadel {_version}")
    parser.add_argument(
        "--no-onboard",
        action="store_true",
        help="Skip first-run onboarding on bare `citadel` (also via CITADEL_NO_ONBOARD)",
    )
    # Not required: bare `citadel` shows the banner + command list instead of an error.
    subcommands = parser.add_subparsers(dest="command")

    status = subcommands.add_parser(
        "status",
        help="Check Citadel connection, identity, and local setup (--json for agents)",
    )
    status.add_argument("--json", action="store_true", help="Machine-readable output")
    status.add_argument("--node-url", help="Override Node URL (default: from config)")
    status.add_argument("--repo", help="Repo to check hooks/MCP in (default: git toplevel or cwd)")
    status.add_argument("--config", help="Override capture config path")
    status.add_argument("--no-search", action="store_true", help="Skip the search smoke check")
    status.add_argument("--no-recent", action="store_true", help="Skip recent-activity fetch")
    status.set_defaults(handler=_status)

    doctor = subcommands.add_parser(
        "doctor",
        help="Diagnose setup problems and suggest (or --fix) repairs",
    )
    doctor.add_argument("--fix", action="store_true", help="Apply safe auto-fixes (hooks, .mcp.json)")
    doctor.add_argument("--json", action="store_true", help="Machine-readable output")
    doctor.add_argument("--node-url", help="Override Node URL")
    doctor.add_argument("--repo", help="Repo to check (default: git toplevel or cwd)")
    doctor.add_argument("--config", help="Override capture config path")
    doctor.set_defaults(handler=_doctor)

    onboard = subcommands.add_parser(
        "onboard",
        help="One-shot teammate setup: token + hooks + MCP + capture roots",
    )
    onboard.add_argument("--token", help="Seat token (else prompt, or use env)")
    onboard.add_argument("--repo", help="Repo root (default: git toplevel or cwd)")
    onboard.add_argument("--shell-rc", help="Shell rc file for the token export")
    onboard.add_argument(
        "--node-url",
        help="Node URL to wire into MCP/capture (default: the built-in Node)",
    )
    onboard.add_argument("--no-mcp", action="store_true", help="Skip writing .mcp.json")
    onboard.add_argument(
        "--no-capture", action="store_true", help="Skip Approved Capture Roots setup"
    )
    onboard.add_argument(
        "--no-tools", action="store_true", help="Skip detecting/adding MCP to other coding tools"
    )
    onboard.add_argument(
        "--non-interactive", action="store_true", help="No prompts; requires --token"
    )
    onboard.add_argument(
        "--json", action="store_true", help="Machine-readable output (implies no prompts)"
    )
    onboard.set_defaults(handler=_onboard)

    setup = subcommands.add_parser(
        "setup",
        help="Configure local Approved Capture Roots (~/.citadel/capture.json)",
    )
    setup.add_argument("--node-url", help=f"Seat Node URL (default {DEFAULT_NODE_URL})")
    setup.add_argument(
        "--root",
        action="append",
        metavar="PATH[=tag1,tag2]",
        help="Add/replace an approved root (repeatable). Implies non-interactive.",
    )
    setup.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts; only apply --node-url / --root flags",
    )
    setup.add_argument("--show", action="store_true", help="Print current config and exit")
    setup.add_argument("--json", action="store_true", help="Machine-readable output")
    setup.add_argument("--config", help="Override config path (testing)")
    setup.set_defaults(handler=_setup)

    capture = subcommands.add_parser(
        "capture",
        help="Summarize Approved Capture Roots and POST to your Node",
    )
    capture.add_argument(
        "--root",
        action="append",
        metavar="PATH",
        help="Capture only this configured root (repeatable; default: all)",
    )
    capture.add_argument(
        "--dry-run", action="store_true", help="Print payloads without posting"
    )
    capture.add_argument("--json", action="store_true", help="Machine-readable output")
    capture.add_argument("--config", help="Override config path (testing)")
    capture.set_defaults(handler=_capture)

    promotion = subcommands.add_parser(
        "promotion",
        help="Promotion Agent queue — list, approve, reject, or run",
    )
    promotion_sub = promotion.add_subparsers(dest="promotion_command", required=True)

    promo_list = promotion_sub.add_parser("list", help="List pending promotion items")
    promo_list.add_argument(
        "--status",
        default="pending",
        choices=("pending", "approved", "rejected"),
        help="Queue filter (default: pending)",
    )
    promo_list.add_argument("--json", action="store_true", help="Machine-readable output")
    promo_list.add_argument("--node-url", help="Override Node URL")
    promo_list.set_defaults(handler=_promotion_list)

    promo_approve = promotion_sub.add_parser("approve", help="Approve a pending item")
    promo_approve.add_argument("item_id", help="Promotion item id (promo_…)")
    promo_approve.add_argument("--note", help="Optional audit note")
    promo_approve.add_argument("--json", action="store_true")
    promo_approve.add_argument("--node-url", help="Override Node URL")
    promo_approve.set_defaults(handler=_promotion_approve)

    promo_reject = promotion_sub.add_parser("reject", help="Reject a pending item")
    promo_reject.add_argument("item_id", help="Promotion item id (promo_…)")
    promo_reject.add_argument("--note", help="Optional audit note")
    promo_reject.add_argument("--json", action="store_true")
    promo_reject.add_argument("--node-url", help="Override Node URL")
    promo_reject.set_defaults(handler=_promotion_reject)

    promo_run = promotion_sub.add_parser(
        "run",
        help="Run the Promotion Agent for your seat (dry-run by default)",
    )
    promo_run.add_argument(
        "--execute",
        action="store_true",
        help="Actually promote / queue (default is dry-run)",
    )
    promo_run.add_argument(
        "--dataset",
        help="Seat dataset to scan (default: token's seat)",
    )
    promo_run.add_argument("--max-items", type=int, help="Cap candidates per run")
    promo_run.add_argument("--json", action="store_true")
    promo_run.add_argument("--node-url", help="Override Node URL")
    promo_run.set_defaults(handler=_promotion_run)

    seat = subcommands.add_parser(
        "seat",
        help="Manage seats (admin — reads the admin key from CITADEL_ADMIN_KEY)",
    )
    seat_sub = seat.add_subparsers(dest="seat_command", required=True)

    seat_list = seat_sub.add_parser("list", help="List seats, roles, and active token counts")
    seat_list.add_argument("--json", action="store_true", help="Machine-readable output")
    seat_list.add_argument("--node-url", help="Override Node URL")
    seat_list.set_defaults(handler=_seat_list)

    seat_create = seat_sub.add_parser(
        "create", help="Create a seat and mint its writer token (printed once)"
    )
    seat_create.add_argument("name", help='Human name, e.g. "Alice Smith"')
    seat_create.add_argument("slug", help="Seat slug, e.g. alice (a-z, 0-9, hyphen)")
    seat_create.add_argument("--email", help="Optional contact email")
    seat_create.add_argument(
        "--role", default="writer", choices=("writer", "reader"), help="Seat role (default: writer)"
    )
    seat_create.add_argument(
        "--no-token", action="store_true", help="Create the seat without issuing a token"
    )
    seat_create.add_argument("--json", action="store_true", help="Machine-readable output")
    seat_create.add_argument("--node-url", help="Override Node URL")
    seat_create.set_defaults(handler=_seat_create)

    seat_token = seat_sub.add_parser(
        "token", help="Mint a fresh token for an EXISTING seat (re-link a lost seat token)"
    )
    seat_token.add_argument("slug", help="Seat slug, e.g. sarthi")
    seat_token.add_argument("--json", action="store_true", help="Machine-readable output")
    seat_token.add_argument("--node-url", help="Override Node URL")
    seat_token.set_defaults(handler=_seat_token)

    token = subcommands.add_parser(
        "token",
        help="Manage standalone tokens (admin — reads CITADEL_ADMIN_KEY)",
    )
    token_sub = token.add_subparsers(dest="token_command", required=True)

    token_create = token_sub.add_parser(
        "create", help="Issue a standalone (service-account) token, printed once"
    )
    token_create.add_argument("name", help="Token name/label")
    token_create.add_argument(
        "--role", default="reader", choices=("reader", "writer", "admin"),
        help="Token role (default: reader)",
    )
    token_create.add_argument(
        "--kind", default="service_account", choices=("service_account", "user"),
        help="Principal kind (default: service_account)",
    )
    token_create.add_argument("--dataset", help="Default dataset for the token")
    token_create.add_argument("--expires-at", help="ISO 8601 expiry timestamp (optional)")
    token_create.add_argument("--json", action="store_true", help="Machine-readable output")
    token_create.add_argument("--node-url", help="Override Node URL")
    token_create.set_defaults(handler=_token_create)

    token_revoke = token_sub.add_parser("revoke", help="Revoke a token by id (token_…)")
    token_revoke.add_argument("token_id", help="Token id to revoke (token_…)")
    token_revoke.add_argument("--json", action="store_true", help="Machine-readable output")
    token_revoke.add_argument("--node-url", help="Override Node URL")
    token_revoke.set_defaults(handler=_token_revoke)

    mcp = subcommands.add_parser(
        "mcp",
        help="Add the Citadel MCP server to your other coding tools",
    )
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)

    mcp_add = mcp_sub.add_parser(
        "add", help="Add Citadel MCP to a tool (or 'all') — writes config or prints a snippet"
    )
    mcp_add.add_argument(
        "tool", help="Tool to wire: claude, cursor, codex, gemini, windsurf, cline, zed, pi, or all"
    )
    mcp_add.add_argument("--node-url", help="Override Node URL")
    mcp_add.set_defaults(handler=_mcp_add)

    mcp_list = mcp_sub.add_parser("list", help="List detected coding tools and how each is wired")
    mcp_list.set_defaults(handler=_mcp_list)

    ingest = subcommands.add_parser(
        "ingest", help="Add a durable note to your Node (HTTP; --local for the server stack)"
    )
    ingest.add_argument("data", help="Text (or a path) to ingest")
    ingest.add_argument("--tag", action="append", default=[], help="Tag to attach (repeatable)")
    ingest.add_argument(
        "--no-cognify",
        action="store_true",
        help="Skip the post-ingest cognify (faster; data appears in search later)",
    )
    ingest.add_argument("--json", action="store_true", help="Machine-readable output")
    ingest.add_argument("--node-url", help="Override Node URL")
    ingest.add_argument(
        "--local",
        action="store_true",
        help="Ingest via the in-process server stack instead of the Node (needs the server extra)",
    )
    ingest.add_argument("--dataset", help="(--local only) dataset to write to")
    ingest.add_argument("--session", help="(--local only) session id")
    ingest.set_defaults(handler=_ingest)

    search = subcommands.add_parser("search", help="Search the Organization Vault (via the Node)")
    search.add_argument("query", help="Search query")
    search.add_argument("--top-k", type=int, default=10, help="Max results (default: 10)")
    search.add_argument("--json", action="store_true", help="Machine-readable output")
    search.add_argument("--node-url", help="Override Node URL")
    search.add_argument(
        "--local",
        action="store_true",
        help="Search the local server stack instead of the Node (needs the server extra)",
    )
    search.add_argument("--dataset", help="(--local only) dataset to search")
    search.add_argument("--session", help="(--local only) session id")
    search.set_defaults(handler=_search)

    feedback = subcommands.add_parser("feedback", help="Attach feedback to a Cognee QA entry")
    feedback.add_argument("qa_id")
    feedback.add_argument("--score", type=int, choices=[-1, 0, 1])
    feedback.add_argument("--text")
    feedback.add_argument("--dataset")
    feedback.add_argument("--session")
    feedback.set_defaults(handler=_feedback)

    improve = subcommands.add_parser("improve", help="Run Cognee improvement")
    improve.add_argument("--dataset", help="Dataset to improve")
    # Accept --session as an alias for parity with ingest/search/feedback.
    improve.add_argument("--session-id", "--session", action="append", dest="session_id",
                         help="Session id to improve (repeatable)")
    improve.set_defaults(handler=_improve)

    cognify = subcommands.add_parser(
        "cognify",
        help="Cognify already-added data in a dataset (recover uncognified data)",
    )
    cognify.add_argument("--dataset")
    cognify.add_argument(
        "--verify",
        action="store_true",
        help="Ingest a unique marker, cognify, and confirm it lands in the graph",
    )
    cognify.set_defaults(handler=_cognify)

    sync_github = subcommands.add_parser(
        "sync-github",
        help="Fetch GitHub organization activity and ingest a daily digest",
    )
    sync_github.add_argument("--org")
    sync_github.add_argument("--state-path")
    sync_github.add_argument("--max-repos", type=int)
    sync_github.add_argument("--max-events", type=int)
    sync_github.add_argument("--max-commits-per-repo", type=int)
    sync_github.add_argument("--force", action="store_true")
    sync_github.add_argument("--dry-run", action="store_true")
    sync_github.add_argument("--skip-improve", action="store_true")
    sync_github.add_argument("--skip-commits", action="store_true")
    sync_github.add_argument("--skip-unchanged", action="store_true")
    sync_github.set_defaults(handler=_sync_github)

    sync_repo_content = subcommands.add_parser(
        "sync-repo-content",
        help="Fetch READMEs, skills, and docs from allowlisted repos and cognify them",
    )
    sync_repo_content.add_argument("--force", action="store_true")
    sync_repo_content.add_argument("--dry-run", action="store_true")
    sync_repo_content.set_defaults(handler=_sync_repo_content)

    learn = subcommands.add_parser(
        "learn",
        help="Run the source learning agent across configured sources",
    )
    learn.add_argument("--status", action="store_true")
    learn.add_argument("--force", action="store_true")
    learn.add_argument("--dry-run", action="store_true")
    learn.add_argument("--post-to-chat", action="store_true")
    learn.add_argument("--hide-digest-preview", action="store_true")
    learn.set_defaults(handler=_learn)

    return parser


def main() -> None:
    from kb.logging_utils import configure_logging

    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    # One Ctrl-C guard around every dispatch path (first-run onboarding + handlers)
    # so quitting a prompt exits cleanly (130) instead of dumping a traceback.
    # SystemExit (carrying handler return codes) is a different type and propagates.
    try:
        if not getattr(args, "command", None):
            # Bare `citadel`: on a brand-new interactive install, drop straight into
            # guided onboarding once; afterwards show the branded home screen. The
            # opt-outs (--no-onboard / CITADEL_NO_ONBOARD / any non-TTY) keep cron,
            # CI, agents, and pipes safe — they never block on a prompt.
            opted_out = bool(os.getenv("CITADEL_NO_ONBOARD")) or getattr(args, "no_onboard", False)
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
            if interactive and not opted_out and not _already_onboarded():
                onboard_args = parser.parse_args(["onboard"])
                asyncio.run(onboard_args.handler(onboard_args))
                print()
            # Branded home screen (hero + curated command menu).
            _print_home()
            raise SystemExit(0)
        # Handlers may return an int exit code (capture/setup); others return None.
        raise SystemExit(asyncio.run(args.handler(args)) or 0)
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
