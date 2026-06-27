from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    detect_shell_rc,
    ensure_token_in_rc,
    git_root_or_cwd,
    install_pre_push_hook,
    mask_token,
    merge_claude_settings,
    merge_mcp_config,
)
from kb.github_sync import GitHubOrgSyncer
from kb.learning_agent import LearningAgent
from kb.models import FeedbackRequest
from kb.repo_content_sync import RepoContentSyncer
from kb.service import Citadel


def _print_json(value: Any) -> None:
    print(json.dumps(value, default=str, indent=2))


async def _ingest(args: argparse.Namespace) -> None:
    kb = Citadel.from_env()
    result = await kb.ingest(
        args.data,
        dataset=args.dataset,
        tags=args.tag,
        session_id=args.session,
    )
    _print_json(result.__dict__)


async def _search(args: argparse.Namespace) -> None:
    kb = Citadel.from_env()
    results = await kb.search(
        args.query,
        dataset=args.dataset,
        session_id=args.session,
        top_k=args.top_k,
    )
    _print_json(results)


async def _feedback(args: argparse.Namespace) -> None:
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


async def _improve(args: argparse.Namespace) -> None:
    kb = Citadel.from_env()
    result = await kb.improve(dataset=args.dataset, session_ids=args.session_id)
    _print_json(result)


async def _cognify(args: argparse.Namespace) -> None:
    kb = Citadel.from_env()
    result = await kb.cognify_dataset(dataset=args.dataset, verify=args.verify)
    _print_json(result)


async def _sync_github(args: argparse.Namespace) -> None:
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


async def _sync_repo_content(args: argparse.Namespace) -> None:
    syncer = RepoContentSyncer(Citadel.from_env())
    result = await syncer.run(force=args.force, dry_run=args.dry_run)
    _print_json(result)


async def _learn(args: argparse.Namespace) -> None:
    agent = LearningAgent.from_env()
    result = await agent.status() if args.status else await agent.run(
        force=args.force,
        dry_run=args.dry_run,
        post_to_chat=args.post_to_chat,
        include_digest_preview=not args.hide_digest_preview,
    )
    _print_json(result)


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
    interactive = not args.non_interactive and not args.root and sys.stdin.isatty()

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
    print(f"\nSaved {len(config.roots)} approved root(s) to {written}")
    _print_json(load_capture_config(config_path).to_dict())
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
            "Missing CITADEL_MCP_ACCESS_TOKEN (or writer key) in environment.",
            file=sys.stderr,
        )
        return 1

    results: list[dict[str, Any]] = []
    failures = 0
    for root, payload in payloads:
        try:
            response = post_capture(config.node_url, token, payload)
            status = response.get("cognee_result", {}).get("status") or response.get("status")
            results.append({"root": root.path, "ok": True, "status": status, "tags": payload["tags"]})
            print(f"OK  {root.path} ({status})")
        except urllib.error.HTTPError as exc:
            failures += 1
            detail = exc.read().decode(errors="replace")[:200]
            results.append({"root": root.path, "ok": False, "error": f"HTTP {exc.code} {detail}"})
            print(f"FAIL {root.path}: HTTP {exc.code} {detail}", file=sys.stderr)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Node unreachable / DNS / timeout / non-HTTPS URL — isolate per root.
            failures += 1
            results.append({"root": root.path, "ok": False, "error": str(exc)})
            print(f"FAIL {root.path}: {exc}", file=sys.stderr)
    _print_json(results)
    return 1 if failures else 0


async def _onboard(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser() if args.repo else git_root_or_cwd()
    interactive = sys.stdin.isatty() and not args.non_interactive

    token = (args.token or os.environ.get(TOKEN_ENV) or "").strip()
    if not token and interactive:
        token = input("Paste your Citadel seat token (ctdl_…): ").strip()
    if not token:
        print(
            "citadel onboard: no token — pass --token or set CITADEL_MCP_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        return 1

    rc_path = Path(args.shell_rc).expanduser() if args.shell_rc else detect_shell_rc()
    steps: list[tuple[str, str]] = []
    try:
        steps.append((f"token → {rc_path}", ensure_token_in_rc(rc_path, token)))
        steps.append(("git pre-push hook", install_pre_push_hook(repo)))
        steps.append(("SessionEnd hook", merge_claude_settings(repo / ".claude" / "settings.json")))
        if not args.no_mcp:
            steps.append(("MCP server (.mcp.json)", merge_mcp_config(repo / ".mcp.json")))
    except ValueError as exc:
        print(f"citadel onboard: {exc}", file=sys.stderr)
        return 1

    want_capture = not args.no_capture and interactive
    if want_capture:
        answer = input("\nSet up Approved Capture Roots now? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            cfg_path = capture_config_path()
            cfg = _wizard_roots(load_capture_config(cfg_path))
            save_capture_config(
                cfg, path=cfg_path, updated_at=datetime.now(timezone.utc).isoformat()
            )
            steps.append((f"capture roots → {cfg_path}", f"{len(cfg.roots)} root(s)"))

    print(f"\nCitadel onboarding for {repo}  (token {mask_token(token)}):")
    for label, status in steps:
        print(f"  • {label}: {status}")
    print(
        f"\nNext: restart your shell (or `source {rc_path}`), then in your agent ask:\n"
        '  "use citadel_search to find what we decided about the vault"'
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citadel")
    subcommands = parser.add_subparsers(dest="command", required=True)

    onboard = subcommands.add_parser(
        "onboard",
        help="One-shot teammate setup: token + hooks + MCP + capture roots",
    )
    onboard.add_argument("--token", help="Seat token (else prompt, or use env)")
    onboard.add_argument("--repo", help="Repo root (default: git toplevel or cwd)")
    onboard.add_argument("--shell-rc", help="Shell rc file for the token export")
    onboard.add_argument("--no-mcp", action="store_true", help="Skip writing .mcp.json")
    onboard.add_argument(
        "--no-capture", action="store_true", help="Skip Approved Capture Roots setup"
    )
    onboard.add_argument(
        "--non-interactive", action="store_true", help="No prompts; requires --token"
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
    capture.add_argument("--config", help="Override config path (testing)")
    capture.set_defaults(handler=_capture)

    ingest = subcommands.add_parser("ingest", help="Ingest text or a path through Cognee")
    ingest.add_argument("data")
    ingest.add_argument("--dataset")
    ingest.add_argument("--session")
    ingest.add_argument("--tag", action="append", default=[])
    ingest.set_defaults(handler=_ingest)

    search = subcommands.add_parser("search", help="Search the Organization Vault")
    search.add_argument("query")
    search.add_argument("--dataset")
    search.add_argument("--session")
    search.add_argument("--top-k", type=int, default=10)
    search.set_defaults(handler=_search)

    feedback = subcommands.add_parser("feedback", help="Attach feedback to a Cognee QA entry")
    feedback.add_argument("qa_id")
    feedback.add_argument("--score", type=int, choices=[-1, 0, 1])
    feedback.add_argument("--text")
    feedback.add_argument("--dataset")
    feedback.add_argument("--session")
    feedback.set_defaults(handler=_feedback)

    improve = subcommands.add_parser("improve", help="Run Cognee improvement")
    improve.add_argument("--dataset")
    improve.add_argument("--session-id", action="append")
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
    # Handlers may return an int exit code (capture/setup); others return None.
    raise SystemExit(asyncio.run(args.handler(args)) or 0)


if __name__ == "__main__":
    main()
