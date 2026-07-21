"""Sync local Approved Capture Roots to the Node for server-side share enforcement."""

from __future__ import annotations

from dataclasses import dataclass

from kb.capture import capture_token
from kb.capture_config import CaptureConfig, normalize_capture_root_paths
from kb.promotion_client import (
    PromotionClientError,
    get_seat_capture_roots,
    node_base_url,
    resolve_seat_slug,
    update_seat_capture_roots,
)


@dataclass(frozen=True)
class CaptureRootsSyncResult:
    ok: bool
    status: str
    detail: str
    seat_slug: str | None = None
    merged_count: int = 0


def merge_capture_root_paths(
    server_paths: tuple[str, ...] | list[str],
    local_paths: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Union server + local paths (order-preserving, normalized, deduped)."""
    return normalize_capture_root_paths((*server_paths, *local_paths))


def sync_local_capture_roots_to_server(
    config: CaptureConfig,
    *,
    base_url: str | None = None,
    token: str | None = None,
) -> CaptureRootsSyncResult:
    """Merge local roots into the seat's server-approved list (best-effort).

    Non-seat tokens and offline Nodes are skipped with a warning — local setup
    must still succeed when sync cannot run.
    """
    local_paths = tuple(root.path for root in config.roots)
    if not local_paths:
        return CaptureRootsSyncResult(
            ok=True,
            status="skipped",
            detail="no local capture roots to sync",
        )

    token = (token or capture_token()).strip()
    if not token:
        return CaptureRootsSyncResult(
            ok=True,
            status="skipped",
            detail="no seat token in environment — set CITADEL_MCP_ACCESS_TOKEN",
        )

    resolved_base = (base_url or config.node_url or node_base_url()).rstrip("/")
    try:
        seat_slug = resolve_seat_slug(resolved_base, token)
    except PromotionClientError as exc:
        return CaptureRootsSyncResult(
            ok=False,
            status="failed",
            detail=str(exc),
        )

    if not seat_slug:
        return CaptureRootsSyncResult(
            ok=True,
            status="skipped",
            detail="token is not seat-bound — server capture roots unchanged",
        )

    try:
        current = get_seat_capture_roots(seat_slug, base_url=resolved_base, token=token)
        server_paths = tuple(current.get("roots") or ())
        merged = merge_capture_root_paths(server_paths, local_paths)
        if merged == normalize_capture_root_paths(server_paths):
            return CaptureRootsSyncResult(
                ok=True,
                status="unchanged",
                detail="server already has these capture roots",
                seat_slug=seat_slug,
                merged_count=len(merged),
            )
        update_seat_capture_roots(
            seat_slug,
            list(merged),
            base_url=resolved_base,
            token=token,
        )
    except PromotionClientError as exc:
        return CaptureRootsSyncResult(
            ok=False,
            status="failed",
            detail=str(exc),
            seat_slug=seat_slug,
        )

    return CaptureRootsSyncResult(
        ok=True,
        status="synced",
        detail=f"synced {len(merged)} approved capture root(s) to Node",
        seat_slug=seat_slug,
        merged_count=len(merged),
    )


def sync_warning_message(result: CaptureRootsSyncResult) -> str | None:
    """Human-readable warning when sync failed or was skipped unexpectedly."""
    if result.status == "failed":
        seat = f" for seat {result.seat_slug}" if result.seat_slug else ""
        return f"Could not sync capture roots to Node{seat}: {result.detail}"
    if result.status == "skipped" and "no seat token" in result.detail:
        return (
            "Capture roots saved locally only — set CITADEL_MCP_ACCESS_TOKEN "
            "and re-run `citadel setup` to sync share enforcement to the Node."
        )
    return None
