from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha1
import logging
from typing import Any

from kb.config import CitadelConfig
from kb.models import FeedbackResult, IngestResult
from kb.security_scan import redact_secrets

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def stable_id(prefix: str, value: str) -> str:
    digest = sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


@dataclass
class MeshState:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=160))
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    revision: int = 0
    documents: int = 0
    searches: int = 0
    feedback_items: int = 0
    upgrades: int = 0
    errors: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    async def snapshot(self, config: CitadelConfig) -> dict[str, Any]:
        async with self._lock:
            self._ensure_base_graph(config)
            indexes = self._indexes(config)
            return {
                "revision": self.revision,
                "generated_at": utc_now(),
                "tenant_id": config.tenant_id,
                "default_dataset": config.default_dataset,
                "stats": {
                    "nodes": len(self.nodes),
                    "edges": len(self.edges),
                    "documents": self.documents,
                    "searches": self.searches,
                    "feedback": self.feedback_items,
                    "upgrades": self.upgrades,
                    "errors": self.errors,
                },
                "indexes": indexes,
                "nodes": list(self.nodes.values()),
                "edges": list(self.edges.values()),
                "events": list(self.events),
            }

    async def record_ingest(
        self,
        config: CitadelConfig,
        result: IngestResult,
        *,
        data: str,
        dataset: str,
        tags: list[str],
    ) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            dataset_id = self._dataset_node(dataset)
            if result.accepted:
                document_id = stable_id("document", f"{dataset}:{data}")
                label = data.strip().splitlines()[0][:80] or "Untitled memory"
                self.nodes[document_id] = {
                    "id": document_id,
                    "label": label,
                    "type": "document",
                    "status": "indexed",
                    "size": min(20 + len(data) // 40, 64),
                    "metadata": {
                        "dataset": dataset,
                        "tags": list(result.tags),
                        "characters": len(data),
                    },
                }
                self._edge(dataset_id, document_id, "contains")
                for tag in result.tags or tuple(tags):
                    tag_id = self._tag_node(tag)
                    self._edge(document_id, tag_id, "tagged")
                self._edge(document_id, "index:vector", "embedded")
                self._edge(document_id, "index:graph", "linked")
                self.documents += 1
                await self._record_event(
                    "ingest",
                    "Memory indexed",
                    {"dataset": dataset, "reason": result.reason, "tags": list(result.tags)},
                )
            else:
                await self._record_event(
                    "reject",
                    "Memory rejected",
                    {"dataset": dataset, "reason": result.reason},
                )

    async def record_search(
        self,
        config: CitadelConfig,
        *,
        query: str,
        dataset: str,
        result_count: int,
    ) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            query_id = stable_id("query", f"{dataset}:{query}:{self.searches}")
            self.nodes[query_id] = {
                "id": query_id,
                "label": query[:80],
                "type": "query",
                "status": "complete",
                "size": 24,
                "metadata": {"dataset": dataset, "results": result_count},
            }
            self._edge(query_id, self._dataset_node(dataset), "searched")
            self._edge(query_id, "index:vector", "retrieved")
            self._edge(query_id, "index:graph", "traversed")
            self.searches += 1
            await self._record_event(
                "search",
                "Search completed",
                {"dataset": dataset, "results": result_count},
            )

    async def record_feedback(
        self,
        config: CitadelConfig,
        *,
        qa_id: str,
        dataset: str,
        result: FeedbackResult,
    ) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            feedback_id = stable_id("feedback", f"{dataset}:{qa_id}:{self.feedback_items}")
            self.nodes[feedback_id] = {
                "id": feedback_id,
                "label": f"Feedback {qa_id[:8]}",
                "type": "feedback",
                "status": "improved" if result.improved else "recorded",
                "size": 22,
                "metadata": {"dataset": dataset, "qa_id": qa_id, "improved": result.improved},
            }
            self._edge(feedback_id, "index:feedback", "updates")
            self._edge(feedback_id, self._dataset_node(dataset), "teaches")
            self.feedback_items += 1
            await self._record_event(
                "feedback",
                "Feedback recorded",
                {"dataset": dataset, "qa_id": qa_id, "improved": result.improved},
            )

    async def record_upgrade(
        self,
        config: CitadelConfig,
        *,
        dataset: str,
        session_ids: list[str] | None,
    ) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            upgrade_id = stable_id("upgrade", f"{dataset}:{self.upgrades}:{utc_now()}")
            self.nodes[upgrade_id] = {
                "id": upgrade_id,
                "label": "Self upgrade",
                "type": "upgrade",
                "status": "complete",
                "size": 30,
                "metadata": {"dataset": dataset, "sessions": session_ids or []},
            }
            self._edge(upgrade_id, self._dataset_node(dataset), "improves")
            self._edge(upgrade_id, "index:feedback", "reads")
            self._edge(upgrade_id, "index:global", "refreshes")
            self.upgrades += 1
            await self._record_event(
                "upgrade",
                "Self upgrade completed",
                {"dataset": dataset, "sessions": session_ids or []},
            )

    async def record_github_sync(self, config: CitadelConfig, result: dict[str, Any]) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            dataset_id = self._dataset_node(result.get("org") or config.github_sync_dataset)
            source_id = stable_id("source", result.get("source_url") or config.github_org)
            self.nodes[source_id] = {
                "id": source_id,
                "label": f"GitHub / {result.get('org') or config.github_org}",
                "type": "source",
                "status": "synced",
                "size": 46,
                "metadata": {
                    "url": result.get("source_url"),
                    "checked_at": result.get("checked_at"),
                    "repos_scanned": result.get("repos_scanned"),
                },
            }
            self._edge(source_id, dataset_id, "updates")

            for repo in result.get("changed_repositories", [])[:12]:
                repo_id = stable_id("repository", repo.get("full_name") or repo.get("name") or "")
                self.nodes[repo_id] = {
                    "id": repo_id,
                    "label": repo.get("name") or repo.get("full_name") or "Repository",
                    "type": "repository",
                    "status": "changed",
                    "size": 26,
                    "metadata": repo,
                }
                self._edge(source_id, repo_id, "observed")
                self._edge(repo_id, dataset_id, "summarized")

            await self._record_event(
                "github_sync",
                "GitHub sync completed",
                {
                    "org": result.get("org"),
                    "repos": result.get("repos_scanned"),
                    "changed": result.get("changed_count"),
                    "events": result.get("event_count"),
                    "ingested": result.get("ingested"),
                    "improved": result.get("improved"),
                },
            )

    async def record_obsidian_sync(
        self,
        config: CitadelConfig,
        *,
        vault: dict[str, Any],
        result: dict[str, Any],
        dataset: str | None = None,
    ) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            dataset_id = self._dataset_node(dataset or config.default_dataset)
            source_id = stable_id("source", f"obsidian:{vault.get('id')}")
            self.nodes[source_id] = {
                "id": source_id,
                "label": f"Obsidian / {vault.get('name') or 'Vault'}",
                "type": "source",
                "status": "conflict" if result.get("conflicts") else "synced",
                "size": 44,
                "metadata": {
                    "source_type": "obsidian_vault",
                    "vault_id": vault.get("id"),
                    "team_id": vault.get("team_id"),
                    "last_push_at": vault.get("last_push_at"),
                    "accepted": len(result.get("accepted", [])),
                    "skipped": len(result.get("skipped", [])),
                    "conflicts": len(result.get("conflicts", [])),
                },
            }
            self._edge(source_id, dataset_id, "updates")

            for document in result.get("accepted", [])[:12]:
                document_id = stable_id(
                    "document",
                    f"obsidian:{vault.get('id')}:{document.get('path')}",
                )
                self.nodes[document_id] = {
                    "id": document_id,
                    "label": document.get("path") or "Obsidian note",
                    "type": "document",
                    "status": "deleted" if document.get("deleted") else "indexed",
                    "size": 24,
                    "metadata": {
                        "source_type": "obsidian_vault",
                        "vault_id": vault.get("id"),
                        "rev": document.get("rev"),
                        "content_hash": document.get("content_hash"),
                    },
                }
                self._edge(source_id, document_id, "synced")
                self._edge(document_id, dataset_id, "indexed")

            await self._record_event(
                "obsidian_sync",
                "Obsidian vault sync received",
                {
                    "vault_id": vault.get("id"),
                    "vault_name": vault.get("name"),
                    "accepted": len(result.get("accepted", [])),
                    "skipped": len(result.get("skipped", [])),
                    "conflicts": len(result.get("conflicts", [])),
                },
            )

    async def record_enrichment(
        self,
        config: CitadelConfig,
        *,
        dataset: str,
        chunks: int,
        used_llm: bool,
        reason: str,
        model: str | None = None,
    ) -> None:
        """Surface an LLM enrichment pass (or its fallback) in the activity stream."""
        async with self._lock:
            self._ensure_base_graph(config)
            await self._record_event(
                "enrichment",
                "Source material enriched",
                {
                    "dataset": dataset,
                    "chunks": chunks,
                    "used_llm": used_llm,
                    "reason": reason,
                    "model": model,
                },
            )

    async def record_optimization(
        self,
        config: CitadelConfig,
        *,
        dataset: str,
        reviewed: int,
        optimized: int,
        used_llm: bool,
        dry_run: bool,
    ) -> None:
        """Surface a self-improvement pass in the activity stream."""
        async with self._lock:
            self._ensure_base_graph(config)
            await self._record_event(
                "optimization",
                "Self-improvement pass completed",
                {
                    "dataset": dataset,
                    "reviewed": reviewed,
                    "optimized": optimized,
                    "used_llm": used_llm,
                    "dry_run": dry_run,
                },
            )

    async def record_conflict(self, config: CitadelConfig, *, conflict: dict[str, Any]) -> None:
        """Surface a detected Knowledge Conflict in the activity stream."""
        async with self._lock:
            self._ensure_base_graph(config)
            await self._record_event(
                "conflict",
                "Knowledge conflict detected",
                {
                    "conflict_id": conflict.get("id"),
                    "kind": conflict.get("kind"),
                    "status": conflict.get("status"),
                    "summary": str(conflict.get("summary") or "")[:280],
                },
            )

    async def record_error(self, config: CitadelConfig, *, operation: str, error: str) -> None:
        async with self._lock:
            self._ensure_base_graph(config)
            self.errors += 1
            logger.error("Mesh recorded %s failure: %s", operation, redact_secrets(error[:280]))
            await self._record_event(
                "error",
                "Operation failed",
                {"operation": operation, "error": error[:280]},
            )

    def _ensure_base_graph(self, config: CitadelConfig) -> None:
        dataset_id = self._dataset_node(config.default_dataset)
        for index_id, label, description in [
            ("index:graph", "Graph mesh", "Entity and relationship store"),
            ("index:vector", "Vector index", "Embedding retrieval store"),
            ("index:feedback", "Feedback memory", "Session feedback and memify input"),
            ("index:global", "Global context", "Cross-session improvement layer"),
        ]:
            self.nodes[index_id] = {
                "id": index_id,
                "label": label,
                "type": "index",
                "status": "active",
                "size": 40,
                "metadata": {"description": description},
            }
            self._edge(dataset_id, index_id, "uses")

    def _dataset_node(self, dataset: str) -> str:
        node_id = stable_id("dataset", dataset)
        self.nodes[node_id] = {
            "id": node_id,
            "label": dataset,
            "type": "dataset",
            "status": "active",
            "size": 52,
            "metadata": {"dataset": dataset},
        }
        return node_id

    def _tag_node(self, tag: str) -> str:
        node_id = stable_id("tag", tag)
        self.nodes[node_id] = {
            "id": node_id,
            "label": tag,
            "type": "tag",
            "status": "active",
            "size": 20,
            "metadata": {"tag": tag},
        }
        return node_id

    def _edge(self, source: str, target: str, label: str) -> None:
        edge_id = f"{source}->{target}:{label}"
        self.edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "label": label,
        }

    def _indexes(self, config: CitadelConfig) -> list[dict[str, Any]]:
        return [
            {
                "id": "graph",
                "name": "Graph mesh",
                "status": "active",
                "records": len([node for node in self.nodes.values() if node["type"] != "index"]),
                "updated_at": self.events[0]["created_at"] if self.events else None,
            },
            {
                "id": "vector",
                "name": "Vector index",
                "status": "active",
                "records": self.documents,
                "updated_at": self.events[0]["created_at"] if self.events else None,
            },
            {
                "id": "feedback",
                "name": "Feedback memory",
                "status": "active",
                "records": self.feedback_items,
                "updated_at": self.events[0]["created_at"] if self.events else None,
            },
            {
                "id": "global",
                "name": "Global context",
                "status": "enabled" if config.build_global_context_index else "standby",
                "records": self.upgrades,
                "updated_at": self.events[0]["created_at"] if self.events else None,
            },
        ]

    async def _record_event(self, event_type: str, message: str, details: dict[str, Any]) -> None:
        self.revision += 1
        event = {
            "id": self.revision,
            "type": event_type,
            "message": message,
            "details": details,
            "created_at": utc_now(),
        }
        self.events.appendleft(event)
        self._publish(event)

    def _publish(self, event: dict[str, Any]) -> None:
        dead_queues: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self.subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.append(queue)
        for queue in dead_queues:
            self.unsubscribe(queue)
