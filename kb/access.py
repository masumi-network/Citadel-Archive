from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any
from uuid import uuid4

ROLE_ORDER = {"reader": 1, "writer": 2, "admin": 3}
VALID_ROLES = frozenset(ROLE_ORDER)
VALID_PRINCIPAL_KINDS = frozenset({"user", "service_account"})

DEFAULT_SCOPES = {
    "reader": ("kb:read", "kb:search", "sources:read", "obsidian:sync:pull"),
    "writer": (
        "kb:read",
        "kb:search",
        "kb:ingest",
        "kb:feedback",
        "sources:read",
        "obsidian:sync:pull",
        "obsidian:sync:push",
    ),
    "admin": (
        "kb:read",
        "kb:search",
        "kb:ingest",
        "kb:feedback",
        "sources:read",
        "sources:sync",
        "obsidian:sync:pull",
        "obsidian:sync:push",
        "agents:manage",
        "access:manage",
        "audit:read",
    ),
}


@dataclass(frozen=True)
class AccessIdentity:
    role: str
    actor_id: str
    actor_kind: str
    actor_name: str
    source: str
    scopes: tuple[str, ...] = field(default_factory=tuple)
    token_id: str | None = None


@dataclass(frozen=True)
class AccessPrincipal:
    id: str
    kind: str
    name: str
    role: str
    scopes: tuple[str, ...]
    team_id: str | None
    created_at: str
    disabled_at: str | None = None


@dataclass(frozen=True)
class ApiToken:
    id: str
    principal_id: str
    name: str
    token_hash: str
    prefix: str
    role: str
    scopes: tuple[str, ...]
    team_id: str | None
    created_at: str
    expires_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None


@dataclass(frozen=True)
class TokenCreation:
    token: str
    api_token: ApiToken
    principal: AccessPrincipal


@dataclass(frozen=True)
class TokenSession:
    identity: AccessIdentity
    token_hash: str


@dataclass(frozen=True)
class AuditEvent:
    id: str
    action: str
    actor_id: str | None
    actor_kind: str | None
    actor_name: str | None
    role: str | None
    success: bool
    created_at: str
    dataset: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_api_token(token: str) -> str:
    return hashlib.sha256(f"citadel-api-token:v1:{token}".encode("utf-8")).hexdigest()


def new_api_token() -> str:
    return f"ctdl_{secrets.token_urlsafe(32)}"


def default_scopes(role: str) -> tuple[str, ...]:
    validate_role(role)
    return DEFAULT_SCOPES[role]


