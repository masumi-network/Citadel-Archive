from __future__ import annotations

from typing import Any, Mapping, Protocol

from kb.config import CitadelConfig
from kb.google_chat import GoogleChatDelivery


class NotificationGateway(Protocol):
    """Outbound delivery adapter for organization update digests."""

    def status(self) -> dict[str, Any]:
        """Return sanitized gateway status suitable for API responses and logs."""
        ...

    def post_digest(self, text: str, *, message_id: str | None = None) -> dict[str, Any]:
        """Deliver one formatted organization update digest."""
        ...


GatewayMap = Mapping[str, NotificationGateway]


def configured_gateways(config: CitadelConfig) -> dict[str, NotificationGateway]:
    gateways: dict[str, NotificationGateway] = {}
    google_chat = GoogleChatDelivery.from_config(config)
    if google_chat:
        gateways["google_chat"] = google_chat
    return gateways


def gateway_statuses(gateways: GatewayMap) -> dict[str, dict[str, Any]]:
    return {name: gateway.status() for name, gateway in gateways.items()}
