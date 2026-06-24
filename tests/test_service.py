from __future__ import annotations

import json
from typing import Any

import pytest

from kb.config import CitadelConfig
from kb.models import FeedbackRequest
from kb.service import Citadel


class FakeCognee:
    def __init__(self) -> None:
        self.remember_calls: list[dict[str, Any]] = []
        self.feedback_calls: list[dict[str, Any]] = []
        self.improve_calls: list[dict[str, Any]] = []
        self.cognify_calls: list[dict[str, Any]] = []
        self.nodes: list[Any] = []
        self.edges: list[Any] = []
        self._pending: list[Any] = []

    async def remember(self, data: Any, **kwargs: Any) -> dict[str, Any]:
        self.remember_calls.append({"data": data, **kwargs})
        # Cognee.add stores data, but it only enters the graph once cognify
        # runs — the modern remember path does not cognify inline.
        self._pending.append(data)
        return {"ok": True}

    async def recall(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"query": query, **kwargs}]

    async def add_feedback(self, **kwargs: Any) -> bool:
        self.feedback_calls.append(kwargs)
        return True

    async def improve(self, **kwargs: Any) -> dict[str, Any]:
        self.improve_calls.append(kwargs)
        return {"improved": True}

    async def cognify(self, **kwargs: Any) -> dict[str, Any]:
        self.cognify_calls.append(kwargs)
        # Cognify turns added-but-uncognified data into graph nodes.
        self.nodes.extend(self._pending)
        self._pending.clear()
        return {"cognified": True}

    async def graph_data(self) -> tuple[list[Any], list[Any]]:
        return list(self.nodes), list(self.edges)


class EmptyCognee(FakeCognee):
    async def recall(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return []


@pytest.mark.asyncio
async def test_ingest_applies_tags_and_dataset() -> None:
    fake = FakeCognee()
    kb = Citadel(CitadelConfig(default_dataset="notes", default_tags=("personal",)), cognee=fake)

    result = await kb.ingest("A useful note", tags=["AI"])

    assert result.accepted
    assert result.tags == ("personal", "ai")
    assert fake.remember_calls[0]["dataset_name"] == "notes"
    assert fake.remember_calls[0]["tags"] == ("personal", "ai")


@pytest.mark.asyncio
async def test_ingest_rejects_duplicate_in_process() -> None:
    fake = FakeCognee()
    kb = Citadel(CitadelConfig(), cognee=fake)

    first = await kb.ingest("same note")
    second = await kb.ingest("same note")

    assert first.accepted
    assert not second.accepted
    assert second.reason == "duplicate_in_process"
    assert len(fake.remember_calls) == 1


@pytest.mark.asyncio
async def test_search_uses_github_sync_session_for_github_dataset() -> None:
    fake = FakeCognee()
    kb = Citadel(
        CitadelConfig(
            github_sync_dataset="masumi-network",
            github_sync_session="masumi-github-daily",
        ),
        cognee=fake,
    )

    result = await kb.search("weekly updates", dataset="masumi-network")

    assert result[0]["session_id"] == "masumi-github-daily"


@pytest.mark.asyncio
async def test_search_falls_back_to_persisted_github_digest(tmp_path: Any) -> None:
    state_path = tmp_path / "github_state.json"
    state_path.write_text(
        json.dumps(
            {
                "org": "masumi-network",
                "last_checked_at": "2026-06-01T14:27:10Z",
                "last_digest_at": "2026-06-01T14:27:10Z",
                "last_digest": (
                    "# masumi-network GitHub daily update\n\n"
                    "New commits observed: 1\n\n"
                    "## Recent commits\n"
                    "- 2026-06-01T13:15:28Z: mrgrauel committed 434cec44e6af "
                    "to masumi-network/sokosumi: organization seat assignment."
                ),
            }
        ),
        encoding="utf-8",
    )
    kb = Citadel(
        CitadelConfig(
            github_sync_dataset="masumi-network",
            github_sync_session="masumi-github-daily",
            github_sync_state_path=str(state_path),
        ),
        cognee=EmptyCognee(),
    )

    result = await kb.search("what were the new updates all week in the org", dataset="masumi-network")

    assert result[0]["source"] == "github_sync_state"
    assert result[0]["metadata"]["org"] == "masumi-network"
    assert any("organization seat assignment" in item["content"] for item in result)


@pytest.mark.asyncio
async def test_cognify_dataset_reports_graph_growth() -> None:
    fake = FakeCognee()
    kb = Citadel(CitadelConfig(default_dataset="masumi-network"), cognee=fake)

    result = await kb.cognify_dataset()

    assert result["ok"]
    assert result["dataset"] == "masumi-network"
    assert result["verify"] is False
    assert fake.cognify_calls == [{"datasets": ["masumi-network"]}]
    assert result["graph_before"] == {"nodes": 0, "edges": 0}


@pytest.mark.asyncio
async def test_cognify_dataset_verify_ingests_marker_and_confirms_hit() -> None:
    class RecallingCognee(FakeCognee):
        async def recall(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"content": query}]

    fake = RecallingCognee()
    kb = Citadel(CitadelConfig(default_dataset="masumi-network"), cognee=fake)

    result = await kb.cognify_dataset(verify=True)

    assert result["verify"] is True
    marker = fake.remember_calls[0]["data"]
    assert marker.startswith("COGNIFY_TEST_MARKER_")
    assert result["verification"]["search_hit"] is True
    assert result["verification"]["graph_grew"] is True
    assert result["verification"]["ok"] is True
    # verify is a superset: recovery cognify + an explicit cognify of the marker
    # (remember does not cognify inline on the modern Cognee path).
    assert fake.cognify_calls == [
        {"datasets": ["masumi-network"]},
        {"datasets": ["masumi-network"]},
    ]


@pytest.mark.asyncio
async def test_feedback_can_auto_improve() -> None:
    fake = FakeCognee()
    kb = Citadel(CitadelConfig(auto_improve=True), cognee=fake)

    result = await kb.feedback(FeedbackRequest(qa_id="qa-1", score=1, text="useful"))

    assert result.recorded
    assert result.improved
    assert fake.feedback_calls[0]["qa_id"] == "qa-1"
    assert fake.improve_calls[0]["session_ids"] == ["personal-session"]
