from __future__ import annotations

from typing import Any

import pytest

from kb.config import CitadelConfig
from kb.github_sync import GitHubEvent, GitHubOrgSyncer, GitHubRepo
from kb.models import IngestResult


class FakeCitadel:
    def __init__(self, config: CitadelConfig) -> None:
        self.config = config
        self.ingest_calls: list[dict[str, Any]] = []
        self.improve_calls: list[dict[str, Any]] = []

    async def ingest(self, data: str, **kwargs: Any) -> IngestResult:
        self.ingest_calls.append({"data": data, **kwargs})
        return IngestResult(True, "accepted", kwargs["dataset"], tuple(kwargs["tags"]))

    async def improve(self, **kwargs: Any) -> dict[str, Any]:
        self.improve_calls.append(kwargs)
        return {"ok": True}


class FakeGitHubClient:
    def fetch_repos(self, org: str, *, max_repos: int) -> list[GitHubRepo]:
        return [
            GitHubRepo(
                name="agent",
                full_name=f"{org}/agent",
                html_url=f"https://github.com/{org}/agent",
                description="Agent runtime",
                language="TypeScript",
                pushed_at="2026-05-21T00:00:00Z",
                updated_at="2026-05-21T00:00:00Z",
                default_branch="main",
                visibility="public",
                archived=False,
                stargazers_count=7,
                forks_count=2,
                open_issues_count=1,
                topics=("masumi", "agent"),
                license_name="Apache License 2.0",
            )
        ][:max_repos]

    def fetch_events(self, org: str, *, max_events: int) -> list[GitHubEvent]:
        return [
            GitHubEvent(
                id="evt-1",
                type="PushEvent",
                repo=f"{org}/agent",
                actor="sarthib7",
                created_at="2026-05-21T00:00:00Z",
                summary="Pushed 1 commit to main: update docs",
            )
        ][:max_events]


@pytest.mark.asyncio
async def test_github_sync_ingests_daily_digest_and_persists_state(tmp_path: Any) -> None:
    config = CitadelConfig(
        github_sync_dataset="masumi-network",
        github_sync_session="masumi-github-daily",
        github_sync_state_path=str(tmp_path / "github_state.json"),
        github_sync_run_improve=True,
    )
    citadel = FakeCitadel(config)
    syncer = GitHubOrgSyncer(citadel, client=FakeGitHubClient(), org="masumi-network")

    result = await syncer.run()
    status = await syncer.status()

    assert result["repos_scanned"] == 1
    assert result["changed_count"] == 1
    assert result["event_count"] == 1
    assert result["ingested"] is True
    assert result["improved"] is True
    assert "masumi-network/agent" in citadel.ingest_calls[0]["data"]
    assert citadel.ingest_calls[0]["dataset"] == "masumi-network"
    assert citadel.improve_calls[0]["session_ids"] == ["masumi-github-daily"]
    assert status["tracked_repositories"] == 1
    assert status["seen_events"] == 1


@pytest.mark.asyncio
async def test_github_sync_can_skip_unchanged_ingest(tmp_path: Any) -> None:
    config = CitadelConfig(
        github_sync_state_path=str(tmp_path / "github_state.json"),
        github_sync_ingest_unchanged=False,
    )
    citadel = FakeCitadel(config)
    syncer = GitHubOrgSyncer(
        citadel,
        client=FakeGitHubClient(),
        org="masumi-network",
        ingest_unchanged=False,
    )

    await syncer.run()
    second = await syncer.run()

    assert second["changed_count"] == 0
    assert second["event_count"] == 0
    assert len(citadel.ingest_calls) == 1
