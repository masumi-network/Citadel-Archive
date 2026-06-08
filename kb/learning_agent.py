from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Mapping

from kb.google_chat import GoogleChatDelivery
from kb.github_sync import GitHubOrgSyncer
from kb.notification_gateways import NotificationGateway, configured_gateways, gateway_statuses
from kb.organization_digest import build_organization_digest
from kb.service import Citadel


class LearningAgent:
    """Runs source-learning jobs that teach Citadel and refresh Cognee indexes."""

    def __init__(
        self,
        citadel: Citadel,
        *,
        github_syncer: GitHubOrgSyncer | None = None,
        google_chat: GoogleChatDelivery | None = None,
        gateways: Mapping[str, NotificationGateway] | None = None,
    ) -> None:
        self.citadel = citadel
        self.github_syncer = github_syncer or GitHubOrgSyncer(citadel)
        configured = dict(gateways) if gateways is not None else configured_gateways(citadel.config)
        if google_chat is not None:
            configured["google_chat"] = google_chat
        self.gateways = configured
        self.google_chat = configured.get("google_chat")

    @classmethod
    def from_env(cls) -> "LearningAgent":
        return cls(Citadel.from_env())

    async def status(self) -> dict[str, Any]:
        github_status = await self.github_syncer.status()
        return {
            "ok": True,
            "agent": "citadel-learning-agent",
            "mode": "github-source-learning",
            "sources": {
                "github": github_status,
            },
            "organization_digest": {
                "enabled": self.citadel.config.organization_digest_enabled,
                "window_hours": self.citadel.config.organization_digest_window_hours,
                "max_items": self.citadel.config.organization_digest_max_items,
            },
            "notifications": {
                "gateways": self._gateway_statuses(),
                "google_chat": self._gateway_status("google_chat"),
            },
            "capabilities": [
                "scan_github_repositories",
                "summarize_open_pull_requests",
                "summarize_merged_pull_requests",
                "summarize_github_events",
                "summarize_recent_commits",
                "ingest_source_digest",
                "run_cognee_improvement",
                "build_organization_update_digest",
                "post_gateway_digest",
                "post_google_chat_digest",
            ],
        }

    async def run(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
        post_to_chat: bool = False,
        include_digest_preview: bool = True,
    ) -> dict[str, Any]:
        github_result = await self.github_syncer.run(force=force, dry_run=dry_run)
        vault_context = await self._recent_vault_context()
        result = {
            "ok": True,
            "agent": "citadel-learning-agent",
            "sources": {
                "github": github_result,
                "vault": vault_context,
            },
            "ingested": github_result.get("ingested", False),
            "improved": github_result.get("improved", False),
            "dry_run": dry_run,
        }
        digest = await asyncio.to_thread(
            build_organization_digest,
            result,
            self.citadel.config,
            include_preview=include_digest_preview,
        )
        digest_text = digest.pop("_text", "")
        result["organization_digest"] = digest
        gateway_results = await self._maybe_post_gateways(
            digest,
            digest_text,
            post_to_gateways=post_to_chat,
            dry_run=dry_run,
            checked_at=github_result.get("checked_at"),
        )
        result["notifications"] = {
            "gateways": gateway_results,
            "google_chat": gateway_results.get("google_chat", {"enabled": False}),
        }
        return result

    async def _recent_vault_context(self) -> dict[str, Any]:
        config = self.citadel.config
        if not config.organization_digest_enabled:
            return {"ok": True, "dataset": None, "recent_context": [], "reason": "digest_disabled"}
        dataset = config.search_default_dataset or config.github_sync_dataset or config.default_dataset
        query = (
            "meaningful source-linked decisions ongoing work blockers features architecture "
            f"repository momentum last {config.organization_digest_window_hours} hours"
        )
        try:
            results = await self.citadel.search(query, dataset=dataset, top_k=5)
        except Exception as exc:
            return {
                "ok": False,
                "dataset": dataset,
                "recent_context": [],
                "error_type": exc.__class__.__name__,
            }
        return {
            "ok": True,
            "dataset": dataset,
            "recent_context": [
                _safe_vault_context_item(item, index) for index, item in enumerate(results)
            ],
        }

    def _gateway_statuses(self) -> dict[str, dict[str, Any]]:
        statuses = gateway_statuses(self.gateways)
        statuses.setdefault("google_chat", {"enabled": False})
        return statuses

    def _gateway_status(self, name: str) -> dict[str, Any]:
        return self._gateway_statuses().get(name, {"enabled": False})

    def _known_gateway_names(self) -> set[str]:
        return set(self.gateways) | {"google_chat"}

    def _skip_gateway_results(self, reason: str) -> dict[str, dict[str, Any]]:
        return {
            name: {"enabled": name in self.gateways, "sent": False, "reason": reason}
            for name in sorted(self._known_gateway_names())
        }

    async def _maybe_post_gateways(
        self,
        digest: dict[str, Any],
        digest_text: str,
        *,
        post_to_gateways: bool,
        dry_run: bool,
        checked_at: str | None,
    ) -> dict[str, dict[str, Any]]:
        if not post_to_gateways:
            return self._skip_gateway_results("preview_only")
        if dry_run:
            return self._skip_gateway_results("dry_run")
        if not digest.get("enabled"):
            return self._skip_gateway_results("digest_disabled")
        if not digest.get("meaningful") and not self.citadel.config.organization_digest_post_on_no_updates:
            return self._skip_gateway_results("no_meaningful_updates")

        results: dict[str, dict[str, Any]] = {}
        for name, gateway in sorted(self.gateways.items()):
            results[name] = await self._post_gateway(
                gateway,
                digest_text,
                message_id=str(checked_at or "latest"),
            )

        if "google_chat" not in results:
            results["google_chat"] = {
                "enabled": False,
                "sent": False,
                "reason": "google_chat_disabled",
            }
        return results

    async def _post_gateway(
        self,
        gateway: NotificationGateway,
        digest_text: str,
        *,
        message_id: str,
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                gateway.post_digest,
                digest_text,
                message_id=message_id,
            )
        except Exception as exc:
            return {
                "enabled": True,
                "ok": False,
                "sent": False,
                "status_category": "delivery_exception",
                "error_type": exc.__class__.__name__,
            }

    async def test_google_chat_delivery(self, message: str | None = None) -> dict[str, Any]:
        """Send one controlled test message to the configured Google Chat space."""
        return await self.test_gateway_delivery(
            "google_chat",
            message=message,
            default_message="Citadel Google Chat delivery test - configuration check only.",
        )

    async def test_gateway_delivery(
        self,
        gateway_name: str,
        *,
        message: str | None = None,
        default_message: str | None = None,
    ) -> dict[str, Any]:
        """Send one controlled test message to a configured delivery gateway."""
        gateway = self.gateways.get(gateway_name)
        if not gateway:
            reason = "google_chat_disabled" if gateway_name == "google_chat" else "gateway_disabled"
            return {
                "ok": False,
                "enabled": False,
                "sent": False,
                "gateway": gateway_name,
                "reason": reason,
            }
        text = message or default_message or (
            f"Citadel {gateway_name} delivery gateway test - configuration check only."
        )
        message_id = f"{gateway_name}-test-{datetime.now(timezone.utc).isoformat()}"
        try:
            result = await asyncio.to_thread(
                gateway.post_digest,
                text,
                message_id=message_id,
            )
        except Exception as exc:
            return {
                "enabled": True,
                "gateway": gateway_name,
                "ok": False,
                "sent": False,
                "status_category": "delivery_exception",
                "error_type": exc.__class__.__name__,
            }
        return {"enabled": True, "gateway": gateway_name, **result}


