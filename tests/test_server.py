from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from fastapi.testclient import TestClient

from kb.access import AccessStore
from kb.config import CitadelConfig
from kb.conflicts import KnowledgeConflictStore
from kb.knowledge_mesh import KnowledgeMesh
from kb.mesh import MeshState
from kb.models import FeedbackResult, IngestResult
from kb.obsidian_sync import ObsidianSyncStore
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
                "repo_content": {
                    "ok": True,
                    "source_type": "github_repo_content",
                    "enabled": True,
                    "tracked_files": 8,
                },
            },
            "capabilities": ["summarize_recent_commits", "sync_repo_content"],
        }

    async def run(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
        post_to_chat: bool = False,
        include_digest_preview: bool = True,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "agent": "citadel-learning-agent",
            "sources": {
                "github": {
                    **(await FakeGitHubSyncer().run(force=force)),
                    "dry_run": dry_run,
                },
                "repo_content": {
                    "ok": True,
                    "enabled": True,
                    "files_ingested": 0 if dry_run else 4,
                    "files_skipped": 2,
                    "improved": not dry_run,
                    "dry_run": dry_run,
                },
            },
            "ingested": not dry_run,
            "improved": not dry_run,
            "dry_run": dry_run,
            "organization_digest": {
                "enabled": True,
                "meaningful": True,
                **({"preview": "Digest preview"} if include_digest_preview else {}),
            },
            "notifications": {
                "google_chat": {
                    "enabled": True,
                    "sent": post_to_chat,
                    "reason": None if post_to_chat else "preview_only",
                }
            },
        }

    async def test_google_chat_delivery(self, message: str | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": True,
            "sent": True,
            "gateway": "google_chat",
            "status_category": "success",
            "message_name": "spaces/AAA/messages/BBB",
            "thread_name": "spaces/AAA/threads/T",
        }

    async def test_gateway_delivery(
        self,
        gateway_name: str,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": True,
            "sent": True,
            "gateway": gateway_name,
            "status_category": "success",
            "message_name": f"{gateway_name}/messages/BBB",
        }


def authed_client(access_key: str = "test-admin") -> TestClient:
    app.state.citadel = FakeCitadel()
    app.state.mesh = MeshState()
    app.state.github_syncer = FakeGitHubSyncer()
    app.state.learning_agent = FakeLearningAgent()
    # Keep knowledge-conflict state out of the repo-local .citadel directory.
    app.state.conflict_store = KnowledgeConflictStore(
        Path(tempfile.mkdtemp()) / "conflicts.json"
    )
    client = TestClient(app, base_url="https://testserver")
    response = client.post("/admin/session", json={"access_key": access_key})
    assert response.status_code == 200
    return client


def test_healthz() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "citadel"}


def test_security_headers_are_applied_to_http_responses() -> None:
    client = TestClient(app, base_url="https://testserver")

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )


def test_security_headers_do_not_force_hsts_on_plain_http() -> None:
    client = TestClient(app, base_url="http://testserver")

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in response.headers


def test_private_responses_are_no_store() -> None:
    client = authed_client()

    session = client.get("/api/session")
    search = client.post("/search", json={"query": "useful"})

    assert session.status_code == 200
    assert search.status_code == 200
    assert session.headers["cache-control"] == "no-store"
    assert session.headers["pragma"] == "no-cache"
    assert search.headers["cache-control"] == "no-store"
    assert search.headers["pragma"] == "no-cache"


