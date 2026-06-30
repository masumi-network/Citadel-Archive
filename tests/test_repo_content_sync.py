from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kb.config import CitadelConfig
from kb.github_sync import GitHubAPIError
from kb.models import IngestResult
from kb.repo_content_sync import (
    DEFAULT_REPO_CONTENT_AUTOJOIN_MARKERS,
    RepoContentFile,
    RepoContentGitHubClient,
    RepoContentSyncer,
    discover_org_repos,
    discover_repo_paths,
    format_repo_content_document,
    resolve_repo_full_name,
)
from kb.repository_update import GitHubRepo


class FakeCitadel:
    def __init__(self, config: CitadelConfig) -> None:
        self.config = config


class FakeLearningProcess:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def learn(self, data: str, **kwargs: Any) -> Any:
        self.calls.append({"data": data, **kwargs})

        class Outcome:
            ingest = IngestResult(True, "accepted", kwargs.get("dataset", "x"), ())
            chunk_ingests = ()
            improve = {"ok": True} if kwargs.get("run_improve") else None

            @property
            def all_ingests(self) -> tuple[IngestResult, ...]:
                return (self.ingest,)

            @property
            def improved(self) -> bool:
                return bool(self.improve)

        return Outcome()


class FakeRepoContentClient(RepoContentGitHubClient):
    def __init__(self) -> None:
        super().__init__(token=None)
        self.files: dict[str, dict[str, str]] = {
            "masumi-network/sokosumi-cli/README.md": {
                "sha": "abc",
                "content": "# Sokosumi CLI\n\nHeadless mode docs.",
            },
            "masumi-network/sokosumi-cli/skills/sokosumi/SKILL.md": {
                "sha": "def",
                "content": "# Skill\n\nAgent workflow.",
            },
        }
        self.directories: dict[str, list[dict[str, Any]]] = {
            "masumi-network/sokosumi-cli/skills": [
                {"path": "skills/sokosumi", "type": "dir"},
            ],
            "masumi-network/sokosumi-cli/skills/sokosumi": [
                {"path": "skills/sokosumi/SKILL.md", "type": "file"},
            ],
        }

    def fetch_default_branch(self, full_name: str) -> str:
        return "main"

    def fetch_commit_sha(self, full_name: str, *, ref: str) -> str:
        return "commit123"

    def file_exists(self, full_name: str, path: str, *, ref: str) -> bool:
        return f"{full_name}/{path}" in self.files

    def fetch_file_text(self, full_name: str, path: str, *, ref: str) -> RepoContentFile | None:
        payload = self.files.get(f"{full_name}/{path}")
        if payload is None:
            return None
        return RepoContentFile(
            repo=full_name,
            path=path,
            sha=payload["sha"],
            ref=ref,
            content=payload["content"],
            html_url=f"https://github.com/{full_name}/blob/{ref}/{path}",
        )

    def list_directory(self, full_name: str, path: str, *, ref: str) -> list[dict[str, Any]]:
        return self.directories.get(f"{full_name}/{path}", [])


def test_resolve_repo_full_name() -> None:
    assert resolve_repo_full_name("sokosumi", "masumi-network") == "masumi-network/sokosumi"
    assert resolve_repo_full_name("masumi-network/sokosumi", "masumi-network") == "masumi-network/sokosumi"


def test_format_repo_content_document() -> None:
    file = RepoContentFile(
        repo="masumi-network/sokosumi-cli",
        path="README.md",
        sha="abc",
        ref="commit123",
        content="# Title",
        html_url="https://example.com",
    )
    document = format_repo_content_document(file, checked_at="2026-06-16T00:00:00Z")
    assert "masumi-network/sokosumi-cli/README.md" in document
    assert "Commit: commit123" in document
    assert "# Title" in document


def test_discover_repo_paths_includes_root_and_tree_files() -> None:
    client = FakeRepoContentClient()
    paths = discover_repo_paths(
        client,
        "masumi-network/sokosumi-cli",
        ref="commit123",
        root_paths=("README.md", "MISSING.md"),
        tree_prefixes=("skills/",),
        tree_extensions=(".md",),
        max_files=10,
    )
    assert paths == ["README.md", "skills/sokosumi/SKILL.md"]


@pytest.mark.asyncio
async def test_repo_content_syncer_ingests_changed_files(tmp_path: Path) -> None:
    config = CitadelConfig(
        repo_content_sync_enabled=True,
        repo_content_sync_dataset="masumi-network",
        repo_content_sync_session="masumi-repo-content",
        repo_content_sync_state_path=str(tmp_path / "repo_content_sync_state.json"),
        repo_content_sync_repos=("sokosumi-cli",),
        repo_content_sync_root_paths=("README.md",),
        repo_content_sync_tree_prefixes=("skills/",),
        repo_content_sync_tree_extensions=(".md",),
        repo_content_sync_max_files_per_repo=10,
        repo_content_sync_run_improve=True,
    )
    learning = FakeLearningProcess()
    syncer = RepoContentSyncer(
        FakeCitadel(config),
        client=FakeRepoContentClient(),
        state_path=config.repo_content_sync_state_path,
        learning=learning,  # type: ignore[arg-type]
    )

    first = await syncer.run()
    assert first["files_ingested"] == 2
    assert len(learning.calls) == 2
    assert learning.calls[0]["tags"] == [
        "github",
        "repo-content",
        "product-knowledge",
        "sokosumi-cli",
        "md",
    ]

    second = await syncer.run()
    assert second["files_ingested"] == 0
    assert second["files_skipped"] == 2
    assert second["files_skipped_by_reason"] == {"unchanged": 2}
    assert second["repositories"][0]["skipped_reasons"] == {"unchanged": 2}

    state = json.loads(Path(config.repo_content_sync_state_path).read_text(encoding="utf-8"))
    assert state["files"]["masumi-network/sokosumi-cli/README.md"]["sha"] == "abc"


