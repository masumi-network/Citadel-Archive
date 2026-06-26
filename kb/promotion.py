"""ADR-0005 step 2: selective promotion of seat-node content to Central.

A :class:`PromotionEngine` enumerates a personal seat node's content, decides
per item whether it is org-relevant and non-sensitive, and (when not a dry run)
promotes the qualifying items into the curated Central vault by reusing the
existing org-ready dual-write path. Every gate is conservative: an item is only
promoted when it is secret-clean AND classified relevant AND not sensitive AND
scores at/above the configured threshold. On ANY uncertainty — a blocked secret
scan, an LLM failure, unparseable output, or a missing field — the item is
SKIPPED. Promotion never happens on uncertainty.

``dry_run`` defaults to ``True``: the engine proposes promotions and writes
nothing. A human flips ``dry_run=False`` to actually promote.

The module mirrors the best-effort, no-raise style of :mod:`kb.llm_enrichment`:
classification failures degrade to a safe SKIP rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from kb.access import AccessIdentity, AccessStore, is_seat_dataset
from kb.config import CitadelConfig
from kb.learning import LearningProcess
from kb.llm_enrichment import (
    default_llm_model,
    openrouter_chat,
    parse_json_payload,
    redacted_preview,
)
from kb.security_scan import SecurityScanEntry, scan_text_entries
from kb.service import Citadel

logger = logging.getLogger(__name__)

PROMOTION_TAG = "org-ready"

# Broad seed queries used to enumerate a seat node. cognee.recall is semantic,
# not an exhaustive listing, so a few complementary seeds widen coverage; the
# results are deduped and capped. This is best-effort top-N by design.
DEFAULT_SEED_QUERIES: tuple[str, ...] = (
    "notable knowledge, decisions, facts, and information",
    "project work, technical notes, and learnings",
)

CLASSIFIER_SYSTEM_PROMPT = (
    "You triage one piece of a person's private notes for promotion into a "
    "shared organization knowledge vault. Decide whether the content is "
    "organization-relevant (useful to teammates, about the company's projects, "
    "products, or shared work) and whether it is sensitive (personal, private, "
    "secret, credentials, financial, health, or otherwise unsafe to share "
    "org-wide). Return ONLY a JSON object shaped as "
    '{"relevant": true|false, "sensitive": true|false, "score": 0.0, '
    '"reason": "..."} where score is your 0..1 confidence that the content is '
    "both relevant AND safe to promote. Never include the original text or any "
    "secret in the reason."
)

CLASSIFIER_MAX_INPUT_CHARS = 6000


@dataclass(frozen=True)
class Classification:
    """A strict, validated classifier verdict for one candidate."""

    relevant: bool
    sensitive: bool
    score: float
    reason: str


@dataclass(frozen=True)
class ProposedPromotion:
    """One candidate plus the promote/skip decision and why."""

    candidate: str
    decision: str  # "promote" | "skip"
    reason: str
    relevant: bool | None = None
    sensitive: bool | None = None
    score: float | None = None
    secret_blocked: bool = False
    promoted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "relevant": self.relevant,
            "sensitive": self.sensitive,
            "score": self.score,
            "secret_blocked": self.secret_blocked,
            "promoted": self.promoted,
            "preview": redacted_preview(self.candidate),
        }


def _candidate_text(result: Any) -> str:
    """Extract real node text using the same field priority as search dedup.

    Mirrors :func:`kb.server.search_result_dedup_key` so promotion reads the
    same body text the rest of the system treats as a node's content.
    """
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        for key in ("text", "content", "chunk", "body", "summary", "title"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _coerce_classification(parsed: Any) -> Classification | None:
    """Strictly validate the classifier JSON. Any deviation -> None (skip)."""
    if not isinstance(parsed, dict):
        return None
    relevant = parsed.get("relevant")
    sensitive = parsed.get("sensitive")
    score = parsed.get("score")
    reason = parsed.get("reason")
    if not isinstance(relevant, bool) or not isinstance(sensitive, bool):
        return None
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    score_value = float(score)
    if not 0.0 <= score_value <= 1.0:
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    return Classification(
        relevant=relevant,
        sensitive=sensitive,
        score=score_value,
        reason=reason.strip()[:300],
    )


class PromotionEngine:
    """Selective seat-to-Central promotion (ADR-0005 step 2)."""

    def __init__(
        self,
        citadel: Citadel,
        learning: LearningProcess,
        access_store: AccessStore,
        config: CitadelConfig,
    ) -> None:
        self.citadel = citadel
        self.learning = learning
        self.access_store = access_store
        self.config = config

    async def enumerate(self, seat_dataset: str, max_items: int) -> list[str]:
        """Best-effort list of a seat node's promotable text, capped at ``max_items``.

        Uses :meth:`Citadel.search` (cognee.recall) per seed query because that is
        the only primitive that returns real node body text. recall is semantic,
        not exhaustive, so this under-samples large nodes by design — documented as
        a known limitation (ADR-0005 open risk).
        """
        cap = max(1, max_items)
        seen: set[str] = set()
        candidates: list[str] = []
        for query in DEFAULT_SEED_QUERIES:
            if len(candidates) >= cap:
                break
            try:
                results = await self.citadel.search(
                    query, dataset=seat_dataset, top_k=cap
                )
            except Exception as exc:  # pragma: no cover - depends on Cognee runtime.
                logger.warning(
                    "promotion.enumerate search failed for %s: %s",
                    seat_dataset,
                    exc.__class__.__name__,
                )
                continue
            for result in results:
                text = _candidate_text(result)
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(text)
                if len(candidates) >= cap:
                    break
        return candidates[:cap]

    def classify(self, text: str) -> Classification | None:
        """Classify one candidate via the OpenRouter direct-HTTP helper.

        Returns ``None`` on ANY failure (missing key, HTTP/URL/timeout error,
        unparseable output, or a missing/malformed field) so the caller can
        deterministically SKIP. Never raises.
        """
        try:
            content = openrouter_chat(
                [
                    {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": text[:CLASSIFIER_MAX_INPUT_CHARS]},
                ],
                model=default_llm_model(),
                operation="promotion.classify",
                max_tokens=300,
            )
        except Exception as exc:  # pragma: no cover - openrouter_chat is itself guarded.
            logger.warning(
                "promotion.classify call raised %s; skipping candidate",
                exc.__class__.__name__,
            )
            return None
        if content is None:
            return None
        return _coerce_classification(parse_json_payload(content))

    def _secret_blocked(self, seat_dataset: str, text: str) -> bool:
        """True when the candidate trips the blocking-severity secret scanner."""
        try:
            scan = scan_text_entries(
                [
                    SecurityScanEntry(
                        source="promotion", location=seat_dataset, text=text
                    )
                ],
                block_severity=self.config.content_scan_block_severity,
            )
        except Exception:  # pragma: no cover - scan is best-effort; fail closed.
            return True
        return bool(scan.get("blocked"))

    def decide(self, seat_dataset: str, candidate: str) -> ProposedPromotion:
        """Apply secret scan, then the LLM classifier + threshold. Default SKIP."""
        if self._secret_blocked(seat_dataset, candidate):
            return ProposedPromotion(
                candidate=candidate,
                decision="skip",
                reason="secret_content",
                secret_blocked=True,
            )
        verdict = self.classify(candidate)
        if verdict is None:
            # LLM unavailable or output unusable -> never promote on uncertainty.
            return ProposedPromotion(
                candidate=candidate,
                decision="skip",
                reason="llm_unavailable",
            )
        threshold = self.config.promotion_relevance_threshold
        qualifies = (
            verdict.relevant
            and not verdict.sensitive
            and verdict.score >= threshold
        )
        if qualifies:
            decision, reason = "promote", verdict.reason
        else:
            decision = "skip"
            if verdict.sensitive:
                reason = "sensitive"
            elif not verdict.relevant:
                reason = "not_relevant"
            else:
                reason = "below_threshold"
        return ProposedPromotion(
            candidate=candidate,
            decision=decision,
            reason=reason,
            relevant=verdict.relevant,
            sensitive=verdict.sensitive,
            score=verdict.score,
        )

    def _promotion_identity(self, seat_dataset: str) -> AccessIdentity:
        """Synthetic admin/env identity whose default node IS the seat.

        ``resolve_write_targets`` only fires the seat-light + Central-full
        dual-write when ``identity.default_dataset`` is the seat node (the
        ``is_promotion`` branch). An ``env`` source + ``admin`` role bypasses the
        dataset allowlist so the engine can write both targets.
        """
        return AccessIdentity(
            role="admin",
            actor_id="promotion-engine",
            actor_kind="service_account",
            actor_name="promotion-engine",
            source="env",
            default_dataset=seat_dataset,
        )

    async def _promote(
        self,
        seat_dataset: str,
        identity: AccessIdentity,
        proposal: ProposedPromotion,
    ) -> bool:
        """Promote one qualifying item via the org-ready dual-write path.

        Reuses ``resolve_write_targets`` (is_promotion -> [seat light, Central
        full]) + ``execute_learning_writes`` so the ADR-0005 step-1 secret gate
        re-runs inside ``learning.learn``. Records one audit event per promotion.
        On a secret block at write time the item is recorded as skipped, not
        promoted. Never raises out of the run loop.
        """
        # Imported lazily to avoid a circular import (server imports promotion).
        from kb.security_scan import SecretContentError
        from kb.server import execute_learning_writes, resolve_write_targets

        central = None
        try:
            targets = resolve_write_targets(
                identity, None, [PROMOTION_TAG], self.config
            )
            central = next(
                (t.dataset for t in targets if t.tier == "full"),
                targets[-1].dataset,
            )
            await execute_learning_writes(
                self.learning,
                data=proposal.candidate,
                targets=targets,
                tags=[PROMOTION_TAG],
                session_id=None,
                operation="promotion",
            )
        except SecretContentError as exc:
            self.access_store.record_event(
                action="promotion.promote",
                actor=identity,
                success=False,
                dataset=central or seat_dataset,
                detail={
                    "seat": seat_dataset,
                    "blocked": "secret_content",
                    "highest_severity": exc.highest_severity,
                    "accepted": False,
                    "score": proposal.score,
                    "relevant": proposal.relevant,
                    "sensitive": proposal.sensitive,
                    "reason": proposal.reason,
                },
            )
            return False
        except Exception as exc:  # pragma: no cover - depends on Cognee runtime.
            self.access_store.record_event(
                action="promotion.promote",
                actor=identity,
                success=False,
                dataset=central or seat_dataset,
                detail={
                    "seat": seat_dataset,
                    "error_type": exc.__class__.__name__,
                    "accepted": False,
                    "reason": proposal.reason,
                },
            )
            return False

        self.access_store.record_event(
            action="promotion.promote",
            actor=identity,
            success=True,
            dataset=central,
            detail={
                "seat": seat_dataset,
                "score": proposal.score,
                "relevant": proposal.relevant,
                "sensitive": proposal.sensitive,
                "reason": proposal.reason,
                "accepted": True,
                "tags": [PROMOTION_TAG],
            },
        )
        return True

    async def run(
        self,
        seat_dataset: str,
        *,
        dry_run: bool = True,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        """Enumerate, decide, and (when ``dry_run=False``) promote.

        ``dry_run`` defaults to ``True``: returns the proposed promotions and
        writes NOTHING. ``dry_run=False`` actually promotes qualifying items via
        the org-ready dual-write and records one audit event each. Gated on
        ``config.promotion_enabled`` (opt-in): when disabled, returns a disabled
        status and does nothing.
        """
        if not self.config.promotion_enabled:
            return {
                "ok": True,
                "enabled": False,
                "dry_run": dry_run,
                "dataset": seat_dataset,
                "reason": "disabled",
                "candidates": 0,
                "promoted": 0,
                "proposals": [],
            }
        if not is_seat_dataset(seat_dataset):
            raise ValueError(f"Not a seat dataset: {seat_dataset}")

        cap = max_items if max_items and max_items > 0 else self.config.promotion_max_items
        candidates = await self.enumerate(seat_dataset, cap)
        proposals = [self.decide(seat_dataset, text) for text in candidates]

        promoted = 0
        if not dry_run:
            identity = self._promotion_identity(seat_dataset)
            settled: list[ProposedPromotion] = []
            for proposal in proposals:
                if proposal.decision != "promote":
                    settled.append(proposal)
                    continue
                ok = await self._promote(seat_dataset, identity, proposal)
                if ok:
                    promoted += 1
                    settled.append(
                        ProposedPromotion(
                            candidate=proposal.candidate,
                            decision="promote",
                            reason=proposal.reason,
                            relevant=proposal.relevant,
                            sensitive=proposal.sensitive,
                            score=proposal.score,
                            promoted=True,
                        )
                    )
                else:
                    settled.append(
                        ProposedPromotion(
                            candidate=proposal.candidate,
                            decision="skip",
                            reason="write_blocked",
                            relevant=proposal.relevant,
                            sensitive=proposal.sensitive,
                            score=proposal.score,
                            secret_blocked=True,
                        )
                    )
            proposals = settled

        return {
            "ok": True,
            "enabled": True,
            "dry_run": dry_run,
            "dataset": seat_dataset,
            "max_items": cap,
            "candidates": len(candidates),
            "proposed": sum(1 for p in proposals if p.decision == "promote"),
            "promoted": promoted,
            "proposals": [p.to_dict() for p in proposals],
        }

    def status(self) -> dict[str, Any]:
        """Read-only config/status snapshot for the GET endpoint."""
        return {
            "enabled": self.config.promotion_enabled,
            "relevance_threshold": self.config.promotion_relevance_threshold,
            "max_items": self.config.promotion_max_items,
            "dry_run_default": True,
            "promotion_tag": PROMOTION_TAG,
        }
