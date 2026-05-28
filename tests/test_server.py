from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from kb.access import AccessStore
from kb.config import CitadelConfig
from kb.mesh import MeshState
from kb.models import FeedbackResult, IngestResult
from kb.server import app


class FakeCitadel:
    config = CitadelConfig(
        tenant_id="test",
        default_dataset="notes",
        admin_key="test-admin",
        reader_keys=("test-reader",),
        writer_keys=("test-writer",),
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


class FakeGitHubSyncer:
    async def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "org": "masumi-network",
            "source_url": "https://github.com/orgs/masumi-network/repositories",
            "dataset": "masumi-network",
            "session_id": "masumi-github-daily",
            "last_checked_at": "2026-05-21T00:00:00Z",
            "last_digest_at": "2026-05-21T00:00:00Z",
            "tracked_repositories": 3,
            "seen_events": 4,
            "tracked_commit_repositories": 2,
            "include_commits": True,
            "max_commits_per_repo": 5,
            "run_improve": True,
            "ingest_unchanged": True,
        }

    async def run(self, *, force: bool = False) -> dict[str, Any]:
        return {
            "ok": True,
            "org": "masumi-network",
            "source_url": "https://github.com/orgs/masumi-network/repositories",
            "checked_at": "2026-05-21T00:00:00Z",
            "repos_scanned": 3,
            "changed_count": 1 if force else 0,
            "event_count": 2,
            "commit_count": 1,
            "changed_repositories": [
                {
                    "name": "agent",
                    "full_name": "masumi-network/agent",
                    "url": "https://github.com/masumi-network/agent",
                    "pushed_at": "2026-05-21T00:00:00Z",
                }
            ],
            "recent_commits": [
                {
                    "repo": "masumi-network/agent",
                    "sha": "abc123def456",
                    "message": "update docs",
                }
            ],
            "recent_events": [],
            "ingested": True,
            "improved": True,
        }


class FakeLearningAgent:
    async def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "agent": "citadel-learning-agent",
            "sources": {
                "github": await FakeGitHubSyncer().status(),
            },
            "capabilities": ["summarize_recent_commits"],
        }

    async def run(self, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        return {
            "ok": True,
            "agent": "citadel-learning-agent",
            "sources": {
                "github": {
                    **(await FakeGitHubSyncer().run(force=force)),
                    "dry_run": dry_run,
                }
            },
            "ingested": not dry_run,
            "improved": not dry_run,
            "dry_run": dry_run,
        }


def authed_client(access_key: str = "test-admin") -> TestClient:
    app.state.citadel = FakeCitadel()
    app.state.mesh = MeshState()
    app.state.github_syncer = FakeGitHubSyncer()
    app.state.learning_agent = FakeLearningAgent()
    client = TestClient(app, base_url="https://testserver")
    response = client.post("/admin/session", json={"access_key": access_key})
    assert response.status_code == 200
    return client


def test_healthz() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "citadel"}


def test_api_uses_configured_citadel_service() -> None:
    client = authed_client()

    ready = client.get("/readyz")
    ingest = client.post("/ingest", json={"data": "A useful note", "tags": ["research"]})
    search = client.post("/search", json={"query": "useful", "top_k": 3})
    mesh = client.get("/api/mesh")
    indexes = client.get("/api/indexes")
    sync_status = client.get("/api/github-sync")
    sync_run = client.post("/api/github-sync/run", json={"force": True})
    learning_status = client.get("/api/learning-agent")
    learning_run = client.post("/api/learning-agent/run", json={"force": True})
    feedback = client.post("/feedback", json={"qa_id": "qa-1", "score": 1, "text": "useful"})
    upgrade = client.post("/api/self-upgrade", json={})
    updated_mesh = client.get("/api/mesh")

    assert ready.status_code == 200
    assert ready.json()["default_dataset"] == "notes"
    assert ingest.status_code == 200
    assert ingest.json()["tags"] == ["research"]
    assert search.status_code == 200
    assert search.json()["results"][0]["top_k"] == 3
    assert mesh.status_code == 200
    assert mesh.json()["stats"]["documents"] == 1
    assert indexes.status_code == 200
    assert len(indexes.json()["indexes"]) == 4
    assert sync_status.status_code == 200
    assert sync_status.json()["tracked_repositories"] == 3
    assert sync_run.status_code == 200
    assert sync_run.json()["changed_count"] == 1
    assert learning_status.status_code == 200
    assert learning_status.json()["agent"] == "citadel-learning-agent"
    assert learning_run.status_code == 200
    assert learning_run.json()["sources"]["github"]["commit_count"] == 1
    assert feedback.status_code == 200
    assert feedback.json() == {"recorded": True, "improved": True}
    assert updated_mesh.status_code == 200
    assert updated_mesh.json()["stats"]["feedback"] == 1
    assert upgrade.status_code == 200


