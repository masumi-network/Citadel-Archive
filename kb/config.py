from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
from typing import Iterable

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - exercised only before dependencies are installed.
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _github_state_path(value: str | None) -> str:
    if value:
        return value
    root = (
        os.getenv("CITADEL_STATE_DIRECTORY")
        or os.getenv("SYSTEM_ROOT_DIRECTORY")
        or ("/data/.citadel" if Path("/data").exists() else ".citadel")
    )
    return str(Path(root) / "github_sync_state.json")


def _access_store_path(value: str | None) -> str:
    if value:
        return value
    root = (
        os.getenv("CITADEL_STATE_DIRECTORY")
        or os.getenv("SYSTEM_ROOT_DIRECTORY")
        or ("/data/.citadel" if Path("/data").exists() else ".citadel")
    )
    return str(Path(root) / "access.json")


def _obsidian_sync_state_path(value: str | None) -> str:
    if value:
        return value
    root = (
        os.getenv("CITADEL_STATE_DIRECTORY")
        or os.getenv("SYSTEM_ROOT_DIRECTORY")
        or ("/data/.citadel" if Path("/data").exists() else ".citadel")
    )
    return str(Path(root) / "obsidian_sync_state.json")


@dataclass(frozen=True)
class CitadelConfig:
    tenant_id: str = "personal"
    user_id: str = "local"
    admin_key: str | None = None
    reader_keys: tuple[str, ...] = field(default_factory=tuple)
    writer_keys: tuple[str, ...] = field(default_factory=tuple)
    access_store_path: str = ".citadel/access.json"
    obsidian_sync_state_path: str = ".citadel/obsidian_sync_state.json"
    audit_max_events: int = 1000
    default_dataset: str = "personal"
    default_session: str = "personal-session"
    default_tags: tuple[str, ...] = field(default_factory=tuple)
    min_chars: int = 3
    exclude_patterns: tuple[str, ...] = (
        ".git/*",
        ".venv/*",
        "__pycache__/*",
        "node_modules/*",
    )
    auto_improve: bool = False
    build_global_context_index: bool = False
    github_org: str = "masumi-network"
    github_sync_dataset: str = "masumi-network"
    github_sync_session: str = "masumi-github-daily"
    github_sync_state_path: str = ".citadel/github_sync_state.json"
    github_sync_max_repos: int = 100
    github_sync_max_events: int = 50
    github_sync_max_commits_per_repo: int = 5
    github_sync_include_commits: bool = True
    github_sync_run_improve: bool = True
    github_sync_ingest_unchanged: bool = True
    github_token: str | None = None

    @classmethod
    def from_env(cls, *, env_file: str | None = ".env") -> "CitadelConfig":
        if env_file:
            load_dotenv(env_file, override=False)

        return cls(
            tenant_id=os.getenv("CITADEL_TENANT_ID", "personal"),
            user_id=os.getenv("CITADEL_USER_ID", "local"),
            admin_key=os.getenv("CITADEL_ADMIN_KEY") or None,
            reader_keys=tuple(_csv(os.getenv("CITADEL_READER_KEYS"))),
            writer_keys=tuple(_csv(os.getenv("CITADEL_WRITER_KEYS"))),
            access_store_path=_access_store_path(os.getenv("CITADEL_ACCESS_STORE_PATH")),
            obsidian_sync_state_path=_obsidian_sync_state_path(
                os.getenv("CITADEL_OBSIDIAN_SYNC_STATE_PATH")
            ),
            audit_max_events=_int(os.getenv("CITADEL_AUDIT_MAX_EVENTS"), default=1000),
            default_dataset=os.getenv("CITADEL_DEFAULT_DATASET", "personal"),
            default_session=os.getenv("CITADEL_DEFAULT_SESSION", "personal-session"),
            default_tags=tuple(_csv(os.getenv("CITADEL_DEFAULT_TAGS"))),
            min_chars=int(os.getenv("CITADEL_MIN_CHARS", "3")),
            exclude_patterns=tuple(
                _csv(os.getenv("CITADEL_EXCLUDE_PATTERNS"))
                or [".git/*", ".venv/*", "__pycache__/*", "node_modules/*"]
            ),
            auto_improve=_bool(os.getenv("CITADEL_AUTO_IMPROVE")),
            build_global_context_index=_bool(os.getenv("CITADEL_BUILD_GLOBAL_CONTEXT_INDEX")),
            github_org=os.getenv("CITADEL_GITHUB_ORG", "masumi-network"),
            github_sync_dataset=os.getenv("CITADEL_GITHUB_SYNC_DATASET", "masumi-network"),
            github_sync_session=os.getenv("CITADEL_GITHUB_SYNC_SESSION", "masumi-github-daily"),
            github_sync_state_path=_github_state_path(os.getenv("CITADEL_GITHUB_SYNC_STATE_PATH")),
            github_sync_max_repos=_int(os.getenv("CITADEL_GITHUB_SYNC_MAX_REPOS"), default=100),
            github_sync_max_events=_int(os.getenv("CITADEL_GITHUB_SYNC_MAX_EVENTS"), default=50),
            github_sync_max_commits_per_repo=_int(
                os.getenv("CITADEL_GITHUB_SYNC_MAX_COMMITS_PER_REPO"),
                default=5,
            ),
            github_sync_include_commits=_bool(
                os.getenv("CITADEL_GITHUB_SYNC_INCLUDE_COMMITS"),
                default=True,
            ),
            github_sync_run_improve=_bool(os.getenv("CITADEL_GITHUB_SYNC_RUN_IMPROVE"), default=True),
            github_sync_ingest_unchanged=_bool(
                os.getenv("CITADEL_GITHUB_SYNC_INGEST_UNCHANGED"),
                default=True,
            ),
            github_token=os.getenv("CITADEL_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or None,
        )

    def with_tags(self, tags: Iterable[str]) -> "CitadelConfig":
        merged = tuple(dict.fromkeys([*self.default_tags, *tags]))
        return replace(self, default_tags=merged)
