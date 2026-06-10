"""The Learning Process: governed transformation of Source Material into
Structured Knowledge.

Per CONTEXT.md and docs/architecture-deepening-opportunities.md (item 1), this
module owns the workflow that callers previously wired by hand: pre-ingest
filtering and structured ingestion (delegated to :class:`kb.service.Citadel`),
Knowledge Mesh projection recording, ingest-time Knowledge Conflict detection,
and the optional Cognee improvement step. Server routes, GitHub sync, and
Obsidian sync feed it source material instead of repeating the orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from kb.conflicts import KnowledgeConflictStore, detect_contribution_conflict
from kb.mesh import MeshState
from kb.models import IngestResult
from kb.service import Citadel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LearningOutcome:
    """What one Learning Process pass produced."""

    ingest: IngestResult
    dataset: str
    improve: Any | None = None
    conflict: dict[str, Any] | None = None

    @property
    def improved(self) -> bool:
        if not self.improve:
            return False
        return not (isinstance(self.improve, dict) and self.improve.get("ok") is False)

    @property
    def improve_error(self) -> str | None:
        if isinstance(self.improve, dict) and self.improve.get("ok") is False:
            return self.improve.get("error")
        return None


class LearningProcess:
    """One entry point from accepted Source Material to vault memory."""

    def __init__(
        self,
        citadel: Citadel,
        *,
        mesh: MeshState | None = None,
        conflicts: KnowledgeConflictStore | None = None,
    ) -> None:
        self.citadel = citadel
        self.config = citadel.config
        self.mesh = mesh
        self.conflicts = conflicts

    async def learn(
        self,
        data: str,
        *,
        dataset: str | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        operation: str = "ingest",
        run_improve: bool = False,
        detect_conflicts: bool = True,
    ) -> LearningOutcome:
        """Filter, ingest, record mesh activity, detect conflicts, and
        optionally run improvement for one piece of Source Material.

        On ingest failure the error is recorded to the mesh projection (when
        attached) and re-raised for the caller to translate.
        """
        target_dataset = dataset or self.config.default_dataset
        try:
            result = await self.citadel.ingest(
                data,
                dataset=dataset,
                tags=tags or [],
                session_id=session_id,
            )
        except Exception as exc:
            if self.mesh:
                await self.mesh.record_error(
                    self.config, operation=operation, error=str(exc)
                )
            raise

        if self.mesh:
            await self.mesh.record_ingest(
                self.config,
                result,
                data=data,
                dataset=target_dataset,
                tags=list(tags or []),
            )

        conflict = None
        if detect_conflicts and result.accepted:
            conflict = self._detect_conflict(data)
            if conflict and self.mesh:
                await self.mesh.record_conflict(self.config, conflict=conflict)

        improve_result = None
        if run_improve and result.accepted:
            improve_result = await self._improve(
                dataset=target_dataset,
                session_ids=[session_id] if session_id else None,
            )

        return LearningOutcome(
            ingest=result,
            dataset=target_dataset,
            improve=improve_result,
            conflict=conflict,
        )

    async def record_failure(self, *, operation: str, error: str) -> None:
        """Record a learning-related failure on the mesh projection."""
        if self.mesh:
            await self.mesh.record_error(self.config, operation=operation, error=error)

    def _detect_conflict(self, data: str) -> dict[str, Any] | None:
        if not self.conflicts:
            return None
        try:
            candidate = detect_contribution_conflict(data, config=self.config)
        except Exception as exc:  # pragma: no cover - defensive; detection is best-effort.
            logger.warning(
                "Knowledge conflict detection failed with %s; continuing",
                exc.__class__.__name__,
            )
            return None
        if not candidate:
            return None
        return self.conflicts.record(candidate)

    async def _improve(
        self,
        *,
        dataset: str,
        session_ids: list[str] | None,
    ) -> Any:
        try:
            return await self.citadel.improve(dataset=dataset, session_ids=session_ids)
        except Exception as exc:
            logger.warning(
                "Learning process improve step failed with %s; continuing without improve",
                exc.__class__.__name__,
            )
            return {"ok": False, "error": str(exc)}