@pytest.mark.asyncio
async def test_repo_content_syncer_respects_disabled_flag() -> None:
    config = CitadelConfig(repo_content_sync_enabled=False)
    syncer = RepoContentSyncer(FakeCitadel(config), client=FakeRepoContentClient())
    result = await syncer.run()
    assert result["enabled"] is False


class FailingRepoContentClient(RepoContentGitHubClient):
    def __init__(self) -> None:
        super().__init__(token=None)

    def fetch_default_branch(self, full_name: str) -> str:
        raise GitHubAPIError(
            "GitHub API returned 403: API rate limit exceeded for 95.90.238.57"
        )


@pytest.mark.asyncio
async def test_repo_content_syncer_marks_failure_when_all_repos_error(tmp_path: Path) -> None:
    config = CitadelConfig(
        repo_content_sync_enabled=True,
        repo_content_sync_state_path=str(tmp_path / "repo_content_sync_state.json"),
        repo_content_sync_repos=("sokosumi-cli", "sokosumi-docs"),
    )
    syncer = RepoContentSyncer(
        FakeCitadel(config),
        client=FailingRepoContentClient(),
        state_path=config.repo_content_sync_state_path,
        learning=FakeLearningProcess(),  # type: ignore[arg-type]
    )

    result = await syncer.run()

    assert result["ok"] is False
    assert result["authenticated"] is False
    assert result["repos_errored"] == 2
    assert result["files_ingested"] == 0
    assert all(repo["errors"] for repo in result["repositories"])


class FakeAutoJoinClient(RepoContentGitHubClient):
    """Org with: a marker repo, a markerless repo, and an archived marker repo."""

    def __init__(self) -> None:
        super().__init__(token=None)
        self.markers: set[str] = {
            "masumi-network/masumi-agent-messenger/AGENTS.md",
            "masumi-network/archived-repo/AGENTS.md",
            "masumi-network/sokosumi-cli/SKILL.md",
        }

    def _repo(self, name: str, *, archived: bool = False, branch: str | None = "main") -> GitHubRepo:
        return GitHubRepo(
            name=name,
            full_name=f"masumi-network/{name}",
            html_url="",
            description=None,
            language=None,
            pushed_at=None,
            updated_at=None,
            default_branch=branch,
            visibility="public",
            archived=archived,
            stargazers_count=0,
            forks_count=0,
            open_issues_count=0,
            topics=(),
            license_name=None,
        )

    def fetch_repos(self, org: str, *, max_repos: int, include_private: bool = True) -> list[GitHubRepo]:
        return [
            self._repo("masumi-agent-messenger"),
            self._repo("no-markers-here"),
            self._repo("archived-repo", archived=True),
            self._repo("sokosumi-cli"),
        ][:max_repos]

    def file_exists(self, full_name: str, path: str, *, ref: str) -> bool:
        return f"{full_name}/{path}" in self.markers


def test_discover_org_repos_joins_only_non_archived_marker_repos() -> None:
    joined = discover_org_repos(
        FakeAutoJoinClient(),
        "masumi-network",
        markers=DEFAULT_REPO_CONTENT_AUTOJOIN_MARKERS,
        max_repos=50,
    )
    assert joined == [
        "masumi-network/masumi-agent-messenger",
        "masumi-network/sokosumi-cli",
    ]


def test_resolved_repos_unions_autojoin_with_dedup() -> None:
    config = CitadelConfig(
        repo_content_sync_repos=("sokosumi-cli",),
        repo_content_sync_autojoin_enabled=True,
        repo_content_sync_autojoin_markers=("AGENTS.md",),
        repo_content_sync_autojoin_max_repos=50,
    )
    syncer = RepoContentSyncer(
        FakeCitadel(config),
        client=FakeAutoJoinClient(),
        state_path="unused",
    )
    resolved = syncer._resolved_repos()
    assert resolved == [
        "masumi-network/sokosumi-cli",
        "masumi-network/masumi-agent-messenger",
    ]


def test_resolved_repos_autojoin_disabled_skips_discovery() -> None:
    config = CitadelConfig(repo_content_sync_repos=("sokosumi-cli",))

    fetch_calls: list[int] = []

    class TrackingClient(FakeAutoJoinClient):
        def fetch_repos(self, org: str, *, max_repos: int, include_private: bool = True) -> list[GitHubRepo]:
            fetch_calls.append(1)
            return super().fetch_repos(org, max_repos=max_repos, include_private=include_private)

    syncer = RepoContentSyncer(FakeCitadel(config), client=TrackingClient(), state_path="unused")
    assert syncer._resolved_repos() == ["masumi-network/sokosumi-cli"]
    assert fetch_calls == []
