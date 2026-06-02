from __future__ import annotations

from fastapi.testclient import TestClient

from kb.server import app


def test_list_skills() -> None:
    client = TestClient(app, base_url="https://citadel.example")
    response = client.get("/skills")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    slugs = {item["slug"] for item in payload["skills"]}
    assert slugs == {"boundary", "connect", "vault"}
    connect = next(item for item in payload["skills"] if item["slug"] == "connect")
    assert connect["url"] == "https://citadel.example/skills/connect"
    assert "mcp" in connect["aliases"]


def test_get_skill_connect() -> None:
    client = TestClient(app)
    response = client.get("/skills/connect")
    assert response.status_code == 200
    assert "citadel-mcp-connector" in response.text
    assert response.headers["content-type"].startswith("text/markdown")


def test_get_skill_alias() -> None:
    client = TestClient(app)
    response = client.get("/skills/mcp")
    assert response.status_code == 200
    assert "Citadel MCP Connector" in response.text


def test_get_skill_unknown() -> None:
    client = TestClient(app)
    response = client.get("/skills/not-a-real-skill")
    assert response.status_code == 404


def test_get_skill_boundary_alias() -> None:
    client = TestClient(app)
    response = client.get("/skills/privacy")
    assert response.status_code == 200
    assert "Public vs Private" in response.text
