from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from kb.config import CitadelConfig
from kb.models import FeedbackResult, IngestResult
from kb.server import app


class FakeCitadel:
    config = CitadelConfig(
        tenant_id="test",
        default_dataset="notes",
        auto_improve=True,
        build_global_context_index=True,
    )

    async def ingest(self, data: str, **kwargs: Any) -> IngestResult:
        return IngestResult(True, "accepted", kwargs["dataset"] or "notes", tuple(kwargs["tags"]))

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"query": query, "dataset": kwargs["dataset"], "top_k": kwargs["top_k"]}]

    async def feedback(self, request: Any) -> FeedbackResult:
        return FeedbackResult(recorded=bool(request.qa_id), improved=True)

    async def improve(self, **kwargs: Any) -> dict[str, Any]:
        return {"dataset": kwargs["dataset"], "session_ids": kwargs["session_ids"]}


def test_healthz() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "citadel"}


def test_api_uses_configured_citadel_service() -> None:
    app.state.citadel = FakeCitadel()
    client = TestClient(app)

    ready = client.get("/readyz")
    ingest = client.post("/ingest", json={"data": "A useful note", "tags": ["research"]})
    search = client.post("/search", json={"query": "useful", "top_k": 3})

    assert ready.status_code == 200
    assert ready.json()["default_dataset"] == "notes"
    assert ingest.status_code == 200
    assert ingest.json()["tags"] == ["research"]
    assert search.status_code == 200
    assert search.json()["results"][0]["top_k"] == 3
