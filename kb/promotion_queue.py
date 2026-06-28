"""ADR-0007 P6: pending promotion approval queue stored in the access JSON."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any
from uuid import uuid4

from kb.llm_enrichment import redacted_preview
from kb.promotion_refs import ReferenceAssessment

PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
REJECTED_STATUS = "rejected"
VALID_PENDING_STATUSES = frozenset({PENDING_STATUS, APPROVED_STATUS, REJECTED_STATUS})


@dataclass(frozen=True)
class PromotionPendingItem:
    id: str
    seat_slug: str
    seat_dataset: str
    candidate_text: str
    candidate_hash: str
    preview: str
    reference_status: str
    reference_reason: str
    repo_hints: tuple[str, ...] = ()
    status: str = PENDING_STATUS
    created_at: str = ""
    decided_at: str | None = None
    decided_by: str | None = None
    decided_by_name: str | None = None
    delegate: bool = False
    score: float | None = None
    relevant: bool | None = None
    sensitive: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["repo_hints"] = list(self.repo_hints)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromotionPendingItem":
        status = data.get("status") or PENDING_STATUS
        if status not in VALID_PENDING_STATUSES:
            raise ValueError(f"Unsupported promotion pending status: {status}")
        return cls(
            id=str(data["id"]),
            seat_slug=str(data["seat_slug"]),
            seat_dataset=str(data["seat_dataset"]),
            candidate_text=str(data["candidate_text"]),
            candidate_hash=str(data["candidate_hash"]),
            preview=str(data.get("preview") or ""),
            reference_status=str(data.get("reference_status") or ""),
            reference_reason=str(data.get("reference_reason") or ""),
            repo_hints=tuple(data.get("repo_hints") or ()),
            status=status,
            created_at=str(data.get("created_at") or ""),
            decided_at=data.get("decided_at"),
            decided_by=data.get("decided_by"),
            decided_by_name=data.get("decided_by_name"),
            delegate=bool(data.get("delegate")),
            score=data.get("score"),
            relevant=data.get("relevant"),
            sensitive=data.get("sensitive"),
        )


def candidate_hash(text: str) -> str:
    normalized = text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def build_pending_item(
    *,
    seat_slug: str,
    seat_dataset: str,
    candidate_text: str,
    assessment: ReferenceAssessment,
    created_at: str,
    score: float | None = None,
    relevant: bool | None = None,
    sensitive: bool | None = None,
) -> PromotionPendingItem:
    return PromotionPendingItem(
        id=f"promo_{uuid4().hex}",
        seat_slug=seat_slug,
        seat_dataset=seat_dataset,
        candidate_text=candidate_text,
        candidate_hash=candidate_hash(candidate_text),
        preview=redacted_preview(candidate_text),
        reference_status=assessment.status,
        reference_reason=assessment.reason,
        repo_hints=assessment.repo_hints,
        created_at=created_at,
        score=score,
        relevant=relevant,
        sensitive=sensitive,
    )
