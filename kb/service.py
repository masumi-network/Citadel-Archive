from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
import logging
from uuid import uuid4
from typing import Any

from kb.cognee_client import CogneeGateway, CogneePublicClient
from kb.config import CitadelConfig
from kb.filters import PreIngestFilter
from kb.models import FeedbackRequest, FeedbackResult, IngestResult
from kb.source_search import search_github_sync_state
from kb.tags import merge_tags

logger = logging.getLogger(__name__)


class Citadel:
    def __init__(
        self,
        config: CitadelConfig | None = None,
        *,
        cognee: CogneeGateway | None = None,
    ) -> None:
        self.config = config or CitadelConfig.from_env()
        self.cognee = cognee or CogneePublicClient()
        self.filter = PreIngestFilter(
            min_chars=self.config.min_chars,
            exclude_patterns=self.config.exclude_patterns,
        )
        self._seen_hashes: set[str] = set()

    def _default_session_for_dataset(self, dataset: str) -> str:
        if dataset == self.config.github_sync_dataset:
            return self.config.github_sync_session
        return self.config.default_session

    @classmethod
    def from_env(cls) -> "Citadel":
        return cls(CitadelConfig.from_env())

    async def ingest(
        self,
        data: str,
        *,
        dataset: str | None = None,
        tags: Iterable[str] | None = None,
        session_id: str | None = None,
    ) -> IngestResult:
        target_dataset = dataset or self.config.default_dataset
        merged_tags = merge_tags(self.config.default_tags, tags)
        decision = self.filter.check(data)
        if not decision.accepted:
            logger.info(
                "Ingest rejected for dataset %s: %s", target_dataset, decision.reason
            )
            return IngestResult(False, decision.reason, target_dataset, merged_tags)

        content_hash = sha256(data.encode("utf-8")).hexdigest()
        if content_hash in self._seen_hashes:
            logger.info(
                "Ingest rejected for dataset %s: duplicate_in_process", target_dataset
            )
            return IngestResult(False, "duplicate_in_process", target_dataset, merged_tags)
        self._seen_hashes.add(content_hash)

        result = await self.cognee.remember(
            data,
            dataset_name=target_dataset,
            session_id=session_id,
            tags=merged_tags,
        )
        return IngestResult(True, "accepted", target_dataset, merged_tags, result)

    async def search(
        self,
        query: str,
        *,
        dataset: str | None = None,
        session_id: str | None = None,
        top_k: int = 10,
    ) -> list[Any]:
        target_dataset = dataset or self.config.default_dataset
        results = await self.cognee.recall(
            query,
            dataset=target_dataset,
            session_id=session_id or self._default_session_for_dataset(target_dataset),
            top_k=top_k,
        )
        if results or target_dataset != self.config.github_sync_dataset:
            return results
        return search_github_sync_state(query, self.config, top_k=top_k)

    async def feedback(self, request: FeedbackRequest) -> FeedbackResult:
        session_id = request.session_id or self.config.default_session
        dataset = request.dataset or self.config.default_dataset
        recorded = await self.cognee.add_feedback(
            session_id=session_id,
            qa_id=request.qa_id,
            score=request.score,
            text=request.text,
        )
        improved = False
        if recorded and self.config.auto_improve:
            await self.cognee.improve(
                dataset=dataset,
                session_ids=[session_id],
                build_global_context_index=self.config.build_global_context_index,
            )
            improved = True
        return FeedbackResult(recorded=recorded, improved=improved)

    async def improve(
        self,
        *,
        dataset: str | None = None,
        session_ids: list[str] | None = None,
    ) -> Any:
        return await self.cognee.improve(
            dataset=dataset or self.config.default_dataset,
            session_ids=session_ids,
            build_global_context_index=self.config.build_global_context_index,
        )

    async def _graph_counts(self) -> dict[str, int]:
        nodes, edges = await self.cognee.graph_data()
        return {"nodes": len(nodes), "edges": len(edges)}

    async def cognify_dataset(
        self,
        *,
        dataset: str | None = None,
        verify: bool = False,
    ) -> dict[str, Any]:
        """Cognify already-added data in ``dataset`` and report graph growth.

        This recovers data that was added but never cognified. ``cognee.cognify``
        only processes uncognified data (incremental by default), so re-running is
        safe and idempotent. ``verify=True`` is a superset: it runs the same
        recovery cognify and *also* ingests a unique marker, cognifies it, and
        searches for it — an end-to-end health check that ingest + cognify fills
        the graph. The marker is cognified explicitly because the modern Cognee
        ``remember`` path does not cognify inline.
        """
        target_dataset = dataset or self.config.default_dataset
        before = await self._graph_counts()

        # Recovery: cognify already-added-but-uncognified data for the dataset.
        await self.cognee.cognify(datasets=[target_dataset])

        verification: dict[str, Any] | None = None
        if verify:
            marker = f"COGNIFY_TEST_MARKER_{uuid4().hex}"
            await self.ingest(marker, dataset=target_dataset)
            await self.cognee.cognify(datasets=[target_dataset])
            matches = await self.search(marker, dataset=target_dataset, top_k=10)
            verification = {
                "marker": marker,
                "search_hit": _marker_in_results(marker, matches),
            }

        after = await self._graph_counts()
        graph_grew = (
            after["nodes"] > before["nodes"] or after["edges"] > before["edges"]
        )
        if verification is not None:
            verification["graph_grew"] = graph_grew
            verification["ok"] = bool(verification["search_hit"] or graph_grew)

        return {
            "ok": True,
            "dataset": target_dataset,
            "graph_before": before,
            "graph_after": after,
            "graph_grew": graph_grew,
            "verify": verify,
            "verification": verification,
        }


def _marker_in_results(marker: str, results: list[Any]) -> bool:
    for item in results:
        if marker in str(item):
            return True
    return False
