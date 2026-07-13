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
from typing import Any, Callable

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
    dataset_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Shape raw Cognee graph tuples into the ``{nodes, edges}`` contract.

    Nodes are ``(node_id, properties)`` tuples; edges are
    ``(source_id, target_id, relationship_name, properties)`` tuples. The node
    list is capped at ``limit`` and edges are kept only when both endpoints
    survive the cap.

    ``dataset_map`` (``{data_id: [dataset_name, ...]}``) optionally attributes
    document nodes to their cognee datasets (per-seat ``seat:<slug>`` datasets):
    mapped nodes gain ``dataset``/``datasets`` keys, chunks inherit the dataset
    of their document via ``is_part_of`` edges, and one synthetic hub node per
    dataset (``dataset:<name>``) is appended with ``belongs_to`` edges. Hubs are
    synthetic: they do not count against ``limit`` or into ``total_nodes``.
    ``None``/``{}`` keeps the exact pre-attribution behavior.
    """
    limit = max(1, limit)
    dataset_map = dataset_map or {}
    nodes: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    node_by_id: dict[str, dict[str, Any]] = {}
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
        node: dict[str, Any] = {
            "id": node_key,
            "label": _node_label(node_key, properties),
            "type": _node_type(properties),
        }
        names = dataset_map.get(node_key)
        if names:
            node["dataset"] = names[0]
            node["datasets"] = list(names)
        nodes.append(node)
        node_by_id[node_key] = node
        if len(nodes) >= limit:
            break

    if dataset_map:
        # Chunk-level attribution: a DocumentChunk links to its document via an
        # is_part_of edge; tag kept, untagged endpoints with the mapped
        # document's dataset(s). Single pass, no recursion.
        for raw in raw_edges:
            try:
                source, target, relationship = str(raw[0]), str(raw[1]), str(raw[2])
            except (TypeError, IndexError, KeyError):
                continue
            if relationship != "is_part_of":
                continue
            for doc_id, other_id in ((source, target), (target, source)):
                names = dataset_map.get(doc_id)
                other = node_by_id.get(other_id)
                if names and other is not None and "dataset" not in other:
                    other["dataset"] = names[0]
                    other["datasets"] = list(names)

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

    # Raw-count semantics captured before synthetic hubs are appended.
    truncated = len(raw_nodes) > len(nodes)

    if dataset_map:
        # Synthesize one hub node per dataset attached to at least one KEPT
        # node, plus belongs_to edges. The "dataset:" prefix cannot collide
        # with kuzu UUID ids, so only intra-hub dedupe is needed.
        hub_names: list[str] = []
        seen_hubs: set[str] = set()
        for node in nodes:
            for name in node.get("datasets", []):
                edges.append(
                    {
                        "source": node["id"],
                        "target": f"dataset:{name}",
                        "relationship": "belongs_to",
                    }
                )
                if name not in seen_hubs:
                    seen_hubs.add(name)
                    hub_names.append(name)
        for name in hub_names:
            hub_id = f"dataset:{name}"
            kept_ids.add(hub_id)
            nodes.append(
                {"id": hub_id, "label": name, "type": "dataset", "dataset": name}
            )

    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(raw_nodes),
        "total_edges": len(raw_edges),
        "truncated": truncated,
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

    async def graph(
        self,
        *,
        limit: int = DEFAULT_MAX_NODES,
        dataset_visible: Callable[[str], bool] | None = None,
    ) -> dict[str, Any]:
        """Shaped graph payload; ``dataset_visible`` filters attribution.

        ``dataset_visible`` (dataset name -> bool) drops dataset names the
        caller may not read BEFORE shaping — no node tag, no hub, no
        belongs_to edge. Seat datasets are default-deny private memory
        (kb/server.py enforce_dataset_allowlist), so attribution must not let
        every kb:search reader durably enumerate who contributed which
        document. ``None`` applies no filtering (trusted/internal callers).
        """
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
        dataset_map: dict[str, list[str]] = {}
        node_dataset_map = getattr(self.gateway, "node_dataset_map", None)
        if callable(node_dataset_map):
            try:
                dataset_map = await node_dataset_map() or {}
            except Exception as exc:
                logger.warning(
                    "Knowledge mesh dataset map read failed with %s; "
                    "omitting dataset attribution",
                    exc.__class__.__name__,
                )
                dataset_map = {}
        if dataset_map and dataset_visible is not None:
            filtered: dict[str, list[str]] = {}
            for node_id, names in dataset_map.items():
                kept = [name for name in names if dataset_visible(name)]
                if kept:
                    filtered[node_id] = kept
            dataset_map = filtered
        payload = build_graph_payload(
            list(raw_nodes), list(raw_edges), limit=limit, dataset_map=dataset_map
        )
        return {"ok": True, "fallback": False, **payload}
