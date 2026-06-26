#!/usr/bin/env python3
"""Railway run-mode dispatcher for Citadel services.

Modes (via ``CITADEL_RUN_MODE``):

- ``web`` (default): the FastAPI Organization Vault service.
- ``github-sync`` / ``learning-agent``: the single GitHub org learning job.
- ``backup-mirror``: the single Vault Backup Mirror export job.
- ``cognify`` / ``cognify-verify``: re-cognify already-added data in a dataset
  (``CITADEL_COGNIFY_DATASET``, default dataset otherwise) to recover data that
  was added but never cognified; ``cognify-verify`` also ingests a unique marker
  and confirms it lands in the graph.
- ``pipeline`` (also ``all``/``cron``): the full scheduled pipeline —
  GitHub org sync, skills catalog refresh, self-improvement pass, and backup
  mirror export. Each stage is toggleable via env, logs a per-stage summary
  line, and a failed stage never stops the stages after it. The process exits
  nonzero only when every enabled stage fails.
- ``linear-sync``: sync the Linear workspace to Central and mirror assignee
  issues into seat Nodes (requires ``CITADEL_LINEAR_API_KEY``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Callable

logger = logging.getLogger("citadel.pipeline")


def _bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def web_command(*, port: str) -> list[str]:
    return [
        "python",
        "-m",
        "uvicorn",
        "kb.server:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]


def _github_sync_stage() -> int:
    from scripts.run_github_sync import run as run_github_sync

    return run_github_sync()


def _skills_refresh_stage() -> int:
    from kb.skills import refresh_skill_catalog

    result = refresh_skill_catalog()
    logger.info(
        "Skills catalog refreshed: skills=%s changed=%s added=%s removed=%s",
        result["skills"],
        ",".join(result["changed"]) or "none",
        ",".join(result["added"]) or "none",
        ",".join(result["removed"]) or "none",
    )
    return 0


def _self_improve_stage() -> int:
    from scripts.run_self_improve import run as run_self_improve

    return run_self_improve()


def _backup_mirror_stage() -> int:
    from scripts.run_backup_mirror import run as run_backup_mirror

    return run_backup_mirror()


def _repo_content_sync_stage() -> int:
    from kb.repo_content_sync import RepoContentSyncer
    from kb.service import Citadel

    result = asyncio.run(RepoContentSyncer(Citadel.from_env()).run())
    if not result.get("ok"):
        return 1
    if result.get("enabled") is False:
        logger.info("Repo content sync skipped: %s", result.get("reason"))
        return 0
    logger.info(
        "Repo content sync finished: repos=%s ingested=%s skipped=%s improved=%s",
        result.get("repos_scanned"),
        result.get("files_ingested"),
        result.get("files_skipped"),
        result.get("improved"),
    )
    return 0


def _cognify_mode(*, verify: bool) -> int:
    from kb.service import Citadel

    dataset = os.getenv("CITADEL_COGNIFY_DATASET") or None
    result = asyncio.run(Citadel.from_env().cognify_dataset(dataset=dataset, verify=verify))
    logger.info(
        "Cognify finished: dataset=%s graph_before=%s graph_after=%s grew=%s verify=%s",
        result.get("dataset"),
        result.get("graph_before"),
        result.get("graph_after"),
        result.get("graph_grew"),
        (result.get("verification") or {}).get("ok") if verify else result.get("verify"),
    )
    if verify and not (result.get("verification") or {}).get("ok"):
        logger.error("Cognify verification failed: %s", result.get("verification"))
        return 1
    return 0


def pipeline_stages() -> list[tuple[str, bool, Callable[[], int]]]:
    """(name, enabled, runner) for every pipeline stage, in execution order."""
    return [
        (
            "github_sync",
            _bool(os.getenv("CITADEL_PIPELINE_GITHUB_SYNC_ENABLED"), default=True),
            _github_sync_stage,
        ),
        (
            "repo_content_sync",
            _bool(os.getenv("CITADEL_PIPELINE_REPO_CONTENT_SYNC_ENABLED"), default=True),
            _repo_content_sync_stage,
        ),
        (
            "skills_refresh",
            _bool(os.getenv("CITADEL_PIPELINE_SKILLS_REFRESH_ENABLED"), default=True),
            _skills_refresh_stage,
        ),
        (
            "self_improve",
            _bool(os.getenv("CITADEL_SELF_IMPROVE_ENABLED"), default=False),
            _self_improve_stage,
        ),
        (
            "backup_mirror",
            _bool(os.getenv("CITADEL_PIPELINE_BACKUP_MIRROR_ENABLED"), default=True),
            _backup_mirror_stage,
        ),
    ]


def run_pipeline() -> int:
    """Run every enabled stage; continue past failures.

    Exit code is nonzero only when all enabled stages fail, so one flaky
    source never blocks the rest of the scheduled learning work.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            stream=sys.stdout,
        )

    succeeded: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    for name, enabled, runner in pipeline_stages():
        if not enabled:
            skipped.append(name)
            logger.info("Pipeline stage %s: skipped (disabled via env)", name)
            continue
        logger.info("Pipeline stage %s: starting", name)
        try:
            code = runner()
        except Exception as exc:
            logger.error(
                "Pipeline stage %s: FAILED with %s: %s",
                name,
                exc.__class__.__name__,
                exc,
            )
            failed.append(name)
            continue
        if code == 0:
            succeeded.append(name)
            logger.info("Pipeline stage %s: ok", name)
        else:
            failed.append(name)
            logger.error("Pipeline stage %s: FAILED with exit code %s", name, code)

    logger.info(
        "Pipeline finished: succeeded=%s failed=%s skipped=%s",
        ",".join(succeeded) or "none",
        ",".join(failed) or "none",
        ",".join(skipped) or "none",
    )
    if failed and not succeeded:
        return 1
    return 0


def run(mode: str | None = None) -> int:
    resolved_mode = (mode or os.getenv("CITADEL_RUN_MODE") or "web").strip() or "web"
    if resolved_mode == "web":
        os.execvp("python", web_command(port=os.getenv("PORT", "8000")))
        raise RuntimeError("os.execvp returned unexpectedly.")
    if resolved_mode in {"github-sync", "learning-agent"}:
        from scripts.run_github_sync import run as run_github_sync

        return run_github_sync()
    if resolved_mode == "backup-mirror":
        from scripts.run_backup_mirror import run as run_backup_mirror

        return run_backup_mirror()
    if resolved_mode in {"cognify", "cognify-verify"}:
        return _cognify_mode(verify=resolved_mode == "cognify-verify")
    if resolved_mode in {"pipeline", "all", "cron"}:
        return run_pipeline()
    if resolved_mode == "linear-sync":
        from kb.access import AccessStore
        from kb.linear_sync import LinearSyncer
        from kb.service import Citadel

        async def _run() -> int:
            citadel = Citadel.from_env()
            access_store = AccessStore(citadel.config.access_store_path)
            result = await LinearSyncer(
                citadel,
                access_store=access_store,
            ).run(force=True)
            if not result.get("ok"):
                logger.error("Linear sync failed: %s", result.get("reason"))
                return 1
            logger.info(
                "Linear sync finished: issues=%s mirrored=%s",
                result.get("issue_count"),
                result.get("mirrored_count"),
            )
            return 0

        return asyncio.run(_run())
    print(f"Unsupported CITADEL_RUN_MODE: {resolved_mode}", file=sys.stderr)
    return 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
