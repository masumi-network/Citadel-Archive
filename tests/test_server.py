from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from kb.access import AccessStore
from kb.config import CitadelConfig
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
