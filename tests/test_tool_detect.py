from __future__ import annotations

import json

import pytest

from kb import tool_detect as td

NODE = "https://node.example"


def test_specs_modes() -> None:
    for write_tool in ("cursor", "codex", "gemini", "windsurf"):
        assert td.SPECS[write_tool].mode == "write"
    for snippet_tool in ("claude", "cline", "zed"):
        assert td.SPECS[snippet_tool].mode == "snippet"
    assert td.SPECS["pi"].mode == "note"


def test_cursor_merge_preserves_and_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cur = tmp_path / ".cursor" / "mcp.json"
    cur.parent.mkdir(parents=True)
    cur.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    first = td.apply("cursor", node_url=NODE)
    assert first.action == "wrote"
    data = json.loads(cur.read_text())
    assert "other" in data["mcpServers"]  # sibling server preserved
    assert data["mcpServers"]["citadel"]["url"] == "https://node.example/mcp/"
    assert "${env:CITADEL_MCP_ACCESS_TOKEN}" in data["mcpServers"]["citadel"]["headers"]["Authorization"]

    assert td.apply("cursor", node_url=NODE).action == "unchanged"


def test_cursor_creates_file_when_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert td.apply("cursor", node_url=NODE).action == "wrote"
    assert (tmp_path / ".cursor" / "mcp.json").exists()


def test_cursor_backs_up_corrupt_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cur = tmp_path / ".cursor" / "mcp.json"
    cur.parent.mkdir(parents=True)
    cur.write_text("{ not valid json")
    result = td.apply("cursor", node_url=NODE)
    assert result.action == "wrote"
    assert (cur.parent / "mcp.json.citadel-bak").exists()  # original preserved
    assert "citadel" in json.loads(cur.read_text())["mcpServers"]


def test_codex_append_fallback_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(td, "_which", lambda name: False)  # force the config.toml path
    first = td.apply("codex", node_url=NODE)
    assert first.action == "wrote"
    cfg = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.citadel]" in cfg
    assert 'bearer_token_env_var = "CITADEL_MCP_ACCESS_TOKEN"' in cfg
    assert td.apply("codex", node_url=NODE).action == "unchanged"


def test_gemini_write_uses_httpurl_and_dollar_var(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert td.apply("gemini", node_url=NODE).action == "wrote"
    entry = json.loads((tmp_path / ".gemini" / "settings.json").read_text())["mcpServers"]["citadel"]
    assert entry["httpUrl"] == "https://node.example/mcp/"  # httpUrl, not url (SSE)
    # Gemini expands $VAR, NOT the ${env:} form.
    assert entry["headers"]["Authorization"] == "Bearer $CITADEL_MCP_ACCESS_TOKEN"


def test_windsurf_write_uses_serverurl_and_env_ref(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert td.apply("windsurf", node_url=NODE).action == "wrote"
    entry = json.loads(
        (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text()
    )["mcpServers"]["citadel"]
    assert entry["serverUrl"] == "https://node.example/mcp/"
    assert entry["headers"]["Authorization"] == "Bearer ${env:CITADEL_MCP_ACCESS_TOKEN}"


def test_snippet_shapes() -> None:
    cline = td.apply("cline", node_url=NODE)
    assert '"streamableHttp"' in cline.snippet  # camelCase is load-bearing for Cline

    zed = td.apply("zed", node_url=NODE)
    assert "context_servers" in zed.snippet and '"source"' not in zed.snippet

    claude = td.apply("claude", node_url=NODE)
    assert "claude mcp add" in claude.snippet and "--scope user" in claude.snippet


def test_pi_is_note_only() -> None:
    result = td.apply("pi", node_url=NODE)
    assert result.action == "note"
    assert "no native MCP" in result.detail


def test_unknown_tool_errors() -> None:
    assert td.apply("nope", node_url=NODE).action == "error"
