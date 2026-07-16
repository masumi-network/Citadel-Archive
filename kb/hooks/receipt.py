"""Local capture receipts for the fail-silent sync hooks (DX-5).

The git-push and SessionEnd hooks capture silently by design. That leaves a dev
with no signal that anything happened — the "black box after onboard" problem.
A receipt makes the invisible visible WITHOUT weakening the hook contract:

- **Stdlib-only + best-effort.** Every function swallows its own errors, so a
  receipt can never break a hook (hooks always exit 0, never block a git push
  or session close).
- **Never surfaces the token.** Receipts carry only counts/summaries.
- One line per capture is appended to ``~/.citadel/activity.log`` (0600, honoring
  ``$CITADEL_HOME`` / ``$CITADEL_CAPTURE_CONFIG_PATH``) so ``citadel activity
  --local`` can show it offline; the line is also printed to stderr when
  ``CITADEL_HOOK_VERBOSE`` is truthy.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Keep the log bounded — it is a rolling receipt trail, not an audit store.
_MAX_BYTES = 128 * 1024
_KEEP_LINES = 200


def _base_dir() -> Path:
    """The local Citadel dir — mirrors ``kb.capture_config.capture_config_path``'s
    resolution so receipts land next to ``capture.json``."""
    override = os.getenv("CITADEL_CAPTURE_CONFIG_PATH")
    if override:
        return Path(override).expanduser().parent
    home = os.getenv("CITADEL_HOME")
    return Path(home).expanduser() if home else Path.home() / ".citadel"


def activity_log_path() -> Path:
    return _base_dir() / "activity.log"


def _verbose() -> bool:
    return (os.getenv("CITADEL_HOOK_VERBOSE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _roll(path: Path) -> None:
    """Trim the log to the last ``_KEEP_LINES`` once it grows past ``_MAX_BYTES``."""
    try:
        if path.stat().st_size <= _MAX_BYTES:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_KEEP_LINES:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def write_receipt(kind: str, summary: str) -> None:
    """Append a one-line capture receipt; echo to stderr when verbose. Never raises.

    ``kind`` is a short tag (``push`` / ``session``); ``summary`` is human text
    like ``captured commit a1b2c3d → your Node``. Contains no token.
    """
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {kind}  {summary}"
    try:
        path = activity_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        _roll(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        pass  # a receipt must never break the hook
    if _verbose():
        try:
            sys.stderr.write(f"citadel: {summary}\n")
        except Exception:
            pass
