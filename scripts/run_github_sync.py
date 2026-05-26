#!/usr/bin/env python3
"""Scheduled GitHub sync trigger.

This mirrors the Nori cron shape: run one job, log a compact result, and exit
non-zero when the scheduler should mark the run as failed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _timeout() -> int:
    raw = os.getenv("CITADEL_GITHUB_SYNC_TIMEOUT_SECONDS")
    if not raw:
        return 900
    try:
        return int(raw)
    except ValueError:
        return 900


def _target_endpoint() -> str | None:
    target = (
        os.getenv("CITADEL_GITHUB_SYNC_ENDPOINT")
        or os.getenv("CITADEL_GITHUB_SYNC_TARGET_URL")
        or os.getenv("CITADEL_WEB_URL")
        or os.getenv("CITADEL_BASE_URL")
    )
    if not target:
        return None
    target = target.rstrip("/")
    if target.endswith("/api/learning-agent/run") or target.endswith("/api/github-sync/run"):
        return target
    return f"{target}/api/learning-agent/run"


def _access_key() -> str | None:
    return os.getenv("CITADEL_GITHUB_SYNC_ACCESS_KEY") or os.getenv("CITADEL_ADMIN_KEY")


def _post_json(
    url: str,
    *,
    payload: dict[str, Any],
    access_key: str,
    timeout: int,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {access_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "citadel-github-sync-cron",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            return response.status, json.loads(response_body or "{}")
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(response_body or "{}")
        except json.JSONDecodeError:
            parsed = {"detail": response_body}
        return exc.code, parsed
    except URLError as exc:
        return 599, {"detail": str(exc.reason)}


async def _run_local(force: bool, dry_run: bool) -> dict[str, Any]:
    from kb.learning_agent import LearningAgent

    return await LearningAgent.from_env().run(force=force, dry_run=dry_run)


def _log_result(result: dict[str, Any]) -> None:
    github = result.get("sources", {}).get("github", {})
    logger.info(
        "GitHub sync complete: repos=%s changed=%s events=%s commits=%s ingested=%s improved=%s",
        github.get("repos_scanned"),
        github.get("changed_count"),
        github.get("event_count"),
        github.get("commit_count"),
        result.get("ingested", github.get("ingested")),
        result.get("improved", github.get("improved")),
    )


def run() -> int:
    force = _bool(os.getenv("CITADEL_GITHUB_SYNC_FORCE"), default=False)
    dry_run = _bool(os.getenv("CITADEL_GITHUB_SYNC_DRY_RUN"), default=False)
    payload = {"force": force, "dry_run": dry_run}
    endpoint = _target_endpoint()

    if endpoint:
        access_key = _access_key()
        if not access_key:
            logger.error(
                "CITADEL_GITHUB_SYNC_ACCESS_KEY or CITADEL_ADMIN_KEY is required "
                "when CITADEL_GITHUB_SYNC_TARGET_URL is set."
            )
            return 1
        logger.info("Starting scheduled GitHub sync through %s", endpoint)
        status_code, result = _post_json(
            endpoint,
            payload=payload,
            access_key=access_key,
            timeout=_timeout(),
        )
        if status_code >= 400:
            logger.error("GitHub sync failed with HTTP %s: %s", status_code, result)
            return 1
    else:
        logger.info("Starting scheduled GitHub sync in-process")
        result = asyncio.run(_run_local(force=force, dry_run=dry_run))

    if result.get("ok") is False:
        logger.error("GitHub sync failed: %s", result)
        return 1

    _log_result(result)
    print(json.dumps(result, indent=2, default=str))
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
