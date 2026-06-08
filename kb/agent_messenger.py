from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from kb.config import CitadelConfig


class AgentMessengerError(RuntimeError):
    pass


class AgentMessengerClient:
    """Small JSON-mode wrapper around the masumi-agent-messenger CLI."""

    def __init__(
        self,
        *,
        command: str = "masumi-agent-messenger",
        profile: str | None = None,
        agent_slug: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.command = command
        self.profile = profile
        self.agent_slug = agent_slug
        self.timeout_seconds = max(1, timeout_seconds)

    @classmethod
    def from_config(cls, config: CitadelConfig) -> "AgentMessengerClient | None":
        if not config.agent_messenger_enabled:
            return None
        return cls(
            command=config.agent_messenger_command,
            profile=config.agent_messenger_profile,
            agent_slug=config.agent_messenger_agent_slug,
            timeout_seconds=config.agent_messenger_timeout_seconds,
        )

    def status(self) -> dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "enabled": True,
                "available": False,
                "command": self.command,
                "reason": "command_not_found",
            }
        try:
            account = self._run("account", "status")
        except AgentMessengerError as exc:
            return {
                "ok": False,
                "enabled": True,
                "available": True,
                "command": self.command,
                "profile": self.profile,
                "agent": self.agent_slug,
                "status_category": "cli_error",
                "error": str(exc),
            }
        return {
            "ok": True,
            "enabled": True,
            "available": True,
            "command": self.command,
            "profile": self.profile,
            "agent": self.agent_slug,
            "account": _safe_payload(account),
        }

    def send_thread(
        self,
        *,
        to: str,
        message: str,
        agent_slug: str | None = None,
        content_type: str = "text/plain",
        headers: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved_agent = self._agent(agent_slug)
        args = [
            "thread",
            "send",
            to,
            message,
            "--agent",
            resolved_agent,
            "--content-type",
            content_type,
        ]
        for header in headers or []:
            args.extend(["--header", header])
        result = self._run(*args)
        return {
            "ok": True,
            "sent": True,
            "surface": "thread",
            "to": to,
            "agent": resolved_agent,
            "content_type": content_type,
            "result": _safe_payload(result),
        }

    def send_channel(
        self,
        *,
        channel: str,
        message: str,
        agent_slug: str | None = None,
    ) -> dict[str, Any]:
        resolved_agent = self._agent(agent_slug)
        result = self._run("channel", "send", channel, message, "--agent", resolved_agent)
        return {
            "ok": True,
            "sent": True,
            "surface": "channel",
            "channel": channel,
            "agent": resolved_agent,
            "result": _safe_payload(result),
        }

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def _agent(self, value: str | None) -> str:
        resolved = (value or self.agent_slug or "").strip()
        if not resolved:
            raise AgentMessengerError(
                "Set CITADEL_AGENT_MESSENGER_AGENT_SLUG or pass an agent slug."
            )
        return resolved

    def _run(self, *args: str) -> dict[str, Any]:
        command = [self.command, *args, "--json"]
        if self.profile:
            command.extend(["--profile", self.profile])
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise AgentMessengerError(f"Command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentMessengerError("Agent Messenger command timed out.") from exc

        if completed.returncode != 0:
            raise AgentMessengerError(_error_message(completed.stderr, completed.stdout))
        try:
            parsed = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise AgentMessengerError("Agent Messenger returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise AgentMessengerError("Agent Messenger returned an unexpected response shape.")
        if parsed.get("ok") is False:
            raise AgentMessengerError(_payload_error(parsed))
        return parsed


def _error_message(stderr: str, stdout: str) -> str:
    for candidate in (stdout, stderr):
        try:
            parsed = json.loads(candidate or "{}")
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return _payload_error(parsed)
    text = " ".join((stderr or stdout or "Agent Messenger command failed.").split())
    return text[:220]


def _payload_error(payload: dict[str, Any]) -> str:
    code = str(payload.get("code") or payload.get("error_code") or "cli_error")
    error = str(payload.get("error") or payload.get("message") or "Agent Messenger command failed.")
    return f"{code}: {error}"[:220]


def _safe_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _redact(value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str):
        return value[:500]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered
        for marker in (
            "token",
            "secret",
            "private",
            "password",
            "passphrase",
            "key",
            "credential",
        )
    )
