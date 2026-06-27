"""Local Approved Capture Roots config (`~/.citadel/capture.json`).

Per-machine client config chosen in the `citadel setup` wizard (ADR-0007 P4.1).
Stores the seat's Node URL and the filesystem roots approved for capture, each
tagged with **Capture Root Tags** (`personal` never promotes; `org-work` is
promotion-eligible). The seat token is deliberately NOT stored here — it stays in
the environment (`CITADEL_MCP_ACCESS_TOKEN`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CAPTURE_CONFIG_VERSION = 1
DEFAULT_NODE_URL = "https://citadel-archive-production.up.railway.app"

# Preset Capture Root Tags (ADR-0007 §4). Custom tags are allowed as search
# labels; only these presets carry promotion semantics.
PRESET_ROOT_TAGS: tuple[str, ...] = ("personal", "org-work")
DEFAULT_ROOT_TAG = "personal"


def capture_config_path() -> Path:
    """Resolve `~/.citadel/capture.json`, honoring test/CI overrides."""
    override = os.getenv("CITADEL_CAPTURE_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    home = os.getenv("CITADEL_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".citadel"
    return base / "capture.json"


def normalize_path(value: str) -> str:
    """Expand ~ and env vars, return an absolute path (no symlink resolution)."""
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    return os.path.abspath(expanded)


def normalize_tags(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Strip, lowercase, dedupe (order-preserving); default to `personal`."""
    seen: dict[str, None] = {}
    for value in values:
        stripped = value.strip().lower()
        if stripped:
            seen.setdefault(stripped, None)
    return tuple(seen) or (DEFAULT_ROOT_TAG,)


@dataclass(frozen=True)
class CaptureRoot:
    path: str
    tags: tuple[str, ...] = (DEFAULT_ROOT_TAG,)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaptureRoot":
        return cls(
            path=normalize_path(str(data.get("path", ""))),
            tags=normalize_tags(data.get("tags") or ()),
        )


@dataclass(frozen=True)
class CaptureConfig:
    node_url: str = DEFAULT_NODE_URL
    roots: tuple[CaptureRoot, ...] = ()
    version: int = CAPTURE_CONFIG_VERSION
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "node_url": self.node_url,
            "roots": [root.to_dict() for root in self.roots],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaptureConfig":
        roots = tuple(
            CaptureRoot.from_dict(item)
            for item in (data.get("roots") or ())
            if str(item.get("path", "")).strip()
        )
        return cls(
            node_url=str(data.get("node_url") or DEFAULT_NODE_URL).rstrip("/"),
            roots=roots,
            version=int(data.get("version", CAPTURE_CONFIG_VERSION)),
            updated_at=data.get("updated_at"),
        )

    def with_root(self, path: str, tags: tuple[str, ...] | list[str]) -> "CaptureConfig":
        """Add a root, or replace an existing root at the same normalized path."""
        normalized = normalize_path(path)
        new_root = CaptureRoot(path=normalized, tags=normalize_tags(tags))
        kept = tuple(root for root in self.roots if root.path != normalized)
        return CaptureConfig(
            node_url=self.node_url,
            roots=(*kept, new_root),
            version=self.version,
            updated_at=self.updated_at,
        )

    def find_root_for_path(self, path: str) -> CaptureRoot | None:
        """Return the approved root that contains `path`, if any (allowlist check)."""
        target = normalize_path(path)
        for root in self.roots:
            if target == root.path or target.startswith(root.path + os.sep):
                return root
        return None


def load_capture_config(path: Path | None = None) -> CaptureConfig:
    """Load config from disk; return defaults (no roots) if absent."""
    config_path = path or capture_config_path()
    if not config_path.exists():
        return CaptureConfig()
    data = json.loads(config_path.read_text())
    return CaptureConfig.from_dict(data)


def save_capture_config(
    config: CaptureConfig, *, path: Path | None = None, updated_at: str | None = None
) -> Path:
    """Write config atomically with 0600 perms (paths can be private)."""
    config_path = path or capture_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(config_path.parent, 0o700)
    except OSError:
        pass
    payload = config.to_dict()
    if updated_at is not None:
        payload["updated_at"] = updated_at
    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, config_path)
    return config_path
