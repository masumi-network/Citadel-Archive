#!/usr/bin/env python3
"""Railway run-mode dispatcher for Citadel services."""

from __future__ import annotations

import os
import sys


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
    print(f"Unsupported CITADEL_RUN_MODE: {resolved_mode}", file=sys.stderr)
    return 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
