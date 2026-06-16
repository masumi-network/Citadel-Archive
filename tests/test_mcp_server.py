from __future__ import annotations

import asyncio
from io import BytesIO
import inspect
import json
from typing import Any
from urllib.error import HTTPError

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import kb.mcp_server as mcp_server
from kb.mcp_server import (
    MAX_AUDIT_LIMIT,
    MAX_SEARCH_TOP_K,
    TOOL_POLICIES,
    CitadelHttpClient,
    CitadelMcpError,
    create_mcp_server,
)


class FakeHttpClient:
    def __init__(self) -> None:
        self.gets: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.public_gets: list[str] = []

    def get(
        self,
        path: str,
        *,
        tool_name: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.gets.append(
            {
                "path": path,
                "tool_name": tool_name,
                "extra_headers": extra_headers or {},
            }
        )
        return {
            "ok": True,
            "path": path,
            "tool_name": tool_name,
            "extra_headers": extra_headers or {},
        }

    def get_public(self, path: str) -> dict[str, Any]:
        self.public_gets.append(path)
        return {"ok": True, "path": path, "public": True}

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        self.posts.append({"path": path, "payload": payload, "tool_name": tool_name})
        return {"ok": True, "path": path, "payload": payload, "tool_name": tool_name}


def tool_fn(server: Any, name: str) -> Any:
    return server._tool_manager.get_tool(name).fn


def run_tool(server: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    result = tool_fn(server, name)(*args, **kwargs)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def test_registered_tools_include_safety_annotations() -> None:
    server = create_mcp_server(FakeHttpClient())

    for name, policy in TOOL_POLICIES.items():
        tool = server._tool_manager.get_tool(name)

        assert tool is not None
        assert tool.annotations == policy.annotations


def test_discovery_tool_authenticates_then_fetches_public_manifest() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_discovery", None)

    assert result["path"] == "/.well-known/citadel.json"
    assert result["tool_name"] is None
    assert client.gets == [
        {"path": "/api/session", "tool_name": "citadel_discovery", "extra_headers": {}},
        {"path": "/.well-known/citadel.json", "tool_name": None, "extra_headers": {}},
    ]


def test_discovery_forwarded_headers_are_validated() -> None:
    class FakeRequest:
        headers = {
            "x-forwarded-proto": "https",
            "x-forwarded-host": "citadel-archive-production.up.railway.app",
        }
        url = "http://127.0.0.1:8000/mcp"

    class FakeRequestContext:
        request = FakeRequest()

    class FakeContext:
        request_context = FakeRequestContext()

    assert mcp_server._public_url_headers_from_context(FakeContext()) == {
        "X-Forwarded-Host": "citadel-archive-production.up.railway.app",
        "X-Forwarded-Proto": "https",
    }


def test_discovery_forwarded_headers_reject_malformed_values() -> None:
    class FakeRequest:
        headers = {
            "x-forwarded-proto": "javascript",
            "x-forwarded-host": "evil.example/path",
        }
        url = "http://127.0.0.1:8000/mcp"

    class FakeRequestContext:
        request = FakeRequest()

    class FakeContext:
        request_context = FakeRequestContext()

    assert mcp_server._public_url_headers_from_context(FakeContext()) == {}


def test_discovery_resource_reads_public_manifest_only() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    resource = asyncio.run(server._resource_manager.get_resource("citadel://discovery"))

    assert resource is not None
    assert json.loads(resource.fn()) == {
        "ok": True,
        "path": "/.well-known/citadel.json",
        "public": True,
    }
    assert client.public_gets == ["/.well-known/citadel.json"]
    assert client.gets == []


def test_search_clamps_top_k_and_tracks_tool_name() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_search", " source state ", None, top_k=999)

    assert result["payload"]["query"] == "source state"
    assert result["payload"]["top_k"] == MAX_SEARCH_TOP_K
    assert result["tool_name"] == "citadel_search"
    assert client.posts[0]["path"] == "/search"


def test_search_omits_dataset_for_server_side_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITADEL_MCP_DEFAULT_DATASET", "masumi-network")
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_search", " source state ", None)
    explicit = run_tool(server, "citadel_search", " notes ", None, dataset="personal")

    assert result["payload"]["dataset"] is None
    assert explicit["payload"]["dataset"] == "personal"


def test_backup_mirror_tools_forward_admin_calls() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    status = run_tool(server, "citadel_backup_mirror_status", None)
    run = run_tool(server, "citadel_run_backup_mirror", None)
    write = run_tool(server, "citadel_run_backup_mirror", None, dry_run=False)

    assert status["path"] == "/api/backup-mirror"
    assert status["tool_name"] == "citadel_backup_mirror_status"
    assert run["path"] == "/api/backup-mirror/run"
    assert run["payload"] == {"dry_run": True}
    assert run["tool_name"] == "citadel_run_backup_mirror"
    assert write["payload"] == {"dry_run": False}


def test_audit_tool_uses_bounded_server_view() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    default = run_tool(server, "citadel_audit_events", None)
    failures = run_tool(server, "citadel_audit_events", None, view="failures", limit=999)

    assert default["path"] == "/api/audit?view=mcp&limit=50"
    assert default["tool_name"] == "citadel_audit_events"
    assert failures["path"] == f"/api/audit?view=failures&limit={MAX_AUDIT_LIMIT}"

    with pytest.raises(ToolError, match="view must be one of"):
        run_tool(server, "citadel_audit_events", None, view="everything")


def test_write_tools_reject_empty_or_oversized_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    server = create_mcp_server(FakeHttpClient())

    with pytest.raises(ToolError, match="data must not be empty"):
        run_tool(server, "citadel_ingest", "   ", None)

    monkeypatch.setenv("CITADEL_MCP_MAX_INGEST_BYTES", "4")
    with pytest.raises(ToolError, match="payload is 5 bytes"):
        run_tool(server, "citadel_ingest", "12345", None)

    with pytest.raises(ToolError, match="qa_id must not be empty"):
        run_tool(server, "citadel_record_feedback", "", None)


def test_remote_http_base_url_is_rejected_without_escape_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CITADEL_MCP_ALLOW_INSECURE_HTTP", raising=False)

    with pytest.raises(CitadelMcpError, match="Refusing insecure remote Citadel URL"):
        CitadelHttpClient(base_url="http://citadel.example", access_token="ctdl_test")

    monkeypatch.setenv("CITADEL_MCP_ALLOW_INSECURE_HTTP", "true")
    client = CitadelHttpClient(base_url="http://citadel.example", access_token="ctdl_test")

    assert client.base_url == "http://citadel.example"


def test_missing_access_token_error_does_not_leak_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CITADEL_MCP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CITADEL_ACCESS_TOKEN", raising=False)
    client = CitadelHttpClient(base_url="http://localhost:8000", access_token=None)

    with pytest.raises(CitadelMcpError) as exc_info:
        client.get("/api/session", tool_name="citadel_session")

    message = str(exc_info.value)
    assert "CITADEL_MCP_ACCESS_TOKEN" in message
    assert "ctdl_" not in message


def test_http_errors_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "ctdl_secret_token"

    def fake_urlopen(request: Any, timeout: float) -> Any:
        assert request.get_header("X-citadel-mcp-tool") == "citadel_search"
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            BytesIO(
                b'{"detail":"bearer ctdl_secret_token token: ctdl_other api_key=sk-test"}'
            ),
        )

    monkeypatch.setattr(mcp_server, "urlopen", fake_urlopen)
    client = CitadelHttpClient(base_url="http://localhost:8000", access_token=token)

    with pytest.raises(CitadelMcpError) as exc_info:
        client.post("/search", {"query": "anything"}, tool_name="citadel_search")

    message = str(exc_info.value)
    assert token not in message
    assert "ctdl_other" not in message
    assert "sk-test" not in message
    assert "[REDACTED]" in message


def test_contribute_tool_posts_through_the_contribute_endpoint() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(
        server,
        "citadel_contribute",
        " Decision: adopt deepseek ",
        "We standardized on deepseek/deepseek-v4-flash for enrichment.",
        None,
        tags=["decision"],
        source_url="https://github.com/masumi-network/Citadel-Archive",
    )

    assert result["path"] == "/api/contribute"
    assert result["tool_name"] == "citadel_contribute"
    assert result["payload"]["title"] == "Decision: adopt deepseek"
    assert result["payload"]["tags"] == ["decision"]
    assert result["payload"]["source_url"] == (
        "https://github.com/masumi-network/Citadel-Archive"
    )


def test_list_sources_includes_repo_content_sync() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_list_sources", None)

    paths = [call["path"] for call in client.gets]
    assert "/api/repo-content-sync" in paths
    assert "/api/sources" in paths
    assert result["repo_content_sync"]["path"] == "/api/repo-content-sync"


def test_run_repo_content_sync_tool_posts_to_admin_endpoint() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_run_repo_content_sync", None, force=True, dry_run=True)

    assert result["path"] == "/api/repo-content-sync/run"
    assert client.posts[-1]["payload"] == {"force": True, "dry_run": True}


def test_recent_contributions_tool_reads_audit_feed() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_recent_contributions", None, limit=5, mine=True)

    assert result["path"] == "/api/contributions/recent?limit=5&mine=true"
    assert client.gets[-1]["tool_name"] == "citadel_recent_contributions"


def test_contribute_tool_rejects_empty_or_oversized_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = create_mcp_server(FakeHttpClient())

    with pytest.raises(ToolError, match="title must not be empty"):
        run_tool(server, "citadel_contribute", "  ", "Body", None)

    with pytest.raises(ToolError, match="content must not be empty"):
        run_tool(server, "citadel_contribute", "Title", "   ", None)

    monkeypatch.setenv("CITADEL_MCP_MAX_INGEST_BYTES", "4")
    with pytest.raises(ToolError, match="payload is 5 bytes"):
        run_tool(server, "citadel_contribute", "Title", "12345", None)