def validate_role_scopes(role: str, scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    validate_role(role)
    normalized = _dedupe(tuple(scopes))
    allowed = set(default_scopes(role))
    extra = sorted(set(normalized) - allowed)
    if extra:
        raise ValueError(
            f"Scopes exceed {role} role: {', '.join(extra)}"
        )
    return normalized


def validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(f"Unsupported role: {role}")


def validate_principal_kind(kind: str) -> None:
    if kind not in VALID_PRINCIPAL_KINDS:
        raise ValueError(f"Unsupported principal kind: {kind}")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_expired(value: str | None) -> bool:
    parsed = _parse_time(value)
    return bool(parsed and parsed <= datetime.now(timezone.utc))


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


class AccessStore:
    def __init__(self, path: Path | str, *, max_audit_events: int = 1000) -> None:
        self.path = Path(path)
        self.max_audit_events = max_audit_events

    def has_tokens(self) -> bool:
        return any(token.revoked_at is None for token in self._tokens(self._load()))

    def snapshot(self) -> dict[str, Any]:
        data = self._load()
        return {
            "principals": [asdict(principal) for principal in self._principals(data)],
            "tokens": [self._redact_token(token) for token in self._tokens(data)],
            "audit_events": [asdict(event) for event in self._audit_events(data)],
        }

    def authenticate_token(self, token: str) -> TokenSession | None:
        token_hash = hash_api_token(token)
        data = self._load()
        tokens = self._tokens(data)
        for index, api_token in enumerate(tokens):
            if not secrets.compare_digest(api_token.token_hash, token_hash):
                continue
            session = self._session_for_token(data, api_token)
            if not session:
                return None
            tokens[index] = ApiToken(
                **{
                    **asdict(api_token),
                    "last_used_at": now_iso(),
                }
            )
            data["tokens"] = [asdict(token_item) for token_item in tokens]
            self._save(data)
            return session
        return None

    def token_session(self, token_id: str) -> TokenSession | None:
        data = self._load()
        for api_token in self._tokens(data):
            if api_token.id == token_id:
                return self._session_for_token(data, api_token)
        return None

    def create_principal(
        self,
        *,
        name: str,
        kind: str,
        role: str,
        scopes: tuple[str, ...] | list[str] | None = None,
        team_id: str | None = None,
    ) -> AccessPrincipal:
        validate_principal_kind(kind)
        validate_role(role)
        principal = AccessPrincipal(
            id=f"principal_{uuid4().hex}",
            kind=kind,
            name=name.strip(),
            role=role,
            scopes=validate_role_scopes(role, tuple(scopes) if scopes else default_scopes(role)),
            team_id=team_id,
            created_at=now_iso(),
        )
        data = self._load()
        data["principals"] = [*data.get("principals", []), asdict(principal)]
        self._save(data)
        return principal

    def create_token(
        self,
        *,
        principal_id: str,
        name: str,
        role: str | None = None,
        scopes: tuple[str, ...] | list[str] | None = None,
        team_id: str | None = None,
        expires_at: str | None = None,
    ) -> TokenCreation:
        data = self._load()
        principal = self._principal(data, principal_id)
        if not principal:
            raise KeyError(principal_id)
        resolved_role = role or principal.role
        validate_role(resolved_role)
        resolved_scopes = (
            validate_role_scopes(resolved_role, scopes)
            if scopes is not None
            else validate_role_scopes(
                resolved_role,
                principal.scopes if resolved_role == principal.role else default_scopes(resolved_role),
            )
        )
        token = new_api_token()
        api_token = ApiToken(
            id=f"token_{uuid4().hex}",
            principal_id=principal.id,
            name=name.strip(),
            token_hash=hash_api_token(token),
            prefix=token[:12],
            role=resolved_role,
            scopes=resolved_scopes,
            team_id=team_id if team_id is not None else principal.team_id,
            created_at=now_iso(),
            expires_at=expires_at,
        )
        data["tokens"] = [*data.get("tokens", []), asdict(api_token)]
        self._save(data)
        return TokenCreation(token=token, api_token=api_token, principal=principal)

    def create_principal_token(
        self,
        *,
        name: str,
        kind: str,
        role: str,
        scopes: tuple[str, ...] | list[str] | None = None,
        team_id: str | None = None,
        expires_at: str | None = None,
    ) -> TokenCreation:
        principal = self.create_principal(
            name=name,
            kind=kind,
            role=role,
            scopes=scopes,
            team_id=team_id,
        )
        return self.create_token(
            principal_id=principal.id,
            name=name,
            role=role,
            scopes=scopes,
            team_id=team_id,
            expires_at=expires_at,
        )

    def revoke_token(self, token_id: str) -> ApiToken | None:
        data = self._load()
        tokens = self._tokens(data)
        revoked: ApiToken | None = None
        next_tokens: list[ApiToken] = []
        for api_token in tokens:
            if api_token.id == token_id:
                revoked = ApiToken(**{**asdict(api_token), "revoked_at": api_token.revoked_at or now_iso()})
                next_tokens.append(revoked)
            else:
                next_tokens.append(api_token)
        if not revoked:
            return None
        data["tokens"] = [asdict(api_token) for api_token in next_tokens]
        self._save(data)
        return revoked

    def record_event(
        self,
        *,
        action: str,
        actor: AccessIdentity | None,
        success: bool,
        dataset: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=f"audit_{uuid4().hex}",
            action=action,
            actor_id=actor.actor_id if actor else None,
            actor_kind=actor.actor_kind if actor else None,
            actor_name=actor.actor_name if actor else None,
            role=actor.role if actor else None,
            success=success,
            dataset=dataset,
            detail=detail or {},
            created_at=now_iso(),
        )
        data = self._load()
        events = [*data.get("audit_events", []), asdict(event)][-self.max_audit_events :]
        data["audit_events"] = events
        self._save(data)
        return event

    def _session_for_token(self, data: dict[str, Any], api_token: ApiToken) -> TokenSession | None:
        principal = self._principal(data, api_token.principal_id)
        if not principal:
            return None
        if principal.disabled_at or api_token.revoked_at or _is_expired(api_token.expires_at):
            return None
        identity = AccessIdentity(
            role=api_token.role,
            actor_id=principal.id,
            actor_kind=principal.kind,
            actor_name=principal.name,
            source="api_token",
            scopes=api_token.scopes,
            token_id=api_token.id,
        )
        return TokenSession(identity=identity, token_hash=api_token.token_hash)

    def _principal(self, data: dict[str, Any], principal_id: str) -> AccessPrincipal | None:
        for principal in self._principals(data):
            if principal.id == principal_id:
                return principal
        return None

    def _principals(self, data: dict[str, Any]) -> list[AccessPrincipal]:
        return [
            AccessPrincipal(
                **{
                    **item,
                    "scopes": tuple(item.get("scopes", ())),
                }
            )
            for item in data.get("principals", [])
        ]

    def _tokens(self, data: dict[str, Any]) -> list[ApiToken]:
        return [
            ApiToken(
                **{
                    **item,
                    "scopes": tuple(item.get("scopes", ())),
                }
            )
            for item in data.get("tokens", [])
        ]

    def _audit_events(self, data: dict[str, Any]) -> list[AuditEvent]:
        return [
            AuditEvent(
                **{
                    **item,
                    "detail": item.get("detail", {}),
                }
            )
            for item in data.get("audit_events", [])
        ]

    def _redact_token(self, api_token: ApiToken) -> dict[str, Any]:
        redacted = asdict(api_token)
        redacted.pop("token_hash", None)
        return redacted

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "principals": [], "tokens": [], "audit_events": []}
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "version": data.get("version", 1),
            "principals": data.get("principals", []),
            "tokens": data.get("tokens", []),
            "audit_events": data.get("audit_events", []),
        }

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(self.path)
