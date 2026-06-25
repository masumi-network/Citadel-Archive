from __future__ import annotations

from dataclasses import asdict
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
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        super().__init__(api_key="test-key")
        self._issues = issues

    def fetch_issues(self, *, max_issues: int) -> list[LinearIssue]:
        parsed = [LinearIssue.from_node(item) for item in self._issues]
        return [item for item in parsed if item][:max_issues]


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
