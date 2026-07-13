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


# --- dataset attribution (seat:<slug> datasets + synthetic hubs) -------------


class FakeDatasetGateway(FakeGraphGateway):
    def __init__(
        self,
        nodes: list[Any] | None = None,
        edges: list[Any] | None = None,
        *,
        dataset_map: dict[str, list[str]] | None = None,
        map_error: Exception | None = None,
    ) -> None:
        super().__init__(nodes, edges)
        self.dataset_map = dataset_map or {}
        self.map_error = map_error

    async def node_dataset_map(self) -> dict[str, list[str]]:
        if self.map_error:
            raise self.map_error
        return self.dataset_map


DOC_NODES = [
    ("doc-1", {"name": "Design Doc", "type": "TextDocument"}),
    ("chunk-1", {"text": "chunk body", "type": "DocumentChunk"}),
]
DOC_EDGES = [("chunk-1", "doc-1", "is_part_of", {})]


def test_build_graph_payload_without_dataset_map_is_unchanged() -> None:
    baseline = build_graph_payload(NODES, EDGES, limit=10)
    payload = build_graph_payload(NODES, EDGES, limit=10, dataset_map=None)

    assert payload == baseline
    assert all("dataset" not in node for node in payload["nodes"])
    assert all(node["type"] != "dataset" for node in payload["nodes"])
    assert all(edge["relationship"] != "belongs_to" for edge in payload["edges"])


def test_dataset_map_tags_document_and_appends_hub() -> None:
    payload = build_graph_payload(
        DOC_NODES,
        [],
        limit=10,
        dataset_map={"doc-1": ["seat:alice"]},
    )

    doc = next(node for node in payload["nodes"] if node["id"] == "doc-1")
    assert doc["dataset"] == "seat:alice"
    assert doc["datasets"] == ["seat:alice"]
    hub = next(node for node in payload["nodes"] if node["id"] == "dataset:seat:alice")
    assert hub == {
        "id": "dataset:seat:alice",
        "label": "seat:alice",
        "type": "dataset",
        "dataset": "seat:alice",
    }
    assert {
        "source": "doc-1",
        "target": "dataset:seat:alice",
        "relationship": "belongs_to",
    } in payload["edges"]
    # Hubs are synthetic: raw-count semantics unchanged.
    assert payload["total_nodes"] == 2
    assert payload["truncated"] is False


def test_dataset_map_propagates_to_chunks_via_is_part_of() -> None:
    payload = build_graph_payload(
        DOC_NODES,
        DOC_EDGES,
        limit=10,
        dataset_map={"doc-1": ["seat:alice"]},
    )

    chunk = next(node for node in payload["nodes"] if node["id"] == "chunk-1")
    assert chunk["dataset"] == "seat:alice"
    assert chunk["datasets"] == ["seat:alice"]
    assert {
        "source": "chunk-1",
        "target": "dataset:seat:alice",
        "relationship": "belongs_to",
    } in payload["edges"]


def test_dataset_hub_survives_node_cap_without_edges_to_dropped_nodes() -> None:
    payload = build_graph_payload(
        DOC_NODES,
        DOC_EDGES,
        limit=1,
        dataset_map={"doc-1": ["seat:alice"]},
    )

    assert [node["id"] for node in payload["nodes"]] == ["doc-1", "dataset:seat:alice"]
    assert payload["edges"] == [
        {
            "source": "doc-1",
            "target": "dataset:seat:alice",
            "relationship": "belongs_to",
        }
    ]
    assert all(
        "chunk-1" not in (edge["source"], edge["target"]) for edge in payload["edges"]
    )
    assert payload["truncated"] is True
    assert payload["total_nodes"] == 2


def test_two_datasets_on_one_document_yield_two_hubs_and_edges() -> None:
    payload = build_graph_payload(
        [("doc-1", {"name": "Mirrored", "type": "TextDocument"})],
        [],
        limit=10,
        dataset_map={"doc-1": ["seat:alice", "seat:bob"]},
    )

    doc = next(node for node in payload["nodes"] if node["id"] == "doc-1")
    assert doc["dataset"] == "seat:alice"
    assert doc["datasets"] == ["seat:alice", "seat:bob"]
    hub_ids = [node["id"] for node in payload["nodes"] if node["type"] == "dataset"]
    assert hub_ids == ["dataset:seat:alice", "dataset:seat:bob"]
    belongs = [edge for edge in payload["edges"] if edge["relationship"] == "belongs_to"]
    assert belongs == [
        {"source": "doc-1", "target": "dataset:seat:alice", "relationship": "belongs_to"},
        {"source": "doc-1", "target": "dataset:seat:bob", "relationship": "belongs_to"},
    ]


async def test_graph_attributes_datasets_through_gateway() -> None:
    mesh = KnowledgeMesh(
        FakeDatasetGateway(
            DOC_NODES, DOC_EDGES, dataset_map={"doc-1": ["seat:alice"]}
        )
    )

    graph = await mesh.graph()

    assert graph["ok"] is True
    doc = next(node for node in graph["nodes"] if node["id"] == "doc-1")
    assert doc["dataset"] == "seat:alice"
    assert any(node["id"] == "dataset:seat:alice" for node in graph["nodes"])


async def test_graph_dataset_map_failure_degrades_to_plain_graph() -> None:
    mesh = KnowledgeMesh(
        FakeDatasetGateway(DOC_NODES, DOC_EDGES, map_error=RuntimeError("db offline"))
    )

    graph = await mesh.graph()

    assert graph["ok"] is True
    assert graph["fallback"] is False
    assert all("dataset" not in node for node in graph["nodes"])
    assert all(node["type"] != "dataset" for node in graph["nodes"])


async def test_graph_dataset_visible_filters_hidden_datasets_before_shaping() -> None:
    # Privacy: seat datasets are default-deny private memory. Names the caller
    # may not read are dropped before shaping — no node tag, no hub, no
    # belongs_to edge — so a plain reader cannot enumerate seat attribution.
    mesh = KnowledgeMesh(
        FakeDatasetGateway(
            DOC_NODES,
            DOC_EDGES,
            dataset_map={"doc-1": ["seat:alice", "masumi-network"]},
        )
    )

    graph = await mesh.graph(dataset_visible=lambda name: name == "masumi-network")

    doc = next(node for node in graph["nodes"] if node["id"] == "doc-1")
    assert doc["dataset"] == "masumi-network"
    assert doc["datasets"] == ["masumi-network"]
    hub_ids = [node["id"] for node in graph["nodes"] if node["type"] == "dataset"]
    assert hub_ids == ["dataset:masumi-network"]
    assert all("seat:alice" not in str(edge.values()) for edge in graph["edges"])
    assert all("seat:alice" not in str(node.values()) for node in graph["nodes"])