def test_public_health_response_is_not_cacheable() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_mcp_legacy_path_redirects_relative() -> None:
    client = TestClient(app, base_url="https://testserver")

    response = client.post("/mcp", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp/"
    assert not response.headers["location"].startswith("http://")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_login_page_uses_static_script_for_csp() -> None:
    client = TestClient(app, base_url="https://testserver")

    response = client.get("/login")

    assert response.status_code == 200
    assert '<script src="/static/login.js" type="module"></script>' in response.text
    assert "<script>\n" not in response.text


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
    search_hit = search.json()["results"][0]
    assert search_hit["top_k"] == 3
    assert search_hit["id"].startswith("chunk:")
    assert search_hit["_citadel"]["rank"] == 1
    assert search_hit["_citadel"]["dataset"] == "notes"
    assert search_hit["_citadel"]["result_id"] == search_hit["id"]
    assert len(search_hit["_citadel"]["content_sha256"]) == 64
    assert search_hit["_citadel"]["provenance"] == {}
    assert search_hit["_citadel"]["retrieval"] == {
        "untrusted_context": True,
        "citation_required": True,
        "document_drilldown_available": False,
    }
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


def test_knowledge_events_api_returns_resumable_timeline() -> None:
    client = authed_client()

    ingest = client.post("/ingest", json={"data": "A useful note", "tags": ["research"]})
    search = client.post("/search", json={"query": "useful", "top_k": 3})
    timeline = client.get("/api/knowledge/events?limit=10")
    resumed = client.get("/api/knowledge/events?after_id=1&limit=1")
    chunked = client.get("/api/knowledge/events?kind=chunk_indexed")
    typed = client.get("/api/knowledge/events?type=search")
    invalid_limit = client.get("/api/knowledge/events?limit=0")
    invalid_after = client.get("/api/knowledge/events?after_id=-1")
    unauthenticated = TestClient(app, base_url="https://testserver").get(
        "/api/knowledge/events"
    )

    assert ingest.status_code == 200
    assert search.status_code == 200
    assert timeline.status_code == 200
    timeline_body = timeline.json()
    assert timeline_body["ok"] is True
    assert timeline_body["latest_event_id"] == timeline_body["stats"]["latest_event_id"]
    assert timeline_body["stats"]["indexed_chunks"] == 1
    assert timeline_body["events"][0]["type"] == "search"
    assert timeline_body["events"][0]["timeline"] == {
        "kind": "retrieval_served",
        "status": "searched",
        "dataset": "notes",
        "source": "search",
        "metrics": {"results": 1},
    }
    assert resumed.status_code == 200
    assert [event["id"] for event in resumed.json()["events"]] == [2]
    assert chunked.status_code == 200
    assert [event["id"] for event in chunked.json()["events"]] == [1]
    assert typed.status_code == 200
    assert [event["type"] for event in typed.json()["events"]] == ["search"]
    assert invalid_limit.status_code == 422
    assert invalid_after.status_code == 422
    assert unauthenticated.status_code == 401


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
    assert "Run learning agent" in response.text
    assert "Send Google Chat test" in response.text
    assert "Obsidian Vaults" in response.text
    assert "mcp-remote" in response.text
    assert "Audit event filter" in response.text


def test_admin_can_create_and_use_role_based_access_token(tmp_path: Any) -> None:
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


def test_token_default_dataset_is_used_when_search_omits_dataset(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={
            "name": "personal-reader",
            "role": "reader",
            "kind": "service_account",
            "default_dataset": "personal",
        },
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    session = api_client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
    search = api_client.post(
        "/search",
        json={"query": "notes"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert session.status_code == 200
    assert session.json()["default_dataset"] == "personal"
    assert session.json()["default_session"] is None
    assert session.json()["allowed_datasets"] is None
    assert search.status_code == 200
    assert search.json()["dataset"] == "personal"
    assert search.json()["results"][0]["dataset"] == "personal"


def test_token_allowed_datasets_rejects_other_dataset(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={
            "name": "scoped-writer",
            "role": "writer",
            "kind": "service_account",
            "default_dataset": "personal",
            "allowed_datasets": ["personal"],
        },
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    allowed = api_client.post(
        "/ingest",
        json={"data": "Scoped note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    denied = api_client.post(
        "/search",
        json={"query": "notes", "dataset": "masumi-network"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert allowed.status_code == 200
    assert allowed.json()["dataset"] == "personal"
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Dataset not allowed: masumi-network."


def test_tokens_without_memory_fields_use_config_defaults(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={"name": "legacy-reader", "role": "reader", "kind": "service_account"},
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    session = api_client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
    search = api_client.post(
        "/search",
        json={"query": "notes"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert session.status_code == 200
    assert session.json()["default_dataset"] == "notes"
    assert search.status_code == 200
    assert search.json()["dataset"] == "notes"


def test_admin_token_bypasses_allowed_datasets(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={
            "name": "admin-scoped",
            "role": "admin",
            "kind": "service_account",
            "allowed_datasets": ["personal"],
        },
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    search = api_client.post(
        "/search",
        json={"query": "notes", "dataset": "masumi-network"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert search.status_code == 200
    assert search.json()["dataset"] == "masumi-network"


def test_google_chat_test_delivery_is_admin_only_and_redacted(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    reader = authed_client("test-reader")

    denied = reader.post("/api/learning-agent/google-chat/test", json={})
    response = admin.post(
        "/api/learning-agent/google-chat/test",
        json={"message": "custom rollout smoke test"},
    )

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.json()["sent"] is True
    events = app.state.access_store.snapshot()["audit_events"]
    event = events[-1]
    serialized = str(event)
    assert event["action"] == "learning_agent.google_chat_test"
    assert event["success"] is True
    assert event["detail"]["status_category"] == "success"
    assert event["detail"]["message_name"] == "spaces/AAA/messages/BBB"
    assert "custom rollout smoke test" not in serialized


def test_gateway_test_delivery_is_admin_only_and_redacted(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    reader = authed_client("test-reader")

    denied = reader.post("/api/learning-agent/gateways/google_chat/test", json={})
    response = admin.post(
        "/api/learning-agent/gateways/google_chat/test",
        json={"message": "gateway rollout smoke test"},
    )

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.json()["sent"] is True
    events = app.state.access_store.snapshot()["audit_events"]
    event = events[-1]
    serialized = str(event)
    assert event["action"] == "learning_agent.gateway_test"
    assert event["success"] is True
    assert event["detail"]["gateway"] == "google_chat"
    assert event["detail"]["status_category"] == "success"
    assert "gateway rollout smoke test" not in serialized


def test_custom_token_scopes_are_enforced(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={
            "name": "ingest-only-agent",
            "role": "writer",
            "kind": "service_account",
            "scopes": ["kb:ingest"],
        },
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    login = api_client.post("/admin/session", json={"access_key": token})
    ingest = api_client.post(
        "/ingest",
        json={"data": "A scoped note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    feedback = api_client.post(
        "/feedback",
        json={"qa_id": "qa-1", "score": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    search = api_client.post(
        "/search",
        json={"query": "note"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert created.status_code == 200
    assert created.json()["api_token"]["scopes"] == ["kb:ingest"]
    assert login.status_code == 200
    assert login.json()["capabilities"] == {"read": False, "write": True, "admin": False}
    assert ingest.status_code == 200
    assert feedback.status_code == 403
    assert feedback.json()["detail"] == "Scope required: kb:feedback."
    assert search.status_code == 403
    assert search.json()["detail"] == "Scope required: kb:search."


def test_custom_token_scopes_cannot_exceed_role(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()

    reader_with_write_scope = client.post(
        "/api/access/tokens",
        json={
            "name": "bad-reader",
            "role": "reader",
            "kind": "service_account",
            "scopes": ["kb:read", "kb:ingest"],
        },
    )
    writer_with_admin_scope = client.post(
        "/api/access/tokens",
        json={
            "name": "bad-writer",
            "role": "writer",
            "kind": "service_account",
            "scopes": ["kb:read", "sources:sync"],
        },
    )

    assert reader_with_write_scope.status_code == 422
    assert "Scopes exceed reader role: kb:ingest" in reader_with_write_scope.json()["detail"]
    assert writer_with_admin_scope.status_code == 422
    assert "Scopes exceed writer role: sources:sync" in writer_with_admin_scope.json()["detail"]


def test_admin_token_scopes_are_enforced_for_management_surfaces(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()
    created = client.post(
        "/api/access/tokens",
        json={
            "name": "access-manager",
            "role": "admin",
            "kind": "service_account",
            "scopes": ["access:manage"],
        },
    )
    token = created.json()["token"]
    api_client = TestClient(app, base_url="https://testserver")

    access = api_client.get("/api/access", headers={"Authorization": f"Bearer {token}"})
    audit = api_client.get("/api/audit", headers={"Authorization": f"Bearer {token}"})
    learning_run = api_client.post(
        "/api/learning-agent/run",
        json={"dry_run": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert created.status_code == 200
    assert access.status_code == 200
    assert audit.status_code == 403
    assert audit.json()["detail"] == "Scope required: audit:read."
    assert learning_run.status_code == 403
    assert learning_run.json()["detail"] == "Scope required: sources:sync."


def test_mcp_search_calls_are_attributable_and_redacted(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client("test-reader")

    response = client.post(
        "/search",
        json={
            "query": "sensitive roadmap question",
            "dataset": "masumi-network",
            "top_k": 2,
        },
        headers={"X-Citadel-MCP-Tool": "citadel_search"},
    )

    assert response.status_code == 200
    events = app.state.access_store.snapshot()["audit_events"]
    event = events[-1]
    serialized = str(event)

    assert event["action"] == "mcp.citadel_search"
    assert event["actor_id"] == "bootstrap:reader"
    assert event["role"] == "reader"
    assert event["success"] is True
    assert event["dataset"] == "masumi-network"
    assert event["detail"]["surface"] == "mcp"
    assert event["detail"]["tool"] == "citadel_search"
    assert event["detail"]["required_role"] == "reader"
    assert event["detail"]["required_scope"] == "kb:search"
    assert event["detail"]["result_count"] == 1
    assert event["detail"]["top_k"] == 2
    assert event["detail"]["query_length"] == len("sensitive roadmap question")
    assert "query_sha256" in event["detail"]
    assert "sensitive roadmap question" not in serialized


def test_failed_mcp_auth_is_audited_without_actor(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    app.state.citadel = FakeCitadel()
    app.state.mesh = MeshState()
    client = TestClient(app, base_url="https://testserver")

    response = client.post(
        "/search",
        json={"query": "anything"},
        headers={"X-Citadel-MCP-Tool": "citadel_search"},
    )

    assert response.status_code == 401
    events = app.state.access_store.snapshot()["audit_events"]
    event = events[-1]

    assert event["action"] == "mcp.citadel_search"
    assert event["actor_id"] is None
    assert event["role"] is None
    assert event["success"] is False
    assert event["dataset"] is None
    assert event["detail"]["surface"] == "mcp"
    assert event["detail"]["tool"] == "citadel_search"
    assert event["detail"]["path"] == "/search"
    assert event["detail"]["status_code"] == 401


def test_audit_api_filters_summarizes_and_limits_events(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    created = admin.post(
        "/api/access/tokens",
        json={"name": "reader-agent", "role": "reader", "kind": "service_account"},
    )
    reader = authed_client("test-reader")
    search = reader.post(
        "/search",
        json={"query": "sensitive project question", "dataset": "masumi-network"},
        headers={"X-Citadel-MCP-Tool": "citadel_search"},
    )
    session = reader.get("/api/session", headers={"X-Citadel-MCP-Tool": "citadel_session"})
    unauthenticated = TestClient(app, base_url="https://testserver")
    failed = unauthenticated.post(
        "/search",
        json={"query": "do not log this"},
        headers={"X-Citadel-MCP-Tool": "citadel_search"},
    )

    all_events = admin.get("/api/audit")
    mcp_events = admin.get("/api/audit?view=mcp&limit=1")
    access_events = admin.get("/api/audit?view=access")
    failure_events = admin.get("/api/audit?view=failures")
    invalid_view = admin.get("/api/audit?view=unknown")
    invalid_limit = admin.get("/api/audit?limit=0")

    assert created.status_code == 200
    assert search.status_code == 200
    assert session.status_code == 200
    assert failed.status_code == 401

    assert all_events.status_code == 200
    assert all_events.json()["view"] == "all"
    assert all_events.json()["summary"] == {
        "total_events": 4,
        "returned_events": 4,
        "mcp_events": 3,
        "access_events": 1,
        "failure_events": 1,
        "mcp_failures": 1,
        "mcp_actors": 1,
    }

    assert mcp_events.status_code == 200
    assert mcp_events.json()["view"] == "mcp"
    assert mcp_events.json()["summary"]["returned_events"] == 1
    assert len(mcp_events.json()["audit_events"]) == 1
    assert mcp_events.json()["audit_events"][0]["action"] == "mcp.citadel_search"
    assert mcp_events.json()["audit_events"][0]["success"] is False
    assert "do not log this" not in str(mcp_events.json())

    assert access_events.status_code == 200
    assert [event["action"] for event in access_events.json()["audit_events"]] == [
        "access.token.create"
    ]

    assert failure_events.status_code == 200
    assert [event["id"] for event in failure_events.json()["audit_events"]] == [
        mcp_events.json()["audit_events"][0]["id"]
    ]
    assert invalid_view.status_code == 422
    assert invalid_limit.status_code == 422


def test_backup_mirror_status_and_run_are_admin_scoped(tmp_path: Any) -> None:
    config = CitadelConfig(
        admin_key="test-admin",
        reader_keys=("test-reader",),
        writer_keys=("test-writer",),
        access_store_path=str(tmp_path / "access.json"),
        obsidian_sync_state_path=str(tmp_path / "obsidian.json"),
        github_sync_state_path=str(tmp_path / "github.json"),
        backup_mirror_root_path=str(tmp_path / "mirror"),
        backup_mirror_enabled=False,
    )
    (tmp_path / "github.json").write_text(
        '{"last_checked_at":"2026-06-03T00:00:00Z"}',
        encoding="utf-8",
    )
    citadel = FakeCitadel()
    citadel.config = config
    app.state.citadel = citadel
    app.state.mesh = MeshState()
    app.state.access_store = AccessStore(config.access_store_path)
    admin = TestClient(app, base_url="https://testserver")
    reader = TestClient(app, base_url="https://testserver")
    assert admin.post("/admin/session", json={"access_key": "test-admin"}).status_code == 200
    assert reader.post("/admin/session", json={"access_key": "test-reader"}).status_code == 200

    status = admin.get("/api/backup-mirror")
    dry_run = admin.post("/api/backup-mirror/run", json={"dry_run": True})
    disabled_run = admin.post("/api/backup-mirror/run", json={"dry_run": False})
    reader_status = reader.get("/api/backup-mirror")

    assert status.status_code == 200
    assert status.json()["enabled"] is False
    assert status.json()["summary"]["available_files"] == 1
    assert dry_run.status_code == 200
    assert dry_run.json()["written"] is False
    assert dry_run.json()["manifest"]["summary"]["available_files"] == 1
    assert disabled_run.status_code == 409
    assert reader_status.status_code == 403
    events = app.state.access_store.snapshot()["audit_events"]
    assert [event["action"] for event in events] == ["backup_mirror.run", "backup_mirror.run"]
    assert events[0]["success"] is True
    assert events[1]["success"] is False


def test_backup_mirror_push_errors_are_audited(tmp_path: Any) -> None:
    config = CitadelConfig(
        admin_key="test-admin",
        access_store_path=str(tmp_path / "access.json"),
        obsidian_sync_state_path=str(tmp_path / "obsidian.json"),
        github_sync_state_path=str(tmp_path / "github.json"),
        backup_mirror_root_path=str(tmp_path / "mirror"),
        backup_mirror_enabled=True,
        backup_mirror_push_enabled=True,
        backup_mirror_token=None,
    )
    citadel = FakeCitadel()
    citadel.config = config
    app.state.citadel = citadel
    app.state.mesh = MeshState()
    app.state.access_store = AccessStore(config.access_store_path)
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/admin/session", json={"access_key": "test-admin"}).status_code == 200

    response = client.post("/api/backup-mirror/run", json={"dry_run": False})

    assert response.status_code == 502
    assert response.json()["detail"] == "Vault Backup Mirror push token is not configured."
    events = app.state.access_store.snapshot()["audit_events"]
    assert events[-1]["action"] == "backup_mirror.run"
    assert events[-1]["success"] is False
    assert events[-1]["detail"]["reason"] == "publish_failed"


def test_obsidian_vault_sync_registers_pushes_pulls_and_lists_sources(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    app.state.obsidian_sync = ObsidianSyncStore(tmp_path / "obsidian.json")
    client = authed_client("test-writer")

    registered = client.post(
        "/api/obsidian/vaults",
        json={"vault_name": "Team Vault", "team_id": "masumi", "plugin_version": "0.1.0"},
    )
    assert registered.status_code == 200
    vault_id = registered.json()["vault"]["id"]

    manifest = client.get(f"/api/obsidian/manifest?vault_id={vault_id}")
    pushed = client.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "dataset": "notes",
            "tags": ["team"],
            "documents": [
                {
                    "path": "Team/Architecture.md",
                    "content": "Architecture decision: Citadel syncs explicit Obsidian notes.",
                }
            ],
        },
    )

    assert manifest.status_code == 200
    assert manifest.json()["documents"] == []
    assert pushed.status_code == 200
    payload = pushed.json()
    assert payload["accepted"][0]["path"] == "Team/Architecture.md"
    assert payload["accepted"][0]["rev"] == 1
    assert payload["ingest_results"][0]["accepted"] is True
    document_id = payload["accepted"][0]["document_id"]

    document = client.get(f"/api/documents/{document_id}")
    pulled = client.get(f"/api/obsidian/sync/pull?vault_id={vault_id}&cursor=0")
    sources = client.get("/api/sources?type=obsidian_vault")

    assert document.status_code == 200
    assert document.json()["document"]["body"].startswith("Architecture decision")
    assert pulled.status_code == 200
    assert pulled.json()["documents"][0]["normalized_path"] == "Team/Architecture.md"
    assert sources.status_code == 200
    assert sources.json()["summary"]["obsidian_vaults"] == 1
    assert sources.json()["summary"]["obsidian_documents"] == 1

    reader = authed_client("test-reader")
    rejected = reader.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "documents": [{"path": "Team/Denied.md", "content": "Reader cannot push."}],
        },
    )
    assert rejected.status_code == 403


def test_obsidian_vault_sync_detects_and_resolves_conflicts(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    app.state.obsidian_sync = ObsidianSyncStore(tmp_path / "obsidian.json")
    app.state.conflict_store = KnowledgeConflictStore(tmp_path / "conflicts.json")
    client = authed_client("test-writer")
    vault_id = client.post("/api/obsidian/vaults", json={"vault_name": "Team Vault"}).json()[
        "vault"
    ]["id"]
    first_push = client.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "documents": [{"path": "Team/Roadmap.md", "content": "Remote revision one."}],
        },
    )
    stale_push = client.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "documents": [
                {
                    "path": "Team/Roadmap.md",
                    "content": "Local edit from stale base.",
                    "base_rev": 0,
                }
            ],
        },
    )

    assert first_push.status_code == 200
    assert stale_push.status_code == 200
    conflict = stale_push.json()["conflicts"][0]
    assert conflict["reason"] == "base_revision_mismatch"

    resolved = client.post(
        f"/api/obsidian/conflicts/{conflict['id']}/resolve",
        json={"resolution": "manual", "body": "Merged roadmap note."},
    )
    manifest = client.get(f"/api/obsidian/manifest?vault_id={vault_id}")
    document_id = first_push.json()["accepted"][0]["document_id"]
    document = client.get(f"/api/documents/{document_id}")

    assert resolved.status_code == 200
    assert resolved.json()["conflict"]["status"] == "resolved_manual"
    assert manifest.json()["documents"][0]["current_rev"] == 2
    assert document.json()["document"]["body"] == "Merged roadmap note."


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


def test_expired_bearer_tokens_are_rejected_with_audit_event(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    created = admin.post(
        "/api/access/tokens",
        json={
            "name": "short-lived",
            "role": "reader",
            "kind": "service_account",
            "expires_at": "2020-01-01T00:00:00+00:00",
        },
    )
    token = created.json()["token"]
    token_id = created.json()["api_token"]["id"]

    rejected = TestClient(app, base_url="https://testserver").get(
        "/api/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rejected.status_code == 401

    audit = admin.get("/api/audit?view=failures")
    assert audit.status_code == 200
    rejections = [
        event
        for event in audit.json()["audit_events"]
        if event["action"] == "access.token.rejected"
    ]
    assert rejections[0]["detail"]["reason"] == "expired"
    assert rejections[0]["detail"]["token_id"] == token_id


class EmptyCitadel(FakeCitadel):
    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return []


class ProvenanceCitadel(FakeCitadel):
    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "ghsync:abc123",
                "source": "github_sync_state",
                "dataset": kwargs["dataset"],
                "session_id": "masumi-github-daily",
                "title": "Recent commits",
                "content": "teach the archive about commits",
                "metadata": {
                    "source_url": "https://github.com/orgs/masumi-network/repositories",
                    "checked_at": "2026-06-01T00:00:00Z",
                },
            }
        ]


def test_search_without_dataset_hints_known_datasets() -> None:
    client = authed_client("test-reader")
    app.state.citadel = EmptyCitadel()

    response = client.post("/search", json={"query": "anything"})

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert "note" in body
    assert "masumi-network" in body["known_datasets"]


def test_search_with_explicit_empty_dataset_omits_hint() -> None:
    client = authed_client("test-reader")
    app.state.citadel = EmptyCitadel()

    response = client.post("/search", json={"query": "anything", "dataset": "notes"})

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert "note" not in body


def test_search_results_include_source_provenance_envelope() -> None:
    client = authed_client("test-reader")
    app.state.citadel = ProvenanceCitadel()

    response = client.post(
        "/search",
        json={"query": "commits", "dataset": "masumi-network"},
    )

    assert response.status_code == 200
    hit = response.json()["results"][0]
    assert hit["id"] == "ghsync:abc123"
    assert hit["_citadel"]["rank"] == 1
    assert hit["_citadel"]["dataset"] == "masumi-network"
    assert hit["_citadel"]["result_id"] == "ghsync:abc123"
    assert hit["_citadel"]["document_endpoint"] == "/api/documents/ghsync:abc123"
    assert hit["_citadel"]["provenance"] == {
        "source": "github_sync_state",
        "source_url": "https://github.com/orgs/masumi-network/repositories",
        "title": "Recent commits",
        "session_id": "masumi-github-daily",
    }
    assert hit["_citadel"]["retrieval"]["untrusted_context"] is True
    assert hit["_citadel"]["retrieval"]["citation_required"] is True
    assert hit["_citadel"]["retrieval"]["document_drilldown_available"] is True


def test_github_digest_search_hit_drills_down_to_document(tmp_path: Any) -> None:
    import json as _json

    state_path = tmp_path / "github_state.json"
    state_path.write_text(
        _json.dumps(
            {
                "org": "masumi-network",
                "last_checked_at": "2026-06-01T00:00:00Z",
                "last_digest_at": "2026-06-01T00:00:00Z",
                "last_digest": "# masumi-network GitHub daily update\n\n"
                "## Recent commits\n- abc: teach the archive about commits.\n",
            }
        ),
        encoding="utf-8",
    )
    citadel = FakeCitadel()
    citadel.config = CitadelConfig(
        admin_key="test-admin",
        reader_keys=("test-reader",),
        writer_keys=("test-writer",),
        github_sync_dataset="masumi-network",
        github_sync_state_path=str(state_path),
    )
    client = authed_client("test-reader")
    app.state.citadel = citadel

    from kb.source_search import search_github_sync_state

    hit = search_github_sync_state("commits", citadel.config, top_k=1)[0]
    document = client.get(f"/api/documents/{hit['id']}")

    assert document.status_code == 200
    assert document.json()["document"]["title"] == hit["title"]
    assert "teach the archive about commits" in document.json()["document"]["body"]


def test_knowledge_conflict_listing_and_resolution_are_role_gated(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    app.state.obsidian_sync = ObsidianSyncStore(tmp_path / "obsidian.json")
    writer = authed_client("test-writer")
    app.state.conflict_store = KnowledgeConflictStore(tmp_path / "conflicts.json")
    vault_id = writer.post("/api/obsidian/vaults", json={"vault_name": "Team Vault"}).json()[
        "vault"
    ]["id"]
    writer.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "documents": [{"path": "Team/Roadmap.md", "content": "Server copy."}],
        },
    )
    writer.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "documents": [
                {"path": "Team/Roadmap.md", "content": "Stale local edit.", "base_rev": 0}
            ],
        },
    )

    listed = writer.get("/api/conflicts?status=open")
    assert listed.status_code == 200
    conflicts = listed.json()["conflicts"]
    assert listed.json()["open_count"] == 1
    assert conflicts[0]["kind"] == "obsidian_push"
    assert conflicts[0]["side_a"]["excerpt"] == "Stale local edit."
    assert conflicts[0]["side_b"]["excerpt"] == "Server copy."
    conflict_id = conflicts[0]["id"]

    mesh = writer.get("/api/mesh")
    conflict_events = [
        event for event in mesh.json()["events"] if event["type"] == "conflict"
    ]
    assert conflict_events[0]["details"]["conflict_id"] == conflict_id

    reader_store = app.state.conflict_store
    reader = authed_client("test-reader")
    app.state.conflict_store = reader_store
    reader_list = reader.get("/api/conflicts")
    reader_resolve = reader.post(
        f"/api/conflicts/{conflict_id}/resolve",
        json={"resolution_note": "reader cannot resolve"},
    )
    assert reader_list.status_code == 200
    assert reader_resolve.status_code == 403

    writer_store = app.state.conflict_store
    writer = authed_client("test-writer")
    app.state.conflict_store = writer_store
    resolved = writer.post(
        f"/api/conflicts/{conflict_id}/resolve",
        json={"resolution_note": "Kept the newer server revision."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["conflict"]["status"] == "resolved"
    assert resolved.json()["conflict"]["resolution_note"] == "Kept the newer server revision."
    assert writer.get("/api/conflicts?status=open").json()["conflicts"] == []

    invalid_status = writer.get("/api/conflicts?status=bogus")
    missing = writer.post(
        "/api/conflicts/kconflict_missing/resolve",
        json={"resolution_note": "nothing here"},
    )
    assert invalid_status.status_code == 422
    assert missing.status_code == 404

    actions = [event["action"] for event in app.state.access_store.snapshot()["audit_events"]]
    assert "conflicts.list" in actions
    assert "conflicts.resolve" in actions


def test_knowledge_conflicts_require_authentication() -> None:
    client = TestClient(app, base_url="https://testserver")

    assert client.get("/api/conflicts").status_code == 401
    assert (
        client.post(
            "/api/conflicts/kconflict_x/resolve",
            json={"resolution_note": "no"},
        ).status_code
        == 401
    )


def test_mesh_graph_returns_fallback_without_cognee_graph_access() -> None:
    client = authed_client("test-reader")
    app.state.knowledge_mesh = None  # force rebuild from FakeCitadel (no gateway)

    response = client.get("/api/mesh/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["fallback"] is True
    assert body["fallback_reason"] == "graph_access_unavailable"
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["limit"] == 200


def test_mesh_graph_serves_real_graph_through_injected_gateway() -> None:
    class FakeGraphGateway:
        async def graph_data(self) -> tuple[list[Any], list[Any]]:
            return (
                [
                    ("n1", {"name": "Citadel", "type": "Entity"}),
                    ("n2", {"name": "Cognee", "type": "Tool"}),
                    ("n3", {"name": "Kuzu", "type": "Tool"}),
                ],
                [("n1", "n2", "uses", {}), ("n2", "n3", "embeds", {})],
            )

    client = authed_client("test-reader")
    app.state.knowledge_mesh = KnowledgeMesh(FakeGraphGateway())
    try:
        full = client.get("/api/mesh/graph")
        capped = client.get("/api/mesh/graph?limit=2")
        invalid = client.get("/api/mesh/graph?limit=0")
        unauthenticated = TestClient(app, base_url="https://testserver").get("/api/mesh/graph")
    finally:
        app.state.knowledge_mesh = None

    assert full.status_code == 200
    assert full.json()["fallback"] is False
    assert [node["id"] for node in full.json()["nodes"]] == ["n1", "n2", "n3"]
    assert {
        "source": "n2",
        "target": "n3",
        "relationship": "embeds",
    } in full.json()["edges"]
    assert capped.status_code == 200
    assert capped.json()["truncated"] is True
    assert len(capped.json()["nodes"]) == 2
    assert capped.json()["limit"] == 2
    assert invalid.status_code == 422
    assert unauthenticated.status_code == 401


class KnowledgeCitadel(FakeCitadel):
    async def search(self, query: str, **kwargs: Any) -> list[Any]:
        return [
            {
                "text": "Rotate keys quarterly",
                "source_url": "https://example.com/runbook",
                "score": 0.92,
                "metadata": {"citadel_tags": ["ops"]},
            },
            "bare string result",
        ]


def test_repo_content_sync_status_and_run(tmp_path: Any) -> None:
    class FakeRepoContentSyncer:
        async def status(self) -> dict[str, Any]:
            return {
                "ok": True,
                "enabled": True,
                "source_type": "github_repo_content",
                "tracked_files": 14,
            }

        async def run(self, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
            return {
                "ok": True,
                "enabled": True,
                "files_ingested": 2 if not dry_run else 0,
                "files_skipped": 1,
                "dry_run": dry_run,
                "improved": not dry_run,
            }

    app.state.repo_content_syncer = FakeRepoContentSyncer()
    reader = authed_client("test-reader")
    admin = authed_client("test-admin")

    status = reader.get("/api/repo-content-sync")
    assert status.status_code == 200
    assert status.json()["source_type"] == "github_repo_content"

    denied = reader.post("/api/repo-content-sync/run", json={"dry_run": True})
    assert denied.status_code == 403

    run = admin.post("/api/repo-content-sync/run", json={"force": True, "dry_run": True})
    assert run.status_code == 200
    assert run.json()["dry_run"] is True


def test_recent_contributions_lists_audit_events(tmp_path: Any) -> None:
    store = AccessStore(str(tmp_path / "access.json"))
    app.state.access_store = store
    writer = authed_client("test-writer")

    response = writer.post(
        "/api/contribute",
        json={"title": "WIP: MCP docs", "content": "OAuth uses hosted endpoint.", "tags": ["wip"]},
    )
    assert response.status_code == 200

    recent = writer.get("/api/contributions/recent?limit=5")
    assert recent.status_code == 200
    payload = recent.json()
    assert payload["ok"] is True
    assert len(payload["contributions"]) == 1
    assert payload["contributions"][0]["action"] == "contribute"
    assert payload["contributions"][0]["detail"]["title"] == "WIP: MCP docs"


def test_contribute_routes_through_learning_process_and_audits(tmp_path: Any) -> None:
    client = authed_client("test-writer")
    store = AccessStore(str(tmp_path / "access.json"))
    app.state.access_store = store

    response = client.post(
        "/api/contribute",
        json={
            "title": "Decision: adopt deepseek for enrichment",
            "content": "We standardized on deepseek/deepseek-v4-flash via OpenRouter.",
            "tags": ["decision", "llm"],
            "source_url": "https://github.com/masumi-network/Citadel-Archive",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["accepted"] is True
    assert payload["chunks"] == 1
    assert payload["conflict"] is None
    assert payload["dataset"] == "masumi-network"

    events = store.snapshot()["audit_events"]
    contribute_events = [event for event in events if event["action"] == "contribute"]
    assert len(contribute_events) == 1
    assert contribute_events[0]["success"] is True
    assert contribute_events[0]["detail"]["chunks"] == 1
    assert contribute_events[0]["detail"]["tag_count"] == 4
    assert contribute_events[0]["detail"]["tags"] == [
        "decision",
        "llm",
        "vault-contribution",
        "author:writer-bootstrap-key",
    ]
    # Raw contribution content never lands in the audit trail.
    assert "deepseek-v4-flash" not in json.dumps(contribute_events[0])


def test_contribute_requires_writer_role() -> None:
    reader = authed_client("test-reader")
    body = {"title": "Note", "content": "Body"}

    assert reader.post("/api/contribute", json=body).status_code == 403
    assert (
        TestClient(app, base_url="https://testserver")
        .post("/api/contribute", json=body)
        .status_code
        == 401
    )


def test_contribute_validates_payload() -> None:
    client = authed_client("test-writer")

    assert client.post("/api/contribute", json={"title": "", "content": "x"}).status_code == 422
    assert client.post("/api/contribute", json={"content": "x"}).status_code == 422
    assert client.post("/api/contribute", json={"title": "t"}).status_code == 422


def test_knowledge_alias_returns_flat_agent_friendly_results() -> None:
    client = authed_client("test-reader")
    app.state.citadel = KnowledgeCitadel()

    response = client.get("/api/knowledge", params={"q": "rotate keys", "limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["query"] == "rotate keys"
    assert payload["results"][0] == {
        "text": "Rotate keys quarterly",
        "source": "https://example.com/runbook",
        "score": 0.92,
        "tags": ["ops"],
    }
    assert payload["results"][1]["text"] == "bare string result"
    assert payload["results"][1]["source"] is None


def test_knowledge_alias_validates_query_and_limit() -> None:
    client = authed_client("test-reader")

    assert client.get("/api/knowledge", params={"q": "   "}).status_code == 422
    assert client.get("/api/knowledge", params={"q": "x", "limit": 0}).status_code == 422
    assert client.get("/api/knowledge", params={"q": "x", "limit": 999}).status_code == 422
    assert (
        TestClient(app, base_url="https://testserver")
        .get("/api/knowledge", params={"q": "x"})
        .status_code
        == 401
    )


def test_optimize_endpoint_is_admin_only_bounded_and_audited(
    tmp_path: Any, monkeypatch: Any
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    writer = authed_client("test-writer")
    assert writer.post("/api/learning-agent/optimize", json={}).status_code == 403

    client = authed_client()
    store = AccessStore(str(tmp_path / "access.json"))
    app.state.access_store = store

    response = client.post(
        "/api/learning-agent/optimize",
        json={"dry_run": True, "max_items": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["max_items"] == 5
    assert payload["optimized"] == 0  # no LLM key -> deterministic no-op fallback
    assert payload["llm_used"] is False

    events = store.snapshot()["audit_events"]
    optimize_events = [
        event for event in events if event["action"] == "learning_agent.optimize"
    ]
    assert len(optimize_events) == 1
    assert optimize_events[0]["success"] is True
    assert optimize_events[0]["detail"]["dry_run"] is True


class MultiSearchCitadel(FakeCitadel):
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.session_calls: dict[str, str | None] = {}

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        dataset = kwargs["dataset"]
        self.search_calls.append(dataset)
        self.session_calls[dataset] = kwargs.get("session_id")
        return [
            {
                "query": query,
                "dataset": dataset,
                "text": f"{query} in {dataset}",
                "top_k": kwargs["top_k"],
            }
        ]


class TrackingCitadel(FakeCitadel):
    def __init__(self) -> None:
        self.ingest_calls: list[dict[str, Any]] = []

    async def ingest(self, data: str, **kwargs: Any) -> IngestResult:
        self.ingest_calls.append({"data": data, **kwargs})
        dataset = kwargs.get("dataset") or "notes"
        return IngestResult(True, "accepted", dataset, tuple(kwargs.get("tags") or ()))


def test_create_seat_api_provisions_node_and_writer_token(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()

    response = client.post(
        "/api/access/seats",
        json={"name": "Alice Smith", "slug": "alice", "email": "alice@example.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["principal"]["seat_slug"] == "alice"
    assert payload["principal"]["default_dataset"] == "seat:alice"
    assert payload["principal"]["default_session"] == "seat-alice"
    assert payload["api_token"]["default_dataset"] == "seat:alice"
    assert payload["api_token"]["allowed_datasets"] == ["seat:alice", "masumi-network"]
    assert payload["token"].startswith("ctdl_")

    duplicate = client.post(
        "/api/access/seats",
        json={"name": "Alice Two", "slug": "alice"},
    )
    assert duplicate.status_code == 422
    assert "already exists" in duplicate.json()["detail"]

    invalid = client.post(
        "/api/access/seats",
        json={"name": "Bad", "slug": "Bad Slug"},
    )
    assert invalid.status_code == 422


def test_seat_token_searches_node_and_central(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    created = admin.post(
        "/api/access/seats",
        json={"name": "Bob", "slug": "bob"},
    )
    token = created.json()["token"]
    app.state.citadel = MultiSearchCitadel()
    api_client = TestClient(app, base_url="https://testserver")

    search = api_client.post(
        "/search",
        json={"query": "architecture"},
        headers={"Authorization": f"Bearer {token}"},
    )
    knowledge = api_client.get(
        "/api/knowledge",
        params={"q": "architecture", "limit": 5},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert search.status_code == 200
    payload = search.json()
    assert payload["dataset"] == "seat:bob"
    assert payload["datasets"] == ["seat:bob", "masumi-network"]
    assert len(payload["results"]) == 2
    assert payload["results"][0]["dataset"] == "seat:bob"
    assert payload["results"][1]["dataset"] == "masumi-network"
    assert set(app.state.citadel.search_calls) == {"seat:bob", "masumi-network"}
    # The seat session scopes the private node only; Central must stay
    # dataset-wide (session_id None) or org-wide hits get hidden.
    assert app.state.citadel.session_calls == {
        "seat:bob": "seat-bob",
        "masumi-network": None,
    }

    assert knowledge.status_code == 200
    assert knowledge.json()["datasets"] == ["seat:bob", "masumi-network"]


def test_seat_cannot_recall_another_seats_session(tmp_path: Any) -> None:
    # Session-scoped recall ignores the dataset allowlist, and seat sessions are
    # derived from a guessable slug, so a seat naming another seat's session would
    # read its private node. A non-bypass caller may only name its own session.
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    admin.post("/api/access/seats", json={"name": "Alice", "slug": "alice"})
    token = admin.post("/api/access/seats", json={"name": "Bob", "slug": "bob"}).json()["token"]
    app.state.citadel = MultiSearchCitadel()
    api_client = TestClient(app, base_url="https://testserver")

    foreign = api_client.post(
        "/search",
        json={"query": "secrets", "session_id": "seat-alice"},
        headers={"Authorization": f"Bearer {token}"},
    )
    own = api_client.post(
        "/search",
        json={"query": "notes", "session_id": "seat-bob"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert foreign.status_code == 403
    assert foreign.json()["detail"] == "Session not allowed."
    assert own.status_code == 200
    # Even an explicit own session scopes the node only; Central stays wide.
    assert app.state.citadel.session_calls == {
        "seat:bob": "seat-bob",
        "masumi-network": None,
    }


def test_admin_may_target_any_session(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post(
        "/api/access/tokens",
        json={"name": "ops", "role": "admin", "kind": "service_account"},
    ).json()["token"]
    app.state.citadel = MultiSearchCitadel()
    api_client = TestClient(app, base_url="https://testserver")

    search = api_client.post(
        "/search",
        json={"query": "anything", "dataset": "masumi-network", "session_id": "masumi-github-daily"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert search.status_code == 200
    assert app.state.citadel.session_calls == {"masumi-network": "masumi-github-daily"}


def test_seat_search_deduplicates_preferring_node(tmp_path: Any) -> None:
    class DuplicateCitadel(FakeCitadel):
        async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"text": "shared hit", "dataset": kwargs["dataset"]}]

    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post("/api/access/seats", json={"name": "Carol", "slug": "carol"}).json()["token"]
    app.state.citadel = DuplicateCitadel()
    api_client = TestClient(app, base_url="https://testserver")

    search = api_client.post(
        "/search",
        json={"query": "shared", "top_k": 5},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert search.status_code == 200
    assert len(search.json()["results"]) == 1
    assert search.json()["results"][0]["dataset"] == "seat:carol"


def test_seat_ingest_defaults_to_node_light_path(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post("/api/access/seats", json={"name": "Dana", "slug": "dana"}).json()["token"]
    tracking = TrackingCitadel()
    app.state.citadel = tracking
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    response = api_client.post(
        "/ingest",
        json={"data": "Working memory note"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["dataset"] == "seat:dana"
    assert len(tracking.ingest_calls) == 1
    assert tracking.ingest_calls[0]["dataset"] == "seat:dana"


def test_org_tag_ingest_routes_to_central(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post("/api/access/seats", json={"name": "Eve", "slug": "eve"}).json()["token"]
    tracking = TrackingCitadel()
    app.state.citadel = tracking
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    response = api_client.post(
        "/ingest",
        json={"data": "Org policy", "tags": ["repo-content"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["dataset"] == "masumi-network"
    assert len(tracking.ingest_calls) == 1
    assert tracking.ingest_calls[0]["dataset"] == "masumi-network"


def test_promotion_tag_dual_writes_node_and_central(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post("/api/access/seats", json={"name": "Frank", "slug": "frank"}).json()["token"]
    tracking = TrackingCitadel()
    app.state.citadel = tracking
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    response = api_client.post(
        "/ingest",
        json={"data": "Curated share", "tags": ["org-ready"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["dataset"] == "masumi-network"
    assert len(tracking.ingest_calls) == 2
    assert tracking.ingest_calls[0]["dataset"] == "seat:frank"
    assert tracking.ingest_calls[1]["dataset"] == "masumi-network"


def test_seat_token_cannot_reach_another_seat_node(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    admin.post("/api/access/seats", json={"name": "Grace", "slug": "grace"})
    token = admin.post("/api/access/seats", json={"name": "Heidi", "slug": "heidi"}).json()["token"]
    app.state.citadel = TrackingCitadel()
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    read = api_client.post(
        "/search",
        json={"query": "secrets", "dataset": "seat:grace"},
        headers={"Authorization": f"Bearer {token}"},
    )
    write = api_client.post(
        "/ingest",
        json={"data": "cross-seat write", "dataset": "seat:grace"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert read.status_code == 403
    assert read.json()["detail"] == "Dataset not allowed: seat:grace."
    assert write.status_code == 403
    assert write.json()["detail"] == "Dataset not allowed: seat:grace."
    assert app.state.citadel.ingest_calls == []


def test_unscoped_token_cannot_reach_a_seat_node(tmp_path: Any) -> None:
    # A writer token with no allowlist stays open for ordinary datasets but must
    # never be able to name a private seat node and reach it.
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    admin.post("/api/access/seats", json={"name": "Ivan", "slug": "ivan"})
    token = admin.post(
        "/api/access/tokens",
        json={"name": "open-writer", "role": "writer", "kind": "service_account"},
    ).json()["token"]
    app.state.citadel = TrackingCitadel()
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    seat_write = api_client.post(
        "/ingest",
        json={"data": "poke", "dataset": "seat:ivan"},
        headers={"Authorization": f"Bearer {token}"},
    )
    ordinary_write = api_client.post(
        "/ingest",
        json={"data": "fine", "dataset": "team-notes"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert seat_write.status_code == 403
    assert seat_write.json()["detail"] == "Dataset not allowed: seat:ivan."
    assert ordinary_write.status_code == 200
    assert ordinary_write.json()["dataset"] == "team-notes"


def test_seat_direct_central_write_requires_org_tag(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post("/api/access/seats", json={"name": "Karl", "slug": "karl"}).json()["token"]
    tracking = TrackingCitadel()
    app.state.citadel = tracking
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    untagged = api_client.post(
        "/ingest",
        json={"data": "raw drop", "dataset": "masumi-network"},
        headers={"Authorization": f"Bearer {token}"},
    )
    tagged = api_client.post(
        "/ingest",
        json={"data": "curated", "dataset": "masumi-network", "tags": ["org-ready"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert untagged.status_code == 403
    assert "org tag" in untagged.json()["detail"]
    assert tagged.status_code == 200
    assert tagged.json()["dataset"] == "masumi-network"
    # Only the tagged write reached Cognee; the untagged one never ingested.
    assert [call["dataset"] for call in tracking.ingest_calls] == ["masumi-network"]


def test_seat_token_defaulting_to_central_still_gated(tmp_path: Any) -> None:
    # A seat-scoped token whose default_dataset is Central must not slip the
    # curation gate: the seat node in its allowlist is the authoritative signal,
    # so raw drops into Central (explicit or via the default target) are blocked.
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post(
        "/api/access/tokens",
        json={
            "name": "seat-defaulting-central",
            "role": "writer",
            "kind": "user",
            "default_dataset": "masumi-network",
            "allowed_datasets": ["seat:leo", "masumi-network"],
        },
    ).json()["token"]
    tracking = TrackingCitadel()
    app.state.citadel = tracking
    app.state.mesh = MeshState()
    api_client = TestClient(app, base_url="https://testserver")

    explicit = api_client.post(
        "/ingest",
        json={"data": "raw drop", "dataset": "masumi-network"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # No dataset given -> default target resolves to Central, which must also gate.
    defaulted = api_client.post(
        "/ingest",
        json={"data": "raw default drop"},
        headers={"Authorization": f"Bearer {token}"},
    )
    tagged = api_client.post(
        "/ingest",
        json={"data": "curated", "dataset": "masumi-network", "tags": ["org-ready"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert explicit.status_code == 403
    assert "org tag" in explicit.json()["detail"]
    assert defaulted.status_code == 403
    assert "org tag" in defaulted.json()["detail"]
    assert tagged.status_code == 200
    assert [call["dataset"] for call in tracking.ingest_calls] == ["masumi-network"]


def test_obsidian_push_routes_org_tagged_docs_through_tags(tmp_path: Any) -> None:
    # Obsidian sync must route on the document's real tags like /ingest: an
    # org-bound (promotion) note dual-writes the seat node and Central instead of
    # being trapped in the node because the resolver was handed empty tags.
    app.state.access_store = AccessStore(tmp_path / "access.json")
    app.state.obsidian_sync = ObsidianSyncStore(tmp_path / "obsidian.json")
    app.state.mesh = MeshState()
    admin = authed_client()
    token = admin.post("/api/access/seats", json={"name": "Mia", "slug": "mia"}).json()["token"]
    tracking = TrackingCitadel()
    app.state.citadel = tracking
    api_client = TestClient(app, base_url="https://testserver")
    headers = {"Authorization": f"Bearer {token}"}

    vault_id = api_client.post(
        "/api/obsidian/vaults",
        json={"vault_name": "Mia Vault"},
        headers=headers,
    ).json()["vault"]["id"]
    pushed = api_client.post(
        "/api/obsidian/sync/push",
        json={
            "vault_id": vault_id,
            "tags": ["org-ready"],
            "documents": [{"path": "Notes/Share.md", "content": "Org-ready note."}],
        },
        headers=headers,
    )

    assert pushed.status_code == 200
    datasets = [call["dataset"] for call in tracking.ingest_calls]
    assert datasets == ["seat:mia", "masumi-network"]
    # The audit records both legs of the dual-write, not just the primary outcome.
    events = app.state.access_store.snapshot()["audit_events"]
    push_event = next(e for e in events if e["action"] == "obsidian.sync.push")
    assert push_event["detail"]["written_datasets"] == ["masumi-network", "seat:mia"]


def test_create_seat_api_rejects_admin_role(tmp_path: Any) -> None:
    app.state.access_store = AccessStore(tmp_path / "access.json")
    client = authed_client()

    response = client.post(
        "/api/access/seats",
        json={"name": "Judy", "slug": "judy", "role": "admin"},
    )

    assert response.status_code == 422
    assert "admin role" in response.json()["detail"]


def test_admin_scope_override_is_audited(tmp_path: Any) -> None:
    # An admin-role token that carries its own allowlist but reaches outside it
    # bypasses enforcement by design; the bypass must be flagged in the audit log.
    app.state.access_store = AccessStore(tmp_path / "access.json")
    admin = authed_client()
    token = admin.post(
        "/api/access/tokens",
        json={
            "name": "scoped-admin",
            "role": "admin",
            "kind": "service_account",
            "allowed_datasets": ["personal"],
        },
    ).json()["token"]
    app.state.citadel = MultiSearchCitadel()
    api_client = TestClient(app, base_url="https://testserver")

    search = api_client.post(
        "/search",
        json={"query": "anything", "dataset": "masumi-network"},
        headers={
            "Authorization": f"Bearer {token}",
            "x-citadel-mcp-tool": "citadel_search",
        },
    )

    assert search.status_code == 200
    events = app.state.access_store.snapshot()["audit_events"]
    search_events = [event for event in events if event["detail"].get("operation") == "search"]
    assert search_events
    assert search_events[-1]["detail"]["scope_override"] is True
