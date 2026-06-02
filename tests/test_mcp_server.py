from __future__ import annotations

import asyncio
from io import BytesIO
import inspect
from typing import Any
from urllib.error import HTTPError

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import kb.mcp_server as mcp_server
from kb.mcp_server import (
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

    def get(self, path: str, *, tool_name: str | None = None) -> dict[str, Any]:
        self.gets.append({"path": path, "tool_name": tool_name})
        return {"ok": True, "path": path, "tool_name": tool_name}

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


def test_search_clamps_top_k_and_tracks_tool_name() -> None:
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_search", " source state ", None, top_k=999)

    assert result["payload"]["query"] == "source state"
    assert result["payload"]["top_k"] == MAX_SEARCH_TOP_K
    assert result["tool_name"] == "citadel_search"
    assert client.posts[0]["path"] == "/search"


def test_search_uses_mcp_default_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITADEL_MCP_DEFAULT_DATASET", "masumi-network")
    client = FakeHttpClient()
    server = create_mcp_server(client)

    result = run_tool(server, "citadel_search", " source state ", None)
    explicit = run_tool(server, "citadel_search", " notes ", None, dataset="personal")

    assert result["payload"]["dataset"] == "masumi-network"
    assert explicit["payload"]["dataset"] == "personal"


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