def test_reader_access_can_view_and_search_but_not_mutate() -> None:
    client = authed_client("test-reader")

    session = client.get("/api/session")
    mesh = client.get("/api/mesh")
    search = client.post("/search", json={"query": "useful"})
    ingest = client.post("/ingest", json={"data": "A useful note"})
    sync_run = client.post("/api/github-sync/run", json={"force": True})

    assert session.status_code == 200
    assert session.json()["role"] == "reader"
    assert session.json()["capabilities"] == {"read": True, "write": False, "admin": False}
    assert mesh.status_code == 200
    assert search.status_code == 200
    assert ingest.status_code == 403
    assert sync_run.status_code == 403


def test_writer_access_can_ingest_and_feedback_but_not_admin_actions() -> None:
    client = authed_client("test-writer")

    session = client.get("/api/session")
    ingest = client.post("/ingest", json={"data": "A useful note"})
    feedback = client.post("/feedback", json={"qa_id": "qa-1", "score": 1})
    upgrade = client.post("/api/self-upgrade", json={})

    assert session.status_code == 200
    assert session.json()["role"] == "writer"
    assert session.json()["capabilities"] == {"read": True, "write": True, "admin": False}
    assert ingest.status_code == 200
    assert feedback.status_code == 200
    assert upgrade.status_code == 403


def test_ui_requires_admin_key() -> None:
    app.state.citadel = FakeCitadel()
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_ui_shell_is_served_after_login() -> None:
    client = authed_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "Citadel Archive" in response.text
    assert "Citadel Vault" in response.text
    assert "Source Sync" in response.text


def test_admin_can_create_and_use_scoped_access_token(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()

    created = client.post(
        "/api/access/tokens",
        json={"name": "research-agent", "role": "reader", "kind": "service_account"},
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["token"].startswith("ctdl_")
    assert "token_hash" not in payload["api_token"]

    access = client.get("/api/access")
    assert access.status_code == 200
    assert access.json()["principals"][0]["name"] == "research-agent"
    assert access.json()["tokens"][0]["prefix"] == payload["token"][:12]
    assert "token_hash" not in access.text

    token_client = authed_client(payload["token"])
    session = token_client.get("/api/session")
    search = token_client.post("/search", json={"query": "useful"})
    ingest = token_client.post("/ingest", json={"data": "A useful note"})
    admin_access = token_client.get("/api/access")

    assert session.status_code == 200
    assert session.json()["role"] == "reader"
    assert session.json()["actor"]["name"] == "research-agent"
    assert search.status_code == 200
    assert ingest.status_code == 403
    assert admin_access.status_code == 403


def test_bearer_tokens_can_access_api_without_cookie(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={"name": "writer-agent", "role": "writer", "kind": "service_account"},
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    session = api_client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
    ingest = api_client.post(
        "/ingest",
        json={"data": "A useful note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    admin_run = api_client.post(
        "/api/learning-agent/run",
        json={"force": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert session.status_code == 200
    assert session.json()["role"] == "writer"
    assert ingest.status_code == 200
    assert admin_run.status_code == 403


def test_access_tokens_are_hashed_and_revocable(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={"name": "writer", "role": "writer", "kind": "user"},
    )
    token = created.json()["token"]
    token_id = created.json()["api_token"]["id"]

    raw_store = (tmp_path / "access.json").read_text()
    assert token not in raw_store
    assert "token_hash" in raw_store

    revoke = client.post(f"/api/access/tokens/{token_id}/revoke", json={})
    assert revoke.status_code == 200

    rejected = TestClient(app, base_url="https://testserver").post(
        "/admin/session",
        json={"access_key": token},
    )
    assert rejected.status_code == 401
