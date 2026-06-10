"""Knowledge Mesh: the real Cognee-backed relationship graph.

This is intentionally separate from :class:`kb.mesh.MeshState`, which is a
wrapper-level dashboard projection of runtime activity. The Knowledge Mesh
exposes what the Organization Vault actually knows: nodes and relationships
read from Cognee's graph engine (Kuzu in the v1 deployment).

The endpoint contract never fails hard: when Cognee has no data, the graph
engine is unavailable, or the gateway does not expose graph access, callers
receive an empty graph with ``fallback: true`` instead of an error.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_NODES = 200

_LABEL_KEYS = ("name", "label", "title", "text", "id")
_TYPE_KEYS = ("type", "node_type", "entity_type", "category")


def _node_label(node_id: str, properties: dict[str, Any]) -> str:
    for key in _LABEL_KEYS:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:120]
    return str(node_id)[:120]


def _node_type(properties: dict[str, Any]) -> str:
    for key in _TYPE_KEYS:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return "node"


def build_graph_payload(
    raw_nodes: list[Any],
    raw_edges: list[Any],
    *,
    limit: int = DEFAULT_MAX_NODES,
) -> dict[str, Any]:
    """Shape raw Cognee graph tuples into the ``{nodes, edges}`` contract.

    Nodes are ``(node_id, properties)`` tuples; edges are
    ``(source_id, target_id, relationship_name, properties)`` tuples. The node
    list is capped at ``limit`` and edges are kept only when both endpoints
    survive the cap.
    """
    limit = max(1, limit)
    nodes: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    for raw in raw_nodes:
        try:
            node_id, properties = raw[0], raw[1]
        except (TypeError, IndexError, KeyError):
            continue
        if not isinstance(properties, dict):
            properties = {}
        node_key = str(node_id)
        if node_key in kept_ids:
            continue
        kept_ids.add(node_key)
        nodes.append(
            {
                "id": node_key,
                "label": _node_label(node_key, properties),
                "type": _node_type(properties),
            }
        )
        if len(nodes) >= limit:
            break

    edges: list[dict[str, Any]] = []
    for raw in raw_edges:
        try:
            source, target, relationship = str(raw[0]), str(raw[1]), str(raw[2])
        except (TypeError, IndexError, KeyError):
            continue
        if source not in kept_ids or target not in kept_ids:
            continue
        edges.append(
            {
                "source": source,
                "target": target,
                "relationship": relationship or "related",
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(raw_nodes),
        "total_edges": len(raw_edges),
        "truncated": len(raw_nodes) > len(nodes),
    }


def fallback_graph(reason: str) -> dict[str, Any]:
    return {
        "ok": True,
        "nodes": [],
        "edges": [],
        "total_nodes": 0,
        "total_edges": 0,
        "truncated": False,
        "fallback": True,
        "fallback_reason": reason,
    }


class KnowledgeMesh:
    """Reads the real knowledge graph through a Cognee gateway."""

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    async def graph(self, *, limit: int = DEFAULT_MAX_NODES) -> dict[str, Any]:
        graph_data = getattr(self.gateway, "graph_data", None)
        if not callable(graph_data):
            return fallback_graph("graph_access_unavailable")
        try:
            raw_nodes, raw_edges = await graph_data()
        except Exception as exc:
            logger.warning(
                "Knowledge mesh graph read failed with %s; returning fallback graph",
                exc.__class__.__name__,
            )
            return fallback_graph(f"graph_engine_error:{exc.__class__.__name__}")
        if not raw_nodes:
            return fallback_graph("graph_empty")
        payload = build_graph_payload(list(raw_nodes), list(raw_edges), limit=limit)
        return {"ok": True, "fallback": False, **payload}
