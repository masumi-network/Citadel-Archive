from __future__ import annotations

from typing import Any

from kb.knowledge_mesh import KnowledgeMesh, build_graph_payload, fallback_graph


class FakeGraphGateway:
    def __init__(
        self,
        nodes: list[Any] | None = None,
        edges: list[Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.nodes = nodes or []
        self.edges = edges or []
        self.error = error
        self.calls = 0

    async def graph_data(self) -> tuple[list[Any], list[Any]]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.nodes, self.edges


NODES = [
    ("node-1", {"name": "Citadel", "type": "Entity"}),
    ("node-2", {"label": "Cognee", "node_type": "Tool"}),
    ("node-3", {}),
]
EDGES = [
    ("node-1", "node-2", "uses", {}),
    ("node-2", "node-3", "", {}),
    ("node-1", "node-missing", "dangles", {}),
]


async def test_graph_maps_cognee_tuples_to_nodes_and_edges() -> None:
    mesh = KnowledgeMesh(FakeGraphGateway(NODES, EDGES))

    graph = await mesh.graph()

    assert graph["ok"] is True
    assert graph["fallback"] is False
    assert graph["nodes"] == [
        {"id": "node-1", "label": "Citadel", "type": "Entity"},
        {"id": "node-2", "label": "Cognee", "type": "Tool"},
        {"id": "node-3", "label": "node-3", "type": "node"},
    ]
    assert {"source": "node-1", "target": "node-2", "relationship": "uses"} in graph["edges"]
    # Empty relationship names fall back to "related"; dangling edges are dropped.
    assert {"source": "node-2", "target": "node-3", "relationship": "related"} in graph["edges"]
    assert all(edge["target"] != "node-missing" for edge in graph["edges"])
    assert graph["truncated"] is False


async def test_graph_caps_nodes_and_drops_edges_outside_the_cap() -> None:
    mesh = KnowledgeMesh(FakeGraphGateway(NODES, EDGES))

    graph = await mesh.graph(limit=2)

    assert [node["id"] for node in graph["nodes"]] == ["node-1", "node-2"]
    assert graph["edges"] == [
        {"source": "node-1", "target": "node-2", "relationship": "uses"}
    ]
    assert graph["truncated"] is True
    assert graph["total_nodes"] == 3


async def test_empty_cognee_graph_returns_fallback() -> None:
    mesh = KnowledgeMesh(FakeGraphGateway([], []))

    graph = await mesh.graph()

    assert graph["ok"] is True
    assert graph["fallback"] is True
    assert graph["fallback_reason"] == "graph_empty"
    assert graph["nodes"] == []
    assert graph["edges"] == []


async def test_graph_engine_errors_never_raise() -> None:
    mesh = KnowledgeMesh(FakeGraphGateway(error=RuntimeError("kuzu offline")))

    graph = await mesh.graph()

    assert graph["fallback"] is True
    assert graph["fallback_reason"] == "graph_engine_error:RuntimeError"


async def test_gateway_without_graph_access_returns_fallback() -> None:
    class NoGraphGateway:
        pass

    for gateway in (NoGraphGateway(), None):
        graph = await KnowledgeMesh(gateway).graph()
        assert graph["fallback"] is True
        assert graph["fallback_reason"] == "graph_access_unavailable"


def test_build_graph_payload_skips_malformed_rows() -> None:
    payload = build_graph_payload(
        [("ok-node", {"name": "Fine"}), None, 42, ("dupe", {}), ("dupe", {})],
        [None, ("ok-node", "dupe", "links", {})],
        limit=10,
    )

    assert [node["id"] for node in payload["nodes"]] == ["ok-node", "dupe"]
    assert payload["edges"] == [
        {"source": "ok-node", "target": "dupe", "relationship": "links"}
    ]


def test_fallback_graph_shape() -> None:
    graph = fallback_graph("graph_empty")

    assert graph == {
        "ok": True,
        "nodes": [],
        "edges": [],
        "total_nodes": 0,
        "total_edges": 0,
        "truncated": False,
        "fallback": True,
        "fallback_reason": "graph_empty",
    }