async def _run_agent(args: argparse.Namespace) -> None:
    agent = LearningAgent.from_env()
    if args.status:
        result = await agent.status()
    else:
        result = await agent.run(
            force=args.force,
            dry_run=args.dry_run,
            post_to_chat=args.post_to_chat,
            include_digest_preview=not args.hide_digest_preview,
        )
    print(json.dumps(result, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kb.learning_agent")
    parser.add_argument("--status", action="store_true", help="Print source-learning status")
    parser.add_argument("--force", action="store_true", help="Treat fetched source activity as new")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print without ingesting")
    parser.add_argument(
        "--post-to-chat",
        action="store_true",
        help="Post the organization update digest to Google Chat",
    )
    parser.add_argument(
        "--hide-digest-preview",
        action="store_true",
        help="Omit the digest message body from command output",
    )
    return parser


def _safe_vault_context_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "id": f"vault-context-{index}",
            "title": str(item)[:180],
            "source": "citadel_search",
        }
    title = (
        item.get("title")
        or item.get("name")
        or item.get("path")
        or item.get("source")
        or item.get("url")
        or item.get("id")
        or f"Vault context {index + 1}"
    )
    return {
        "id": item.get("id") or f"vault-context-{index}",
        "title": str(title)[:180],
        "source": item.get("source") or item.get("url") or item.get("path") or "citadel_search",
        "metadata": _safe_context_metadata(item.get("metadata")),
    }


def _safe_context_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {}
    for key in ("dataset", "repo", "repository", "document_id", "section", "source_type"):
        if key in value:
            allowed[key] = value[key]
    return allowed


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_run_agent(args))


if __name__ == "__main__":
    main()
