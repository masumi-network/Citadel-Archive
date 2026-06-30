from __future__ import annotations

from typing import Any

import pytest

from kb.access import AccessStore, seat_dataset
from kb.config import CitadelConfig
from kb.linear_sync import (
    LinearClient,
    LinearIssue,
    LinearSyncer,
    format_issue_note,
    resolve_mirror_dataset,
    seat_email_index,
)
from kb.service import Citadel


class FakeLinearClient(LinearClient):
    def __init__(
        self, issues: list[dict[str, Any]], users: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(api_key="test-key")
        self._issues = issues
        self._users = users or []

    def fetch_issues(self, *, max_issues: int) -> list[LinearIssue]:
        parsed = [LinearIssue.from_node(item) for item in self._issues]
        return [item for item in parsed if item][:max_issues]

    def fetch_users(self, *, max_users: int = 250) -> list[dict[str, Any]]:
        return self._users


@pytest.fixture
def sample_issues() -> list[dict[str, Any]]:
    return [
        {
            "id": "issue-1",
            "identifier": "ENG-1",
            "title": "Ship Linear sync",
            "description": "Implement workspace sync.",
            "url": "https://linear.app/acme/issue/ENG-1",
            "priority": 2,
            "updatedAt": "2026-06-25T10:00:00Z",
            "state": {"name": "In Progress", "type": "started"},
            "team": {"key": "ENG", "name": "Engineering"},
            "assignee": {
                "id": "user-john",
                "name": "John Doe",
                "email": "john@example.com",
            },
        },
        {
            "id": "issue-2",
            "identifier": "ENG-2",
            "title": "Org-wide roadmap",
            "description": "Central only.",
            "url": "https://linear.app/acme/issue/ENG-2",
            "priority": 1,
            "updatedAt": "2026-06-25T09:00:00Z",
            "state": {"name": "Backlog", "type": "backlog"},
            "team": {"key": "ENG", "name": "Engineering"},
            "assignee": None,
        },
    ]


def test_format_issue_note(sample_issues: list[dict[str, Any]]) -> None:
    issue = LinearIssue.from_node(sample_issues[0])
    assert issue is not None
    note = format_issue_note(issue)
    assert "ENG-1" in note
    assert "John Doe" in note


def test_seat_email_index(tmp_path: Any) -> None:
    store = AccessStore(str(tmp_path / "access.json"))
    store.create_seat(name="John Doe", slug="john", email="john@example.com", issue_token=False)
    mapping = seat_email_index(store)
    assert mapping["john@example.com"] == seat_dataset("john")


def test_resolve_mirror_dataset(sample_issues: list[dict[str, Any]]) -> None:
    issue = LinearIssue.from_node(sample_issues[0])
    assert issue is not None
    dataset = resolve_mirror_dataset(
        issue,
        {"john@example.com": seat_dataset("john")},
    )
    assert dataset == seat_dataset("john")


@pytest.mark.asyncio
async def test_linear_sync_ingests_central_and_mirror(
    tmp_path: Any,
    sample_issues: list[dict[str, Any]],
    monkeypatch: Any,
) -> None:
    config = CitadelConfig(
        linear_api_key="lin_test",
        linear_sync_state_path=str(tmp_path / "linear_state.json"),
        access_store_path=str(tmp_path / "access.json"),
    )
    citadel = Citadel(config)
    store = AccessStore(config.access_store_path)
    store.create_seat(name="John Doe", slug="john", email="john@example.com", issue_token=False)

    ingests: list[dict[str, Any]] = []

    async def fake_learn(
        self: Any,
        data: str,
        *,
        dataset: str | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        operation: str = "ingest",
        run_improve: bool = False,
        detect_conflicts: bool = True,
        tier: str = "full",
    ) -> Any:
        ingests.append(
            {
                "dataset": dataset,
                "tags": tags or [],
                "operation": operation,
                "tier": tier,
                "data": data[:80],
            }
        )

        class FakeResult:
            accepted = True

        class Outcome:
            ingest = FakeResult()

        return Outcome()

    monkeypatch.setattr("kb.linear_sync.LearningProcess.learn", fake_learn)

    syncer = LinearSyncer(
        citadel,
        client=FakeLinearClient(sample_issues),
        access_store=store,
    )
    result = await syncer.run(force=True)
    assert result["ok"] is True
    assert result["issue_count"] == 2
    assert result["mirrored_count"] == 1
    assert any(item["dataset"] == "masumi-network" for item in ingests)
    assert any(item["dataset"] == seat_dataset("john") for item in ingests)
    assert syncer.issues_for_scope(scope="my", seat_dataset_name=seat_dataset("john"))
    assert len(syncer.issues_for_scope(scope="org", seat_dataset_name=None)) == 2


@pytest.mark.asyncio
async def test_linear_sync_writes_each_issue_to_central(
    tmp_path: Any,
    sample_issues: list[dict[str, Any]],
    monkeypatch: Any,
) -> None:
    # #52: each issue's full text (not just the digest of titles) must reach
    # Central so linear_search returns real issues org-wide.
    config = CitadelConfig(
        linear_api_key="lin_test",
        linear_sync_state_path=str(tmp_path / "s.json"),
        access_store_path=str(tmp_path / "a.json"),
    )
    citadel = Citadel(config)
    ingests: list[dict[str, Any]] = []

    async def fake_learn(self: Any, data: str, *, dataset: str | None = None, tags: list[str] | None = None, **_: Any) -> Any:
        ingests.append({"dataset": dataset, "tags": tags or [], "data": data})

        class Outcome:
            class ingest:
                accepted = True

        return Outcome()

    monkeypatch.setattr("kb.linear_sync.LearningProcess.learn", fake_learn)
    syncer = LinearSyncer(citadel, client=FakeLinearClient(sample_issues))

    result = await syncer.run(force=True)
    assert result["ok"] is True

    central_issue_writes = [
        i for i in ingests if i["dataset"] == "masumi-network" and "linear-issue" in i["tags"]
    ]
    id_tags = {tag for i in central_issue_writes for tag in i["tags"] if tag.startswith("linear:")}
    assert "linear:ENG-1" in id_tags
    assert "linear:ENG-2" in id_tags
    # The full description reaches Central, not just the title.
    assert any("Implement workspace sync." in i["data"] for i in central_issue_writes)


@pytest.mark.asyncio
async def test_linear_sync_auto_maps_assignee_by_member_email(
    tmp_path: Any, monkeypatch: Any
) -> None:
    # #46: when the issue payload omits assignee.email, resolve the mirror by
    # matching the assignee id against the Linear members list (id->email) vs seats.
    config = CitadelConfig(
        linear_api_key="lin_test",
        linear_sync_state_path=str(tmp_path / "s.json"),
        access_store_path=str(tmp_path / "a.json"),
    )
    citadel = Citadel(config)
    store = AccessStore(config.access_store_path)
    store.create_seat(name="John Doe", slug="john", email="john@example.com", issue_token=False)

    issues = [
        {
            "id": "issue-1",
            "identifier": "ENG-1",
            "title": "x",
            "description": "d",
            "url": "u",
            "priority": 1,
            "updatedAt": "2026-06-25T10:00:00Z",
            "state": {"name": "In Progress", "type": "started"},
            "team": {"key": "ENG", "name": "Eng"},
            "assignee": {"id": "linear-user-john", "name": "John", "email": None},  # no email
        }
    ]
    members = [{"id": "linear-user-john", "name": "John Doe", "email": "john@example.com", "active": True}]

    async def fake_learn(self: Any, data: str, **_: Any) -> Any:
        class Outcome:
            class ingest:
                accepted = True

        return Outcome()

    monkeypatch.setattr("kb.linear_sync.LearningProcess.learn", fake_learn)
    syncer = LinearSyncer(
        citadel, client=FakeLinearClient(issues, users=members), access_store=store
    )

    result = await syncer.run(force=True)
    assert result["ok"] is True
    assert result["auto_mapped_assignees"] == 1
    assert result["mirrored_count"] == 1
    assert seat_dataset("john") in result["mirrors"]


@pytest.mark.asyncio
async def test_linear_sync_surfaces_api_error(tmp_path: Any) -> None:
    # #46: an API failure returns ok:False with a reason and is persisted so
    # status()/list_sources stop showing a stale green last_synced_at.
    from kb.linear_sync import LinearAPIError

    config = CitadelConfig(
        linear_api_key="lin_test",
        linear_sync_state_path=str(tmp_path / "s.json"),
    )
    citadel = Citadel(config)

    class BrokenClient(LinearClient):
        def __init__(self) -> None:
            super().__init__(api_key="x")

        def fetch_issues(self, *, max_issues: int) -> list[LinearIssue]:
            raise LinearAPIError("401 Unauthorized")

    syncer = LinearSyncer(citadel, client=BrokenClient())

    result = await syncer.run(force=True)
    assert result["ok"] is False
    assert result["reason"] == "linear_api_error"
    assert "401" in result["error"]

    status = await syncer.status()
    assert status["last_error"] == "401 Unauthorized"
    assert status["last_attempt_at"]


def test_linear_sync_status_disabled(tmp_path: Any) -> None:
    config = CitadelConfig(
        linear_sync_state_path=str(tmp_path / "linear_state.json"),
    )
    syncer = LinearSyncer(Citadel(config))

    async def _status() -> dict[str, Any]:
        return await syncer.status()

    import asyncio

    status = asyncio.run(_status())
    assert status["enabled"] is False
