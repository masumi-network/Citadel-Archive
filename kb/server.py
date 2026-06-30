from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kb.access import (
    CENTRAL_DATASET,
    SEAT_DATASET_PREFIX,
    AccessIdentity,
    AccessStore,
    ROLE_ORDER,
    default_scopes,
    hash_api_token,
    is_seat_dataset,
    validate_seat_slug,
)
from kb.capture_policy import SeatCapturePolicy, capture_policy_payload
from kb.backup_mirror import BackupMirror, BackupMirrorDisabled, BackupMirrorPublishError
from kb.conflicts import KnowledgeConflictStore, obsidian_push_conflict_candidate
from kb.tags import normalize_tags
from kb.config import CitadelConfig
from kb.github_sync import GitHubOrgSyncer
from kb.linear_sync import LinearSyncer
from kb.knowledge_mesh import KnowledgeMesh
from kb.learning import LearningOutcome, LearningProcess
from kb.learning_agent import LearningAgent
from kb.logging_utils import configure_logging
from kb.mcp_server import TOOL_POLICIES, _max_ingest_bytes, create_mcp_server
from kb.mesh import MeshState
from kb.models import FeedbackRequest
from kb.obsidian_sync import ObsidianSyncStore, SyncPushDocument, normalize_path
from kb.promotion import PromotionEngine
from kb.promotion_queue import APPROVED_STATUS, PENDING_STATUS, REJECTED_STATUS
from kb.repo_content_sync import RepoContentSyncer
from kb.security_scan import SecretContentError
from kb.self_improve import SelfImprovement
from kb.service import Citadel
from kb.skills import skill_catalog, skill_integrity, skill_path
from kb.source_search import GITHUB_DOC_ID_PREFIX, github_section_document

configure_logging()
logger = logging.getLogger(__name__)

# Hosted MCP: one streamable-HTTP endpoint at /mcp/, authenticated per request by
# the caller's ctdl_ bearer token. No clone, no local Python — agents point their
# MCP client at https://<host>/mcp/ with Authorization: Bearer <token>.
MCP_ENDPOINT_PATH = "/mcp/"

# Strong refs to detached fire-and-forget tasks (e.g. the webhook re-ingest) so
# the event loop does not garbage-collect them mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

mcp_server = create_mcp_server()
mcp_app = mcp_server.streamable_http_app()


class _McpAcceptShim:
    """Augment the Accept header so minimal MCP clients reach the transport.

    The mcp>=1.23 StreamableHTTP transport answers a POST with HTTP 406 unless
    ``Accept`` lists BOTH ``application/json`` and ``text/event-stream`` (``*/*``
    is deliberately not honored). Minimal clients (e.g. the Raspberry Pi MCP
    bridge) send ``application/json`` only, or omit Accept, and cannot connect.
    This shim rewrites the header in-flight to advertise both content types
    before delegating to the mounted streamable-HTTP app, leaving callers that
    already send both untouched.
    """

    _BOTH = "application/json, text/event-stream"
    _REQUIRED = ("application/json", "text/event-stream")

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = scope.get("headers") or []
        kept = [(name, value) for name, value in raw_headers if name.lower() != b"accept"]
        existing = (
            b", ".join(value for name, value in raw_headers if name.lower() == b"accept")
            .decode("latin-1")
            .strip()
        )
        if not existing or existing == "*/*":
            merged = self._BOTH
        else:
            merged = existing
            lowered = existing.lower()
            for needed in self._REQUIRED:
                if needed not in lowered:
                    merged = f"{merged}, {needed}"
        kept.append((b"accept", merged.encode("latin-1")))
        await self.app({**scope, "headers": kept}, receive, send)


async def _evolve_scheduler_loop(interval_seconds: int) -> None:
    """Run the evolve cycle every ``interval_seconds``: heavy stages in a
    subprocess, then cognify in-loop.

    Two cognee/Kuzu constraints force this split:
    - cognee binds its async resources to the loop that created them, so cognify
      must run in the server's long-lived loop — a fresh ``asyncio.run()`` raises
      "got Future attached to a different loop".
    - Kuzu (the graph store) is a single-writer embedded DB, so only one process
      may hold it. The subprocess opens Kuzu during its add stages and releases it
      when it EXITS; only then can the web process cognify as the sole writer.

    Phase 1 runs github_sync → repo_content_sync → self_improve → promotion as a
    subprocess (``CITADEL_EVOLVE_COGNIFY_ENABLED=false``) that exits. Phase 2
    awaits cognify in-loop on the web's own Citadel. Serial and fail-soft; the
    first pass waits one full interval so a redeploy never triggers a heavy cycle
    on boot.
    """
    import sys

    while True:
        await asyncio.sleep(interval_seconds)
        logger.info("Evolve scheduler: starting scheduled pass")
        # Phase 1 — heavy stages in a subprocess that frees the Kuzu lock on exit.
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "scripts.run_railway",
                env={
                    **os.environ,
                    "CITADEL_RUN_MODE": "evolve",
                    "CITADEL_EVOLVE_COGNIFY_ENABLED": "false",
                },
            )
            code = await proc.wait()
            logger.info("Evolve scheduler: stages finished (exit=%s)", code)
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                proc.terminate()
            raise
        except Exception:
            logger.exception("Evolve scheduler: stages subprocess failed")
        # Phase 2 — cognify in-loop; the web process is the sole Kuzu writer now.
        force = os.getenv("CITADEL_EVOLVE_COGNIFY_FORCE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            result = await get_citadel().cognify_dataset(force=force)
            logger.info(
                "Evolve scheduler: cognify finished (graph_after=%s grew=%s)",
                result.get("graph_after"),
                result.get("graph_grew"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Evolve scheduler: cognify failed")


def _start_evolve_scheduler() -> "asyncio.Task[Any] | None":
    """Launch the 6h evolve cron when enabled.

    A separate Railway service cannot host this: the stages work against the Kuzu
    graph + JSON access store on the local ``/data`` volume, and Railway volumes
    attach to a single service. The scheduler runs the heavy stages as a
    subprocess on the web container and then cognifies in-loop (see
    :func:`_evolve_scheduler_loop` for why the split is required). Off by default
    (``CITADEL_EVOLVE_SCHEDULER_ENABLED``).
    """
    config = get_citadel().config
    if not config.evolve_scheduler_enabled:
        return None
    interval = max(60, config.evolve_interval_seconds)
    logger.info("Evolve scheduler enabled: interval=%ss", interval)
    task = asyncio.create_task(_evolve_scheduler_loop(interval))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def _stop_evolve_scheduler(task: "asyncio.Task[Any] | None") -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    async with mcp_server.session_manager.run():
        # Eagerly build the mesh and seed its in-memory activity counters from
        # persistent source state so a redeploy does not look like the graph reset.
        # get_mesh() then returns this already-seeded instance. Best-effort: a failed
        # rehydrate must never block startup.
        mesh = MeshState()
        app.state.mesh = mesh
        try:
            await mesh.rehydrate(get_citadel().config)
        except Exception:
            logger.exception("Mesh rehydrate failed; starting with empty counters")
        evolve_task = _start_evolve_scheduler()
        try:
            yield
        finally:
            await _stop_evolve_scheduler(evolve_task)


# Single-source the service version so /.well-known/citadel.json and the CLI
# never drift. Prefer installed package metadata; fall back to the in-source
# kb.__version__ because the Railway node runs from source (not dist-installed),
# where importlib.metadata raises and a hardcoded version would mislead.
try:
    _SERVICE_VERSION = _pkg_version("citadel-archive")
except PackageNotFoundError:
    from kb import __version__ as _SERVICE_VERSION

app = FastAPI(
    title="Citadel Archive",
    version=_SERVICE_VERSION,
    description="Self-hosted Organization Vault wrapper around Cognee.",
    lifespan=lifespan,
)
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=False)
async def mcp_trailing_slash_redirect() -> RedirectResponse:
    """Keep legacy /mcp configs working without emitting an absolute http:// redirect."""
    return RedirectResponse(url=MCP_ENDPOINT_PATH, status_code=307)


app.mount("/mcp", _McpAcceptShim(mcp_app))
ADMIN_COOKIE = "citadel_admin"
MCP_TOOL_HEADER = "x-citadel-mcp-tool"
AUDIT_VIEWS = frozenset({"all", "mcp", "access", "failures"})
AUDIT_LIMIT_MAX = 500
PUBLIC_CACHE_HEADERS = {"Cache-Control": "public, max-age=300"}
PRIVATE_CACHE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
PUBLIC_CACHE_PATHS = frozenset({"/.well-known/citadel.json", "/skills"})
PUBLIC_CACHE_PREFIXES = ("/skills/", "/static/")
PUBLIC_HOST_RE = re.compile(r"^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::[0-9]{1,5})?$")
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

LOGIN_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Citadel Admin</title>
    <link rel="stylesheet" href="/static/styles.css" />
  </head>
  <body>
    <main class="login-shell">
      <section class="login-panel">
        <div class="brand compact">
          <div class="brand-mark" aria-hidden="true">CA</div>
          <div>
            <h1>Citadel Archive</h1>
            <p>Workspace access</p>
          </div>
        </div>
        <form id="loginForm" class="form">
          <div class="field">
            <label for="adminKey">Access key</label>
            <input
              id="adminKey"
              name="accessKey"
              type="password"
              autocomplete="current-password"
              required
              autofocus
            />
          </div>
          <p id="loginError" class="form-error" role="alert"></p>
          <button id="loginSubmit" class="primary-button" type="submit">Open workspace</button>
        </form>
      </section>
    </main>
    <script src="/static/login.js" type="module"></script>
  </body>
</html>
"""


class IngestBody(BaseModel):
    data: str = Field(min_length=1)
    dataset: str | None = None
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    # When true, cognify the written dataset inline (server-side, where it holds
    # the single Kuzu writer) and block until done — so a writer's ingest is
    # immediately searchable without needing the admin-only cognify endpoint.
    cognify: bool = False


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    dataset: str | None = None
    session_id: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class FeedbackBody(BaseModel):
    qa_id: str = Field(min_length=1)
    score: int | None = Field(default=None, ge=-1, le=1)
    text: str | None = None
    session_id: str | None = None
    dataset: str | None = None


class ImproveBody(BaseModel):
    dataset: str | None = None
    session_ids: list[str] | None = None


class AdminSessionBody(BaseModel):
    access_key: str | None = Field(default=None, min_length=1)
    admin_key: str | None = Field(default=None, min_length=1)


class GitHubSyncBody(BaseModel):
    force: bool = False


class LinearSyncBody(BaseModel):
    force: bool = False


class RepoContentSyncBody(BaseModel):
    force: bool = False
    dry_run: bool = False


class LearningAgentRunBody(BaseModel):
    force: bool = False
    dry_run: bool = False
    post_to_chat: bool = False
    include_digest_preview: bool = True


class GoogleChatTestBody(BaseModel):
    message: str | None = Field(default=None, min_length=1, max_length=400)


class BackupMirrorRunBody(BaseModel):
    dry_run: bool = True


class PromoteRunBody(BaseModel):
    dataset: str = Field(min_length=1)
    dry_run: bool = True
    max_items: int | None = Field(default=None, ge=1, le=200)


class PromotionDecisionBody(BaseModel):
    note: str | None = Field(default=None, max_length=400)


class CognifyRunBody(BaseModel):
    dataset: str | None = None
    verify: bool = False
    force: bool = False


class AccessTokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="reader")
    kind: str = Field(default="service_account")
    scopes: list[str] | None = None
    team_id: str | None = None
    expires_at: str | None = None
    default_dataset: str | None = None
    default_session: str | None = None
    allowed_datasets: list[str] | None = None


class CreateSeatBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=63)
    email: str | None = Field(default=None, max_length=320)
    role: str = Field(default="writer")
    issue_token: bool = True
    token_name: str | None = Field(default=None, max_length=120)


class IssueSeatTokenBody(BaseModel):
    token_name: str | None = Field(default=None, max_length=120)


class CapturePolicyBody(BaseModel):
    deny_globs: list[str] = Field(default_factory=list, max_length=200)


class ObsidianVaultBody(BaseModel):
    vault_name: str | None = Field(default=None, min_length=1, max_length=180)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    team_id: str | None = Field(default=None, max_length=120)
    plugin_version: str | None = Field(default=None, max_length=80)


class ObsidianPushDocumentBody(BaseModel):
    path: str = Field(min_length=1, max_length=600)
    content: str = ""
    base_rev: int | None = Field(default=None, ge=0)
    deleted: bool = False
    tags: list[str] = Field(default_factory=list)
    dataset: str | None = None


class ObsidianPushBody(BaseModel):
    vault_id: str = Field(min_length=1)
    documents: list[ObsidianPushDocumentBody] = Field(min_length=1)
    dataset: str | None = None
    session_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ObsidianConflictResolveBody(BaseModel):
    resolution: str = Field(pattern="^(accept_local|accept_remote|save_both|manual)$")
    body: str | None = None


class KnowledgeConflictResolveBody(BaseModel):
    resolution_note: str = Field(min_length=1, max_length=400)


class ContributeBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = Field(default=None, max_length=1000)
    dataset: str | None = None


class OptimizeBody(BaseModel):
    dry_run: bool = False
    max_items: int | None = Field(default=None, ge=1, le=50)


def get_citadel() -> Citadel:
    if not hasattr(app.state, "citadel"):
        app.state.citadel = Citadel.from_env()
    return app.state.citadel


def get_mesh() -> MeshState:
    if not hasattr(app.state, "mesh"):
        app.state.mesh = MeshState()
    return app.state.mesh


def get_github_syncer() -> GitHubOrgSyncer:
    if hasattr(app.state, "github_syncer"):
        return app.state.github_syncer
    return GitHubOrgSyncer(get_citadel())


def get_repo_content_syncer() -> RepoContentSyncer:
    if hasattr(app.state, "repo_content_syncer"):
        return app.state.repo_content_syncer
    return RepoContentSyncer(get_citadel())


def get_linear_syncer() -> LinearSyncer:
    if hasattr(app.state, "linear_syncer"):
        return app.state.linear_syncer
    return LinearSyncer(get_citadel(), access_store=get_access_store())


def get_learning_agent() -> LearningAgent:
    if hasattr(app.state, "learning_agent"):
        return app.state.learning_agent
    return LearningAgent(
        get_citadel(),
        github_syncer=get_github_syncer(),
        repo_content_syncer=get_repo_content_syncer(),
    )


def get_backup_mirror() -> BackupMirror:
    return BackupMirror(get_citadel().config)


def get_promotion_engine() -> PromotionEngine:
    citadel = get_citadel()
    return PromotionEngine(
        citadel,
        get_learning_process(),
        get_access_store(),
        citadel.config,
    )


def get_access_store() -> AccessStore:
    existing = getattr(app.state, "access_store", None)
    if isinstance(existing, AccessStore):
        return existing
    config = get_citadel().config
    app.state.access_store = AccessStore(
        config.access_store_path,
        max_audit_events=config.audit_max_events,
    )
    return app.state.access_store


def get_obsidian_sync() -> ObsidianSyncStore:
    existing = getattr(app.state, "obsidian_sync", None)
    if isinstance(existing, ObsidianSyncStore):
        return existing
    app.state.obsidian_sync = ObsidianSyncStore(get_citadel().config.obsidian_sync_state_path)
    return app.state.obsidian_sync


def get_conflict_store() -> KnowledgeConflictStore:
    existing = getattr(app.state, "conflict_store", None)
    if isinstance(existing, KnowledgeConflictStore):
        return existing
    config = get_citadel().config
    app.state.conflict_store = KnowledgeConflictStore(
        config.conflicts_store_path,
        max_records=config.conflicts_max_records,
    )
    return app.state.conflict_store


def get_learning_process() -> LearningProcess:
    return LearningProcess(
        get_citadel(),
        mesh=get_mesh(),
        conflicts=get_conflict_store(),
    )


def get_knowledge_mesh() -> KnowledgeMesh:
    existing = getattr(app.state, "knowledge_mesh", None)
    if isinstance(existing, KnowledgeMesh):
        return existing
    return KnowledgeMesh(getattr(get_citadel(), "cognee", None))


def sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def configured_access_keys() -> list[tuple[str, str]]:
    config = get_citadel().config
    entries: list[tuple[str, str]] = []
    if config.admin_key:
        entries.append(("admin", config.admin_key))
    entries.extend(("writer", key) for key in config.writer_keys)
    entries.extend(("reader", key) for key in config.reader_keys)
    return entries


def env_identity(role: str) -> AccessIdentity:
    return AccessIdentity(
        role=role,
        actor_id=f"bootstrap:{role}",
        actor_kind="bootstrap_key",
        actor_name=f"{role.title()} bootstrap key",
        source="env",
        scopes=default_scopes(role),
    )


def session_token(role: str, access_key: str) -> str:
    message = f"citadel-session:v2:{role}".encode("utf-8")
    return hmac.new(access_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def cookie_value(role: str, access_key: str) -> str:
    return f"{role}:{session_token(role, access_key)}"


def token_session_signature(role: str, token_id: str, token_hash: str) -> str:
    message = f"citadel-session:v2:token:{role}:{token_id}".encode("utf-8")
    return hmac.new(token_hash.encode("utf-8"), message, hashlib.sha256).hexdigest()


def token_cookie_value(identity: AccessIdentity, token_hash: str) -> str:
    if not identity.token_id:
        raise ValueError("Token identity missing token ID.")
    signature = token_session_signature(identity.role, identity.token_id, token_hash)
    return f"token:{identity.role}:{identity.token_id}:{signature}"


def access_key_identity(access_key: str) -> tuple[AccessIdentity, str] | None:
    for role, key in configured_access_keys():
        if secrets.compare_digest(access_key, key):
            return env_identity(role), cookie_value(role, access_key)
    token_session = get_access_store().authenticate_token(access_key)
    if token_session:
        return token_session.identity, token_cookie_value(
            token_session.identity,
            hash_api_token(access_key),
        )
    return None


def session_identity(request: Request) -> AccessIdentity | None:
    session = request.cookies.get(ADMIN_COOKIE)
    if not session:
        return None
    for role, key in configured_access_keys():
        if secrets.compare_digest(session, cookie_value(role, key)):
            return env_identity(role)
    parts = session.split(":")
    if len(parts) != 4 or parts[0] != "token":
        return None
    _, role, token_id, signature = parts
    token_session = get_access_store().token_session(token_id)
    if not token_session or token_session.identity.role != role:
        return None
    expected = token_session_signature(role, token_id, token_session.token_hash)
    if not secrets.compare_digest(signature, expected):
        return None
    return token_session.identity


def bearer_identity(request: Request) -> AccessIdentity | None:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        return None
    identity_with_cookie = access_key_identity(token.strip())
    if not identity_with_cookie:
        return None
    identity, _ = identity_with_cookie
    return identity


def request_identity(request: Request) -> AccessIdentity | None:
    return bearer_identity(request) or session_identity(request)


def session_role(request: Request) -> str | None:
    identity = session_identity(request)
    return identity.role if identity else None


def require_role(request: Request, minimum_role: str) -> AccessIdentity:
    identity = request_identity(request)
    if not identity:
        logger.warning(
            "Rejected unauthenticated request: %s %s", request.method, request.url.path
        )
        raise HTTPException(status_code=401, detail="Access key required.")
    if ROLE_ORDER[identity.role] < ROLE_ORDER[minimum_role]:
        logger.warning(
            "Denied %s %s for actor %s: role %s below required %s",
            request.method,
            request.url.path,
            identity.actor_id,
            identity.role,
            minimum_role,
        )
        raise HTTPException(status_code=403, detail=f"{minimum_role.title()} access required.")
    return identity


def effective_scopes(identity: AccessIdentity) -> tuple[str, ...]:
    if identity.scopes:
        return identity.scopes
    if identity.source == "env":
        return default_scopes(identity.role)
    return ()


def require_access(request: Request, minimum_role: str, scope: str) -> AccessIdentity:
    identity = require_role(request, minimum_role)
    if scope not in effective_scopes(identity):
        raise HTTPException(status_code=403, detail=f"Scope required: {scope}.")
    return identity


def can_bypass_dataset_allowlist(identity: AccessIdentity) -> bool:
    if identity.source == "env":
        return True
    if identity.role == "admin":
        return True
    return "access:manage" in effective_scopes(identity)


def env_exclude_patterns() -> tuple[str, ...]:
    return get_citadel().config.exclude_patterns


def require_capture_policy_read(request: Request, slug: str) -> tuple[AccessIdentity, str]:
    try:
        normalized = validate_seat_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    identity = require_access(request, "reader", "kb:read")
    if identity.role == "admin" or "access:manage" in effective_scopes(identity):
        return identity, normalized
    if identity.seat_slug == normalized:
        return identity, normalized
    raise HTTPException(status_code=403, detail="Capture policy is not available for this seat.")


def seat_capture_policy_response(slug: str) -> dict[str, Any]:
    store = get_access_store()
    if not store.find_seat_by_slug(slug):
        raise HTTPException(status_code=404, detail=f"Seat not found: {slug}")
    baseline = store.get_capture_policy(slug)
    return capture_policy_payload(
        seat_slug=slug,
        baseline=baseline,
        env_exclude_patterns=env_exclude_patterns(),
    )


def can_run_promotion(identity: AccessIdentity, seat_dataset: str) -> bool:
    if not is_seat_dataset(seat_dataset):
        return False
    seat_slug = seat_dataset.removeprefix("seat:")
    if identity.role == "admin" or "sources:sync" in effective_scopes(identity):
        return True
    if identity.role == "writer" and identity.seat_slug == seat_slug:
        return True
    return False


def can_decide_promotion_item(
    identity: AccessIdentity,
    item_seat_slug: str,
) -> tuple[bool, bool]:
    if identity.role == "admin" or "access:manage" in effective_scopes(identity):
        delegate = identity.seat_slug is not None and identity.seat_slug != item_seat_slug
        if identity.seat_slug is None:
            delegate = True
        return True, delegate
    if identity.seat_slug == item_seat_slug:
        return True, False
    return False, False


def promotion_pending_filter_seat(identity: AccessIdentity) -> str | None:
    if identity.role == "admin" or "access:manage" in effective_scopes(identity):
        return None
    if identity.seat_slug:
        return identity.seat_slug
    raise HTTPException(
        status_code=403,
        detail="Promotion queue is only available to seat holders and admins.",
    )


def redact_pending_item(item: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(item)
    redacted.pop("candidate_text", None)
    return redacted


def enforce_dataset_allowlist(identity: AccessIdentity, dataset: str) -> None:
    if can_bypass_dataset_allowlist(identity):
        return
    if dataset in identity.allowed_datasets:
        return
    # Seat nodes are private memory: the seat: namespace is default-deny even for
    # callers that carry no allowlist at all. Without this, any legacy or non-seat
    # token (whose allowed_datasets is empty) could read or write another seat's
    # node by naming it explicitly. Non-seat datasets stay open for unscoped tokens
    # to preserve backward compatibility.
    if is_seat_dataset(dataset):
        raise HTTPException(status_code=403, detail=f"Dataset not allowed: {dataset}.")
    if not identity.allowed_datasets:
        return
    raise HTTPException(status_code=403, detail=f"Dataset not allowed: {dataset}.")


def scope_override_active(
    identity: AccessIdentity,
    datasets: list[str] | tuple[str, ...],
) -> bool:
    """True when a bypassing caller that carries an explicit allowlist reaches a
    dataset outside it — the auditable "admin overrode scope" case. Callers with
    no allowlist (env/bootstrap) were never scope-bound, so they are not flagged.
    """
    if not identity.allowed_datasets:
        return False
    if not can_bypass_dataset_allowlist(identity):
        return False
    return any(dataset not in identity.allowed_datasets for dataset in datasets)


ORG_BOUND_TAGS = frozenset(
    {
        "vault-contribution",
        "org-ready",
        "repo-content",
        "product-knowledge",
        "github",
        "github-daily",
    }
)
PROMOTION_TAGS = frozenset({"org-ready", "vault-contribution"})
IngestTier = str


@dataclass(frozen=True)
class WriteTarget:
    dataset: str
    tier: IngestTier


def central_dataset(config: CitadelConfig) -> str:
    return config.github_sync_dataset or CENTRAL_DATASET


def is_org_bound(tags: list[str] | tuple[str, ...]) -> bool:
    return bool(set(normalize_tags(tags)) & ORG_BOUND_TAGS)


def is_promotion(tags: list[str] | tuple[str, ...]) -> bool:
    return bool(set(normalize_tags(tags)) & PROMOTION_TAGS)


def seat_safe_tags(identity: AccessIdentity, tags: list[str] | tuple[str, ...]) -> list[str]:
    """Drop org/promotion tags for seat writers (ADR-0007 Node-only writes)."""
    normalized = list(normalize_tags(tags))
    if not is_seat_identity(identity) or can_bypass_dataset_allowlist(identity):
        return normalized
    blocked = ORG_BOUND_TAGS | PROMOTION_TAGS
    return [tag for tag in normalized if tag not in blocked]


def resolve_search_datasets(
    identity: AccessIdentity,
    requested: str | None,
    config: CitadelConfig,
) -> list[str]:
    if requested:
        enforce_dataset_allowlist(identity, requested)
        return [requested]

    node_dataset = identity.default_dataset if is_seat_dataset(identity.default_dataset) else None
    if node_dataset:
        enforce_dataset_allowlist(identity, node_dataset)
        datasets = [node_dataset]
        central = central_dataset(config)
        if central != node_dataset:
            if can_bypass_dataset_allowlist(identity) or (
                not identity.allowed_datasets or central in identity.allowed_datasets
            ):
                enforce_dataset_allowlist(identity, central)
                datasets.append(central)
        return datasets

    dataset = identity.default_dataset or config.search_default_dataset or config.default_dataset
    enforce_dataset_allowlist(identity, dataset)
    return [dataset]


def resolve_search_dataset(
    identity: AccessIdentity,
    requested: str | None,
    config: CitadelConfig,
) -> str:
    return resolve_search_datasets(identity, requested, config)[0]


def is_seat_identity(identity: AccessIdentity) -> bool:
    # A seat is a private-memory boundary, identified by a seat: node either as
    # the default target or anywhere in the allowlist. Keying only off
    # default_dataset would let a seat token whose default is Central slip the
    # curation gate, so the allowlist is the authoritative signal.
    if is_seat_dataset(identity.default_dataset):
        return True
    return any(is_seat_dataset(dataset) for dataset in identity.allowed_datasets)


def seat_node_dataset(identity: AccessIdentity) -> str | None:
    if is_seat_dataset(identity.default_dataset):
        return identity.default_dataset
    for dataset in identity.allowed_datasets:
        if is_seat_dataset(dataset):
            return dataset
    return None


def guard_seat_write_policy(
    identity: AccessIdentity,
    *,
    operation: str,
    dataset: str | None,
    tags: list[str] | tuple[str, ...],
) -> None:
    """ADR-0007: seat-scoped callers write to their Node only; Central is read-only."""
    if not is_seat_identity(identity) or can_bypass_dataset_allowlist(identity):
        return

    node = seat_node_dataset(identity)
    if not node:
        raise HTTPException(
            status_code=403,
            detail="Seat identity has no personal node configured.",
        )

    if operation == "contribute":
        raise HTTPException(
            status_code=403,
            detail=(
                "Seat holders cannot contribute directly to Central. Add durable notes "
                "to your personal node; Central is updated via Promotion and org sync."
            ),
        )

    normalized_tags = normalize_tags(tags)
    if is_org_bound(normalized_tags) or is_promotion(normalized_tags):
        raise HTTPException(
            status_code=403,
            detail=(
                "Seat writes cannot use org or promotion tags. Content stays in your "
                "personal node; Central is updated via Promotion and org sync."
            ),
        )

    if dataset and dataset != node:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Seat writes may only target your personal node ({node}). "
                "Central is read-only; use Promotion to share org knowledge."
            ),
        )


def guard_curated_central(
    identity: AccessIdentity,
    dataset: str,
    tags: list[str] | tuple[str, ...],
    config: CitadelConfig,
) -> None:
    # Central is curated: a seat-holder cannot drop raw content straight into it.
    # Writes to Central from a seat must carry an org tag (which routes through
    # promotion/dual-write) or go through /api/contribute. Admin/env callers
    # bypass this, and non-seat service accounts keep their direct Central path.
    if (
        dataset == central_dataset(config)
        and is_seat_identity(identity)
        and not is_org_bound(tags)
        and not can_bypass_dataset_allowlist(identity)
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Direct writes to Central require an org tag "
                "(org-ready / vault-contribution) or /api/contribute."
            ),
        )


def resolve_write_targets(
    identity: AccessIdentity,
    requested: str | None,
    tags: list[str],
    config: CitadelConfig,
) -> list[WriteTarget]:
    normalized_tags = list(normalize_tags(tags))

    if is_seat_identity(identity) and not can_bypass_dataset_allowlist(identity):
        node = seat_node_dataset(identity)
        if not node:
            raise HTTPException(
                status_code=403,
                detail="Seat identity has no personal node configured.",
            )
        guard_seat_write_policy(
            identity,
            operation="ingest",
            dataset=requested,
            tags=normalized_tags,
        )
        enforce_dataset_allowlist(identity, node)
        return [WriteTarget(node, "light")]

    if requested:
        dataset = requested
        guard_curated_central(identity, dataset, tags, config)
        enforce_dataset_allowlist(identity, dataset)
        tier: IngestTier = "light" if is_seat_dataset(dataset) and not is_org_bound(tags) else "full"
        return [WriteTarget(dataset, tier)]

    node_dataset = identity.default_dataset if is_seat_dataset(identity.default_dataset) else None
    central = central_dataset(config)

    if is_promotion(normalized_tags) and node_dataset:
        targets = [
            WriteTarget(node_dataset, "light"),
            WriteTarget(central, "full"),
        ]
        for target in targets:
            enforce_dataset_allowlist(identity, target.dataset)
        return targets

    if is_org_bound(normalized_tags):
        enforce_dataset_allowlist(identity, central)
        return [WriteTarget(central, "full")]

    dataset = identity.default_dataset or config.default_dataset
    guard_curated_central(identity, dataset, normalized_tags, config)
    enforce_dataset_allowlist(identity, dataset)
    tier = "light" if is_seat_dataset(dataset) else "full"
    return [WriteTarget(dataset, tier)]


def resolve_write_dataset(
    identity: AccessIdentity,
    requested: str | None,
    config: CitadelConfig,
) -> str:
    return resolve_write_targets(identity, requested, [], config)[0].dataset


def search_result_dedup_key(result: Any) -> str:
    if isinstance(result, dict):
        text = first_string(
            result.get("text"),
            result.get("content"),
            result.get("chunk"),
            result.get("body"),
            result.get("summary"),
            result.get("title"),
            result.get("query"),
        )
        if text:
            return text.strip().lower()
        return json.dumps(
            {key: value for key, value in result.items() if key != "_citadel"},
            sort_keys=True,
            default=str,
        )
    return str(result)


async def search_across_datasets(
    citadel: Citadel,
    *,
    query: str,
    datasets: list[str],
    sessions: Mapping[str, str | None],
    top_k: int,
) -> list[tuple[str, Any]]:
    # Query every dataset before merging so a result-rich primary node can never
    # short-circuit (and thereby silently drop) Central. The primary still wins
    # dedup and takes the bulk of the slots; a reserved slice keeps room for the
    # secondary datasets when more than one is in scope. Sessions are resolved per
    # dataset: a seat's private session must not scope shared datasets like Central
    # (see resolve_search_sessions), or it would hide org-wide hits.
    per_dataset: list[tuple[str, list[Any]]] = []
    for dataset in datasets:
        results = await citadel.search(
            query,
            dataset=dataset,
            session_id=sessions.get(dataset),
            top_k=top_k,
        )
        per_dataset.append((dataset, list(results)))

    merged: list[tuple[str, Any]] = []
    seen: set[str] = set()

    def take(dataset: str, results: list[Any], budget: int) -> None:
        for result in results:
            if budget <= 0 or len(merged) >= top_k:
                return
            key = search_result_dedup_key(result)
            if key in seen:
                continue
            seen.add(key)
            merged.append((dataset, result))
            budget -= 1

    if not per_dataset:
        return merged

    reserve = max(1, top_k // 5) if len(per_dataset) > 1 else 0
    primary_dataset, primary_results = per_dataset[0]
    take(primary_dataset, primary_results, top_k - reserve)
    for dataset, results in per_dataset[1:]:
        take(dataset, results, top_k - len(merged))
    # Backfill any slots the secondaries left unused from the primary node.
    take(primary_dataset, primary_results, top_k - len(merged))
    return merged


async def execute_learning_writes(
    learning: LearningProcess,
    *,
    data: str,
    targets: list[WriteTarget],
    tags: list[str],
    session_id: str | None,
    operation: str,
    detect_conflicts: bool = True,
    run_improve: bool = False,
) -> tuple[LearningOutcome, list[LearningOutcome]]:
    outcomes: list[LearningOutcome] = []
    primary: LearningOutcome | None = None
    for target in targets:
        outcome = await learning.learn(
            data,
            dataset=target.dataset,
            tags=tags,
            session_id=session_id,
            operation=operation,
            detect_conflicts=detect_conflicts and target.tier == "full",
            run_improve=run_improve and target.tier == "full",
            tier=target.tier,
        )
        outcomes.append(outcome)
        if primary is None or target.tier == "full":
            primary = outcome
    if primary is None:
        raise RuntimeError("execute_learning_writes requires at least one target")
    return primary, outcomes


def assert_requested_session_allowed(identity: AccessIdentity, requested: str | None) -> None:
    # A session id is private context, and session-scoped recall ignores the
    # dataset allowlist (Cognee recalls by session without a dataset constraint).
    # Seat sessions are `seat-{slug}` — derived from a guessable slug — so a caller
    # who could name another seat's session would read that seat's private node,
    # sidestepping node isolation. A non-bypass caller may therefore only name
    # their own default_session; admin/env callers keep full session reach (org
    # sync sessions, cross-seat support).
    if not requested:
        return
    if can_bypass_dataset_allowlist(identity):
        return
    if requested == identity.default_session:
        return
    raise HTTPException(status_code=403, detail="Session not allowed.")


def resolve_session_id(identity: AccessIdentity, requested: str | None) -> str | None:
    assert_requested_session_allowed(identity, requested)
    return requested or identity.default_session


def resolve_search_sessions(
    identity: AccessIdentity,
    requested: str | None,
    datasets: list[str],
) -> dict[str, str | None]:
    # A session is private node memory. Scope it to the caller's own node only, so
    # a seat session can never filter (and thereby hide org-wide hits in) a shared
    # dataset like Central — even when the seat passes its own session explicitly.
    # Admin/env callers may target any session across whatever they searched.
    assert_requested_session_allowed(identity, requested)
    if requested and can_bypass_dataset_allowlist(identity):
        return {dataset: requested for dataset in datasets}
    session = requested or identity.default_session
    if not session:
        return {dataset: None for dataset in datasets}
    owned = identity.default_dataset
    return {
        # The session scopes the caller's own node; for a caller with no node of
        # its own, a single-dataset search still scopes to that one dataset.
        dataset: (
            session
            if dataset == owned or (owned is None and len(datasets) == 1)
            else None
        )
        for dataset in datasets
    }


def node_label(dataset: str | None) -> str | None:
    # A friendly, human label for the caller's private Node dataset. Only seat
    # nodes get a label; shared datasets like Central are not a personal Node.
    if not is_seat_dataset(dataset):
        return None
    slug = dataset[len(SEAT_DATASET_PREFIX) :]
    return f"{slug}'s private Node"


def resolved_memory_scope(
    identity: AccessIdentity,
    config: CitadelConfig,
) -> dict[str, Any]:
    search_datasets = resolve_search_datasets(identity, None, config)
    # Reflect ONLY the authenticated caller's own identity: seat_slug is read
    # straight off this identity (null for non-seat callers), never another seat.
    seat_slug = identity.seat_slug
    return {
        "default_dataset": search_datasets[0],
        "default_session": identity.default_session,
        "allowed_datasets": list(identity.allowed_datasets) or None,
        "search_datasets": search_datasets if len(search_datasets) > 1 else None,
        "seat_slug": seat_slug,
        "node_label": node_label(identity.default_dataset),
    }


_AUTHOR_TAG_RE = re.compile(r"[^a-z0-9]+")


def _author_tag(actor: AccessIdentity) -> str | None:
    if not actor.actor_name:
        return None
    slug = _AUTHOR_TAG_RE.sub("-", actor.actor_name.strip().lower()).strip("-")
    return slug or None


def _contribution_tags(body_tags: list[str], actor: AccessIdentity) -> list[str]:
    tags = list(dict.fromkeys([*body_tags, "vault-contribution"]))
    if not any(tag.startswith("author:") for tag in tags):
        author = _author_tag(actor)
        if author:
            tags.append(f"author:{author}")
    return tags


def role_payload(role: str, identity: AccessIdentity | None = None) -> dict[str, Any]:
    scopes = set(effective_scopes(identity)) if identity else set(default_scopes(role))
    payload: dict[str, Any] = {
        "role": role,
        "capabilities": {
            "read": ROLE_ORDER[role] >= ROLE_ORDER["reader"]
            and bool({"kb:read", "kb:search", "sources:read", "obsidian:sync:pull"} & scopes),
            "write": ROLE_ORDER[role] >= ROLE_ORDER["writer"]
            and bool({"kb:ingest", "kb:feedback", "obsidian:sync:push"} & scopes),
            "admin": ROLE_ORDER[role] >= ROLE_ORDER["admin"]
            and bool({"sources:sync", "access:manage", "audit:read"} & scopes),
        },
        "actor": None
        if identity is None
        else {
            "id": identity.actor_id,
            "kind": identity.actor_kind,
            "name": identity.actor_name,
            "source": identity.source,
            "token_id": identity.token_id,
            "scopes": list(effective_scopes(identity)),
        },
    }
    if identity is not None:
        payload.update(resolved_memory_scope(identity, get_citadel().config))
    return payload


def mcp_tool_name(request: Request) -> str | None:
    tool_name = (request.headers.get(MCP_TOOL_HEADER) or "").strip()
    if tool_name not in TOOL_POLICIES:
        return None
    return tool_name


def record_mcp_audit(
    request: Request,
    *,
    actor: AccessIdentity | None,
    success: bool,
    dataset: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    tool_name = mcp_tool_name(request)
    if not tool_name:
        return
    policy = TOOL_POLICIES[tool_name]
    event_detail: dict[str, Any] = {
        "surface": "mcp",
        "tool": tool_name,
        "method": request.method,
        "path": request.url.path,
        "required_role": policy.role,
        "required_scope": policy.scope,
        "risk": policy.risk,
    }
    if detail:
        event_detail.update(detail)
    get_access_store().record_event(
        action=f"mcp.{tool_name}",
        actor=actor,
        success=success,
        dataset=dataset,
        detail=event_detail,
    )
    request.state.mcp_audit_recorded = True


def is_mcp_audit_event(event: dict[str, Any]) -> bool:
    detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
    return str(event.get("action") or "").startswith("mcp.") or detail.get("surface") == "mcp"


def audit_events_for_view(events: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
    if view == "all":
        return list(events)
    if view == "mcp":
        return [event for event in events if is_mcp_audit_event(event)]
    if view == "access":
        return [event for event in events if not is_mcp_audit_event(event)]
    if view == "failures":
        return [event for event in events if event.get("success") is False]
    raise HTTPException(status_code=422, detail=f"Unsupported audit view: {view}.")


def audit_actor_key(event: dict[str, Any]) -> str | None:
    for key in ("actor_id", "actor_name"):
        value = event.get(key)
        if value:
            return str(value)
    return None


def audit_summary(
    *,
    all_events: list[dict[str, Any]],
    returned_events: list[dict[str, Any]],
) -> dict[str, int]:
    mcp_events = [event for event in all_events if is_mcp_audit_event(event)]
    failure_events = [event for event in all_events if event.get("success") is False]
    mcp_failures = [event for event in mcp_events if event.get("success") is False]
    mcp_actors = {actor for event in mcp_events if (actor := audit_actor_key(event))}
    return {
        "total_events": len(all_events),
        "returned_events": len(returned_events),
        "mcp_events": len(mcp_events),
        "access_events": len(all_events) - len(mcp_events),
        "failure_events": len(failure_events),
        "mcp_failures": len(mcp_failures),
        "mcp_actors": len(mcp_actors),
    }


def audit_limit_value(limit: int | None) -> int | None:
    if limit is None:
        return None
    if limit < 1 or limit > AUDIT_LIMIT_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"Audit limit must be between 1 and {AUDIT_LIMIT_MAX}.",
        )
    return limit


def enforce_ingest_size(text: str) -> None:
    """Reject oversized write payloads at the HTTP boundary.

    Mirrors the MCP write tools' byte cap (kb.mcp_server._validate_ingest_size) so a
    direct HTTP caller (or autosync) that bypasses the MCP layer cannot push an
    unbounded body into seat-scoped storage. Shares the MCP limit/env so the two
    surfaces never drift.
    """
    max_bytes = _max_ingest_bytes()
    byte_count = len(text.encode("utf-8"))
    if byte_count > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Payload is {byte_count} bytes; limit is {max_bytes} bytes.",
        )


def known_datasets(config: Any) -> list[str]:
    """Datasets a caller can target, in preference order, deduplicated."""
    ordered: list[str] = []
    for dataset in (config.search_default_dataset, config.github_sync_dataset, config.default_dataset):
        if dataset and dataset not in ordered:
            ordered.append(dataset)
    return ordered


def string_value(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def first_string(*values: Any) -> str | None:
    for value in values:
        normalized = string_value(value)
        if normalized:
            return normalized
    return None


def result_provenance(result: dict[str, Any]) -> dict[str, str]:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    provenance = {
        "source": first_string(
            result.get("source"),
            result.get("source_type"),
            metadata.get("source"),
            metadata.get("source_type"),
        ),
        "source_url": first_string(
            result.get("source_url"),
            result.get("url"),
            result.get("uri"),
            metadata.get("source_url"),
            metadata.get("url"),
            metadata.get("uri"),
        ),
        "path": first_string(
            result.get("path"),
            result.get("normalized_path"),
            metadata.get("path"),
            metadata.get("normalized_path"),
        ),
        "title": first_string(result.get("title"), metadata.get("title")),
        "session_id": first_string(result.get("session_id"), metadata.get("session_id")),
    }
    return {key: value for key, value in provenance.items() if value}


def document_endpoint_for_result(result_id: str) -> str | None:
    if result_id.startswith(f"{GITHUB_DOC_ID_PREFIX}:") or result_id.startswith("doc_"):
        return f"/api/documents/{result_id}"
    return None


def result_content_sha256(result: dict[str, Any]) -> str:
    content_basis = {key: value for key, value in result.items() if key != "_citadel"}
    encoded = json.dumps(content_basis, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def with_result_id(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure a search result dict carries a stable ``id`` for drill-down.

    Results that already supply an id (e.g. the GitHub digest fallback) are left
    untouched. Other dict results get a content-derived id for traceability.
    """
    if result.get("id"):
        return result
    basis = json.dumps(result, sort_keys=True, default=str)
    derived = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return {"id": f"chunk:{derived}", **result}


def with_result_metadata(result: Any, index: int, dataset: str) -> Any:
    """Attach a reserved Citadel provenance envelope to dict search results."""
    if not isinstance(result, dict):
        return result
    normalized = with_result_id(result)
    result_id = str(normalized["id"])
    document_endpoint = document_endpoint_for_result(result_id)
    metadata: dict[str, Any] = {
        "rank": index + 1,
        "dataset": dataset,
        "result_id": result_id,
        "content_sha256": result_content_sha256(normalized),
        "provenance": result_provenance(normalized),
        "retrieval": {
            "untrusted_context": True,
            "citation_required": True,
            "document_drilldown_available": bool(document_endpoint),
        },
    }
    if document_endpoint:
        metadata["document_endpoint"] = document_endpoint
    return {**normalized, "_citadel": metadata}


def public_base_url(request: Request) -> str:
    configured = os.getenv("CITADEL_PUBLIC_BASE_URL") or os.getenv("CITADEL_HTTP_BASE_URL")
    if configured:
        return configured.rstrip("/")

    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_host and forwarded_proto:
        host = forwarded_host.split(",", 1)[0].strip()
        proto = forwarded_proto.split(",", 1)[0].strip().lower()
        if host and PUBLIC_HOST_RE.fullmatch(host) and proto in {"http", "https"}:
            return f"{proto}://{host}".rstrip("/")

    return str(request.base_url).rstrip("/")


def request_is_https(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
    return request.url.scheme == "https"


def public_cacheable_path(path: str) -> bool:
    return path in PUBLIC_CACHE_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_CACHE_PREFIXES)


def public_skill_rows(request: Request) -> list[dict[str, Any]]:
    base = public_base_url(request)
    return [
        {
            **entry,
            "url": f"{base}/skills/{entry['slug']}",
        }
        for entry in skill_catalog()
    ]


def public_mcp_tool_rows() -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "role": policy.role,
            "scope": policy.scope,
            "risk": policy.risk,
        }
        for name, policy in sorted(TOOL_POLICIES.items())
    ]


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if "cache-control" not in response.headers:
        cache_headers = PUBLIC_CACHE_HEADERS if public_cacheable_path(request.url.path) else PRIVATE_CACHE_HEADERS
        for header, value in cache_headers.items():
            response.headers.setdefault(header, value)
    if request_is_https(request):
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


@app.middleware("http")
async def audit_forwarded_mcp_call(request: Request, call_next: Any) -> Response:
    if not mcp_tool_name(request):
        return await call_next(request)

    try:
        response = await call_next(request)
    except Exception as exc:
        if not getattr(request.state, "mcp_audit_recorded", False):
            record_mcp_audit(
                request,
                actor=request_identity(request),
                success=False,
                detail={"error_type": exc.__class__.__name__},
            )
        raise

    if not getattr(request.state, "mcp_audit_recorded", False):
        record_mcp_audit(
            request,
            actor=request_identity(request),
            success=response.status_code < 400,
            detail={"status_code": response.status_code},
        )
    return response


@app.get("/", include_in_schema=False)
async def ui(request: Request) -> Response:
    if not session_role(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def login() -> HTMLResponse:
    return HTMLResponse(LOGIN_HTML)


@app.post("/admin/session")
async def create_admin_session(body: AdminSessionBody, response: Response) -> dict[str, Any]:
    access_key = body.access_key or body.admin_key
    if not configured_access_keys() and not get_access_store().has_tokens():
        raise HTTPException(status_code=503, detail="Access keys are not configured.")
    if not access_key:
        raise HTTPException(status_code=422, detail="Access key is required.")
    identity_with_cookie = access_key_identity(access_key)
    if not identity_with_cookie:
        logger.warning("Admin session login rejected: access key did not match any credential")
        raise HTTPException(status_code=401, detail="Access key was rejected.")
    identity, session_cookie = identity_with_cookie
    response.set_cookie(
        ADMIN_COOKIE,
        session_cookie,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return {"ok": True, **role_payload(identity.role, identity)}


@app.post("/admin/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(ADMIN_COOKIE)
    return {"ok": True}


@app.get("/api/session")
async def current_session(request: Request) -> dict[str, Any]:
    identity = require_access(request, "reader", "kb:read")
    record_mcp_audit(
        request,
        actor=identity,
        success=True,
        detail={"role": identity.role},
    )
    return {"ok": True, **role_payload(identity.role, identity)}


@app.get("/api/access")
async def access_snapshot(request: Request) -> dict[str, Any]:
    require_access(request, "admin", "access:manage")
    bootstrap_counts = {"reader": 0, "writer": 0, "admin": 0}
    for role, _ in configured_access_keys():
        bootstrap_counts[role] += 1
    return {
        "ok": True,
        "bootstrap_keys": bootstrap_counts,
        **get_access_store().snapshot(),
    }


@app.get("/api/audit")
async def audit_snapshot(
    request: Request,
    view: str = "all",
    limit: int | None = None,
) -> dict[str, Any]:
    require_access(request, "admin", "audit:read")
    if view not in AUDIT_VIEWS:
        raise HTTPException(status_code=422, detail=f"Unsupported audit view: {view}.")
    limit = audit_limit_value(limit)
    events = get_access_store().snapshot()["audit_events"]
    filtered_events = audit_events_for_view(events, view)
    returned_events = filtered_events[-limit:] if limit is not None else filtered_events
    return {
        "ok": True,
        "view": view,
        "audit_events": returned_events,
        "summary": audit_summary(all_events=events, returned_events=returned_events),
    }


@app.get("/api/access/seats")
async def list_access_seats(request: Request) -> dict[str, Any]:
    require_access(request, "admin", "access:manage")
    snapshot = get_access_store().snapshot()
    tokens_by_principal: dict[str, list[dict[str, Any]]] = {}
    for token in snapshot["tokens"]:
        tokens_by_principal.setdefault(token["principal_id"], []).append(token)
    seats: list[dict[str, Any]] = []
    # A seat is a principal that carries a seat_slug; derive the list purely from
    # the existing snapshot (no new store schema), joining each seat to its tokens.
    for principal in snapshot["principals"]:
        if not principal.get("seat_slug"):
            continue
        seat_tokens = sorted(
            tokens_by_principal.get(principal["id"], []),
            key=lambda token: token.get("created_at") or "",
        )
        token_rows = [
            {
                "id": token["id"],
                "name": token["name"],
                "role": token["role"],
                # prefix is the masked, non-secret head already stored at rest.
                "prefix": token["prefix"],
                "revoked": bool(token.get("revoked_at")),
                "revoked_at": token.get("revoked_at"),
                "last_used_at": token.get("last_used_at"),
                "created_at": token.get("created_at"),
            }
            for token in seat_tokens
        ]
        active_tokens = sum(1 for token in token_rows if not token["revoked"])
        seats.append(
            {
                "principal_id": principal["id"],
                "name": principal["name"],
                "seat_slug": principal["seat_slug"],
                "node_dataset": principal.get("default_dataset"),
                "email": principal.get("email"),
                "role": principal["role"],
                "disabled": bool(principal.get("disabled_at")),
                "active_token_count": active_tokens,
                "token_count": len(token_rows),
                "tokens": token_rows,
            }
        )
    seats.sort(key=lambda seat: seat["seat_slug"])
    return {"ok": True, "seats": seats}


@app.post("/api/access/seats")
async def create_access_seat(body: CreateSeatBody, request: Request) -> dict[str, Any]:
    actor = require_access(request, "admin", "access:manage")
    try:
        created = get_access_store().create_seat(
            name=body.name,
            slug=body.slug,
            email=body.email,
            role=body.role,
            issue_token=body.issue_token,
            token_name=body.token_name,
            central_dataset=central_dataset(get_citadel().config),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    get_access_store().record_event(
        action="access.seat.create",
        actor=actor,
        success=True,
        dataset=created.principal.default_dataset,
        detail={
            "principal_id": created.principal.id,
            "seat_slug": created.principal.seat_slug,
            "token_id": created.api_token.id if created.api_token else None,
            "role": created.principal.role,
        },
    )
    payload: dict[str, Any] = {
        "ok": True,
        "principal": jsonable_encoder(created.principal),
    }
    if created.token and created.api_token:
        payload["token"] = created.token
        payload["api_token"] = jsonable_encoder(
            {key: value for key, value in created.api_token.__dict__.items() if key != "token_hash"}
        )
    return payload


@app.post("/api/access/seats/{slug}/tokens")
async def issue_access_seat_token(
    slug: str, body: IssueSeatTokenBody, request: Request
) -> dict[str, Any]:
    """Mint a fresh token for an EXISTING seat (e.g. to re-link a lost token)."""
    actor = require_access(request, "admin", "access:manage")
    try:
        normalized = validate_seat_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store = get_access_store()
    if not store.find_seat_by_slug(normalized):
        raise HTTPException(status_code=404, detail=f"Seat not found: {normalized}")
    try:
        created = store.issue_seat_token(
            slug=normalized,
            token_name=body.token_name,
            central_dataset=central_dataset(get_citadel().config),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.record_event(
        action="access.seat.token.create",
        actor=actor,
        success=True,
        dataset=created.api_token.default_dataset,
        detail={
            "principal_id": created.principal.id,
            "seat_slug": normalized,
            "token_id": created.api_token.id,
        },
    )
    return {
        "ok": True,
        "token": created.token,
        "principal": jsonable_encoder(created.principal),
        "api_token": jsonable_encoder(
            {key: value for key, value in created.api_token.__dict__.items() if key != "token_hash"}
        ),
    }


@app.get("/api/access/capture-baseline")
async def org_capture_baseline(request: Request) -> dict[str, Any]:
    require_access(request, "admin", "access:manage")
    return capture_policy_payload(
        seat_slug=None,
        baseline=SeatCapturePolicy(),
        env_exclude_patterns=env_exclude_patterns(),
    )


@app.get("/api/access/seats/{slug}/capture-policy")
async def get_seat_capture_policy(slug: str, request: Request) -> dict[str, Any]:
    require_capture_policy_read(request, slug)
    return seat_capture_policy_response(slug)


@app.put("/api/access/seats/{slug}/capture-policy")
async def update_seat_capture_policy(
    slug: str,
    body: CapturePolicyBody,
    request: Request,
) -> dict[str, Any]:
    actor = require_access(request, "admin", "access:manage")
    try:
        normalized = validate_seat_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store = get_access_store()
    seat = store.find_seat_by_slug(normalized)
    if not seat:
        raise HTTPException(status_code=404, detail=f"Seat not found: {normalized}")
    try:
        baseline = store.set_capture_policy(
            normalized,
            deny_globs=body.deny_globs,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.record_event(
        action="access.capture_policy.update",
        actor=actor,
        success=True,
        dataset=seat.default_dataset,
        detail={
            "seat_slug": normalized,
            "deny_glob_count": len(baseline.deny_globs),
        },
    )
    return capture_policy_payload(
        seat_slug=normalized,
        baseline=baseline,
        env_exclude_patterns=env_exclude_patterns(),
    )


@app.post("/api/access/tokens")
async def create_access_token(body: AccessTokenBody, request: Request) -> dict[str, Any]:
    actor = require_access(request, "admin", "access:manage")
    try:
        created = get_access_store().create_principal_token(
            name=body.name,
            kind=body.kind,
            role=body.role,
            scopes=body.scopes,
            team_id=body.team_id,
            expires_at=body.expires_at,
            default_dataset=body.default_dataset,
            default_session=body.default_session,
            allowed_datasets=body.allowed_datasets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    get_access_store().record_event(
        action="access.token.create",
        actor=actor,
        success=True,
        detail={
            "principal_id": created.principal.id,
            "token_id": created.api_token.id,
            "role": created.api_token.role,
            "kind": created.principal.kind,
        },
    )
    return {
        "ok": True,
        "token": created.token,
        "principal": jsonable_encoder(created.principal),
        "api_token": jsonable_encoder(
            {key: value for key, value in created.api_token.__dict__.items() if key != "token_hash"}
        ),
    }


@app.post("/api/access/tokens/{token_id}/revoke")
async def revoke_access_token(token_id: str, request: Request) -> dict[str, Any]:
    actor = require_access(request, "admin", "access:manage")
    revoked = get_access_store().revoke_token(token_id)
    if not revoked:
        get_access_store().record_event(
            action="access.token.revoke",
            actor=actor,
            success=False,
            detail={"token_id": token_id, "reason": "not_found"},
        )
        raise HTTPException(status_code=404, detail="Token not found.")
    get_access_store().record_event(
        action="access.token.revoke",
        actor=actor,
        success=True,
        detail={"token_id": token_id},
    )
    redacted = {key: value for key, value in revoked.__dict__.items() if key != "token_hash"}
    return {"ok": True, "api_token": jsonable_encoder(redacted)}


@app.get("/healthz")
async def healthz() -> dict[str, str | bool]:
    return {"ok": True, "service": "citadel"}


@app.get("/.well-known/citadel.json")
async def citadel_discovery_manifest(request: Request, response: Response) -> dict[str, Any]:
    """Public agent discovery document with no vault content or secrets."""
    response.headers.update(PUBLIC_CACHE_HEADERS)
    base = public_base_url(request)
    tools = public_mcp_tool_rows()
    return {
        "ok": True,
        "service": {
            "name": "Citadel Archive",
            "kind": "organization_vault",
            "version": app.version,
            "base_url": base,
        },
        "public_endpoints": {
            "health": f"{base}/healthz",
            "skills": f"{base}/skills",
            "discovery": f"{base}/.well-known/citadel.json",
        },
        "mcp": {
            "endpoint": f"{base}{MCP_ENDPOINT_PATH}",
            "transport": "streamable_http",
            "authentication": {
                "required": True,
                "scheme": "bearer",
                "token_prefix": "ctdl_",
                "header": "Authorization",
            },
            "tools": tools,
            "approval_recommended_for": [
                row["name"]
                for row in tools
                if row["risk"] in {"additive_write", "admin_job"}
            ],
            "audit": {
                "event_action": "mcp.<tool_name>",
                "admin_tool": "citadel_audit_events",
            },
        },
        "skills": public_skill_rows(request),
        "security": {
            "public_data": [
                "application code and documentation",
                "hosted skill markdown and content hashes",
                "MCP endpoint URL and tool policy metadata",
            ],
            "private_data": [
                "ctdl_ access tokens",
                "vault search results and source documents",
                "Obsidian sync contents",
                "backup mirror repository contents",
            ],
            "token_handling": [
                "give each human or agent a distinct token",
                "store tokens only in local secret stores or environment variables",
                "rotate any token pasted into chat, logs, issues, pull requests, or public repos",
            ],
            "scope_model": {
                "roles": ["reader", "writer", "admin"],
                "custom_scopes": "Custom scopes can only reduce permissions within the selected role.",
            },
            "seat_mcp_write_policy": {
                "personal_node_only": True,
                "central_read_only_for_seats": True,
                "contribute_via_mcp": False,
                "secret_scan_on_all_writes": True,
                "client_must_require_user_approval_for": [
                    "citadel_ingest",
                    "citadel_contribute",
                    "citadel_record_feedback",
                ],
                "central_updates_via": [
                    "github_sync_cron",
                    "linear_sync_cron",
                    "promotion_engine",
                    "curated_contribute_non_mcp",
                ],
            },
        },
    }


@app.get("/skills")
async def list_skills(request: Request) -> dict[str, Any]:
    """Public index of shareable agent skill URLs (no auth)."""
    return {"ok": True, "skills": public_skill_rows(request)}


@app.get("/skills/{slug}")
async def get_skill(slug: str) -> FileResponse:
    """Serve a bundled agent skill as markdown (no auth)."""
    path = skill_path(slug)
    if path is None:
        raise HTTPException(status_code=404, detail="Unknown skill")
    integrity = skill_integrity(path)
    headers = {
        **PUBLIC_CACHE_HEADERS,
        "ETag": f"\"sha256-{integrity['sha256']}\"",
        "X-Citadel-Skill-SHA256": str(integrity["sha256"]),
        "X-Citadel-Skill-Integrity": str(integrity["integrity"]),
    }
    return FileResponse(path, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, Any]:
    require_access(request, "reader", "kb:read")
    config = get_citadel().config
    return {
        "ok": True,
        "service": "citadel",
        "tenant_id": config.tenant_id,
        "default_dataset": config.default_dataset,
        "auto_improve": config.auto_improve,
        "build_global_context_index": config.build_global_context_index,
    }


@app.get("/api/mesh")
async def mesh(request: Request) -> Any:
    require_access(request, "reader", "kb:read")
    citadel = get_citadel()
    return jsonable_encoder(await get_mesh().snapshot(citadel.config))


@app.get("/api/knowledge/events")
async def knowledge_events(
    request: Request,
    after_id: int | None = None,
    limit: int = 50,
    event_type: str | None = Query(default=None, alias="type"),
    kind: str | None = None,
) -> Any:
    require_access(request, "reader", "kb:read")
    if after_id is not None and after_id < 0:
        raise HTTPException(status_code=422, detail="after_id must be zero or greater.")
    if not 1 <= limit <= 160:
        raise HTTPException(status_code=422, detail="Timeline limit must be between 1 and 160.")
    timeline = await get_mesh().timeline(
        after_id=after_id,
        limit=limit,
        event_type=event_type,
        kind=kind,
    )
    return jsonable_encoder({"ok": True, **timeline})


@app.get("/api/mesh/graph")
async def mesh_graph(request: Request, limit: int | None = None) -> Any:
    """The real Knowledge Mesh graph from Cognee (not the dashboard projection).

    Never fails hard: returns an empty graph with ``fallback: true`` when
    Cognee has no data or graph access is unavailable.
    """
    require_access(request, "reader", "kb:search")
    if limit is not None and not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="Graph limit must be between 1 and 1000.")
    effective_limit = limit or get_citadel().config.mesh_graph_max_nodes
    graph = await get_knowledge_mesh().graph(limit=effective_limit)
    return jsonable_encoder({**graph, "limit": effective_limit})


@app.get("/api/conflicts")
async def list_knowledge_conflicts(request: Request, status: str | None = None) -> Any:
    actor = require_access(request, "reader", "kb:read")
    if status not in {None, "open", "resolved"}:
        raise HTTPException(status_code=422, detail="Unsupported conflict status filter.")
    store = get_conflict_store()
    conflicts = store.list(status=status)
    get_access_store().record_event(
        action="conflicts.list",
        actor=actor,
        success=True,
        detail={"status": status or "all", "returned": len(conflicts)},
    )
    return {
        "ok": True,
        "status": status or "all",
        "conflicts": jsonable_encoder(conflicts),
        "open_count": store.open_count(),
    }


@app.post("/api/conflicts/{conflict_id}/resolve")
async def resolve_knowledge_conflict(
    conflict_id: str,
    body: KnowledgeConflictResolveBody,
    request: Request,
) -> Any:
    actor = require_access(request, "writer", "kb:ingest")
    try:
        resolved = get_conflict_store().resolve(
            conflict_id,
            resolution_note=body.resolution_note,
            resolved_by=actor.actor_id,
        )
    except KeyError as exc:
        get_access_store().record_event(
            action="conflicts.resolve",
            actor=actor,
            success=False,
            detail={"conflict_id": conflict_id, "reason": "not_found"},
        )
        raise HTTPException(status_code=404, detail="Conflict not found.") from exc
    get_access_store().record_event(
        action="conflicts.resolve",
        actor=actor,
        success=True,
        detail={"conflict_id": conflict_id, "kind": resolved.get("kind")},
    )
    return {"ok": True, "conflict": jsonable_encoder(resolved)}


@app.get("/api/indexes")
async def indexes(request: Request) -> Any:
    require_access(request, "reader", "kb:read")
    citadel = get_citadel()
    snapshot = await get_mesh().snapshot(citadel.config)
    return jsonable_encoder({"indexes": snapshot["indexes"], "stats": snapshot["stats"]})


@app.get("/api/github-sync")
async def github_sync_status(request: Request) -> Any:
    require_access(request, "reader", "sources:read")
    return jsonable_encoder(await get_github_syncer().status())


@app.get("/api/repo-content-sync")
async def repo_content_sync_status(request: Request) -> Any:
    require_access(request, "reader", "sources:read")
    return jsonable_encoder(await get_repo_content_syncer().status())


@app.get("/api/sources")
async def sources(request: Request, type: str | None = None) -> Any:
    require_access(request, "reader", "sources:read")
    sources_payload: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    if type in {None, "github"}:
        github_status = await get_github_syncer().status()
        sources_payload.append(
            {
                "id": "github-org",
                "source_type": "github",
                "name": github_status.get("org"),
                "status": "tracked" if github_status.get("last_checked_at") else "ready",
                "url": github_status.get("source_url"),
                "last_checked_at": github_status.get("last_checked_at"),
                "documents": github_status.get("tracked_repositories", 0),
                "open_conflicts": 0,
                "metadata": github_status,
            }
        )
        summary["github_repositories"] = github_status.get("tracked_repositories", 0)

    if type in {None, "github_repo_content"}:
        repo_content_status = await get_repo_content_syncer().status()
        sources_payload.append(
            {
                "id": "github-repo-content",
                "source_type": "github_repo_content",
                "name": repo_content_status.get("org"),
                "status": "tracked" if repo_content_status.get("last_checked_at") else "ready",
                "last_checked_at": repo_content_status.get("last_checked_at"),
                "documents": repo_content_status.get("tracked_files", 0),
                "open_conflicts": 0,
                "metadata": repo_content_status,
            }
        )
        summary["repo_content_files"] = repo_content_status.get("tracked_files", 0)

    if type in {None, "linear"}:
        linear_status = await get_linear_syncer().status()
        sources_payload.append(
            {
                "id": "linear-workspace",
                "source_type": "linear",
                "name": "Linear workspace",
                "status": "tracked" if linear_status.get("last_synced_at") else "ready",
                "last_checked_at": linear_status.get("last_synced_at"),
                "documents": linear_status.get("issue_count", 0),
                "open_conflicts": 0,
                "metadata": linear_status,
            }
        )
        summary["linear_issues"] = linear_status.get("issue_count", 0)

    if type in {None, "obsidian_vault"}:
        obsidian_status = get_obsidian_sync().source_status(source_type="obsidian_vault")
        sources_payload.extend(obsidian_status["sources"])
        summary.update(obsidian_status["summary"])

    if type not in {None, "github", "github_repo_content", "linear", "obsidian_vault"}:
        raise HTTPException(status_code=422, detail="Unsupported source type.")

    return {"ok": True, "sources": sources_payload, "summary": summary}


@app.post("/api/github-sync/run")
async def run_github_sync(body: GitHubSyncBody, request: Request) -> Any:
    require_access(request, "admin", "sources:sync")
    citadel = get_citadel()
    mesh_state = get_mesh()
    try:
        result = await get_github_syncer().run(force=body.force)
    except Exception as exc:  # pragma: no cover - depends on GitHub and runtime Cognee config.
        logger.error("GitHub sync run failed: %s", exc.__class__.__name__)
        await mesh_state.record_error(citadel.config, operation="github_sync", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await mesh_state.record_github_sync(citadel.config, result)
    return jsonable_encoder(result)


def verify_github_signature(secret: str, body: bytes, signature_header: str) -> bool:
    """Constant-time check of GitHub's ``X-Hub-Signature-256`` over the raw body.

    GitHub signs the request body with HMAC-SHA256 keyed by the shared webhook
    secret and sends ``sha256=<hexdigest>``. A missing/empty/malformed header, an
    empty secret, or any mismatch returns ``False``. The body is UNTRUSTED; this
    runs before any parsing.
    """
    if not secret or not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    provided = signature_header[len(prefix):]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def webhook_identity(dataset: str) -> AccessIdentity:
    """Synthetic service-account identity for auditing accepted webhook triggers."""
    return AccessIdentity(
        role="admin",
        actor_id="github-webhook",
        actor_kind="service_account",
        actor_name="github-webhook",
        source="env",
        default_dataset=dataset,
    )


async def _run_webhook_reingest(syncer: GitHubOrgSyncer) -> None:
    """Background org re-ingest kicked off by an accepted PR-merge webhook.

    Fire-and-forget: the webhook returns 202 immediately (GitHub times out in
    seconds; the full sync is ~26min) and this runs detached. Never raises.
    """
    try:
        await syncer.run(force=True)
    except Exception as exc:  # pragma: no cover - depends on GitHub + Cognee runtime.
        logger.error(
            "GitHub webhook re-ingest failed: %s: %s",
            exc.__class__.__name__,
            exc,
        )
        await get_mesh().record_error(
            get_citadel().config, operation="github_sync", error=str(exc)
        )


@app.post("/api/webhooks/github")
async def github_webhook(request: Request) -> Response:
    """GitHub PR-merge webhook -> non-blocking org re-ingest (ADR-0005 step 3).

    Gated off by default (``github_webhook_enabled`` -> 404 when disabled). The
    raw body is verified against ``X-Hub-Signature-256`` BEFORE parsing and is
    treated as untrusted. An invalid/missing signature -> 401. Only a closed,
    merged ``pull_request`` event triggers work (returns 202); everything else
    (ping, other events, non-merge closes) is acknowledged with 204 and no work.
    """
    config = get_citadel().config
    if not config.github_webhook_enabled:
        raise HTTPException(status_code=404, detail="Not found.")

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_github_signature(config.github_webhook_secret, body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature.")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return Response(status_code=204)

    try:
        payload = json.loads(body or b"{}")
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    pull_request = payload.get("pull_request")
    merged = isinstance(pull_request, dict) and pull_request.get("merged") is True
    if payload.get("action") != "closed" or not merged:
        return Response(status_code=204)

    repository = payload.get("repository")
    repo_full_name = repository.get("full_name") if isinstance(repository, dict) else None
    task = asyncio.create_task(_run_webhook_reingest(get_github_syncer()))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    get_access_store().record_event(
        action="github_webhook.merge",
        actor=webhook_identity(config.github_sync_dataset),
        success=True,
        dataset=config.github_sync_dataset,
        detail={
            "event": event,
            "action": "closed",
            "merged": True,
            "pr_number": pull_request.get("number"),
            "repository": repo_full_name,
            "triggered": "github_sync",
        },
    )
    return Response(status_code=202)


@app.get("/api/linear-sync")
async def linear_sync_status(request: Request) -> Any:
    require_access(request, "reader", "sources:read")
    return jsonable_encoder(await get_linear_syncer().status())


@app.get("/api/linear-sync/issues")
async def linear_sync_issues(
    request: Request,
    scope: str = Query(default="my", pattern="^(my|org)$"),
) -> dict[str, Any]:
    identity = require_access(request, "reader", "kb:read")
    syncer = get_linear_syncer()
    seat_dataset_name = identity.default_dataset if is_seat_dataset(identity.default_dataset) else None
    if scope == "my" and not seat_dataset_name:
        return {"ok": True, "scope": scope, "issues": [], "count": 0}
    issues = syncer.issues_for_scope(scope=scope, seat_dataset_name=seat_dataset_name)
    return {"ok": True, "scope": scope, "issues": issues, "count": len(issues)}


@app.post("/api/linear-sync/run")
async def run_linear_sync(body: LinearSyncBody, request: Request) -> Any:
    require_access(request, "admin", "sources:sync")
    citadel = get_citadel()
    mesh_state = get_mesh()
    try:
        result = await get_linear_syncer().run(force=body.force)
    except Exception as exc:  # pragma: no cover - depends on Linear API and runtime Cognee config.
        logger.error("Linear sync run failed: %s", exc.__class__.__name__)
        await mesh_state.record_error(citadel.config, operation="linear_sync", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("reason", "Linear sync unavailable"))
    return jsonable_encoder(result)


@app.post("/api/repo-content-sync/run")
async def run_repo_content_sync(body: RepoContentSyncBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    citadel = get_citadel()
    mesh_state = get_mesh()
    try:
        result = await get_repo_content_syncer().run(force=body.force, dry_run=body.dry_run)
    except Exception as exc:  # pragma: no cover - depends on GitHub and runtime Cognee config.
        logger.error("Repo content sync run failed: %s", exc.__class__.__name__)
        await mesh_state.record_error(
            citadel.config,
            operation="repo_content_sync",
            error=str(exc),
        )
        get_access_store().record_event(
            action="repo_content_sync.run",
            actor=actor,
            success=False,
            detail={
                "force": body.force,
                "dry_run": body.dry_run,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not body.dry_run and result.get("enabled") is not False:
        await mesh_state.record_repo_content_sync(citadel.config, result)
    get_access_store().record_event(
        action="repo_content_sync.run",
        actor=actor,
        success=True,
        detail={
            "force": body.force,
            "dry_run": body.dry_run,
            "files_ingested": result.get("files_ingested"),
            "files_skipped": result.get("files_skipped"),
            "improved": result.get("improved"),
        },
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=citadel.config.repo_content_sync_dataset,
        detail={
            "operation": "repo_content_sync.run",
            "force": body.force,
            "dry_run": body.dry_run,
            "files_ingested": result.get("files_ingested"),
            "files_skipped": result.get("files_skipped"),
        },
    )
    return jsonable_encoder(result)


@app.post("/api/obsidian/vaults")
async def register_obsidian_vault(body: ObsidianVaultBody, request: Request) -> Any:
    actor = require_access(request, "writer", "obsidian:sync:push")
    vault_name = body.vault_name or body.name
    if not vault_name:
        raise HTTPException(status_code=422, detail="Vault name is required.")
    try:
        vault = get_obsidian_sync().register_vault(
            name=vault_name,
            team_id=body.team_id,
            plugin_version=body.plugin_version,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    get_access_store().record_event(
        action="obsidian.vault.register",
        actor=actor,
        success=True,
        detail={"vault_id": vault.id, "team_id": body.team_id},
    )
    return {"ok": True, "vault": jsonable_encoder(vault)}


@app.get("/api/obsidian/manifest")
async def obsidian_manifest(request: Request, vault_id: str, cursor: int | None = None) -> Any:
    require_access(request, "reader", "obsidian:sync:pull")
    try:
        manifest = get_obsidian_sync().manifest(vault_id=vault_id, cursor=cursor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vault not found.") from exc
    return {"ok": True, **jsonable_encoder(manifest)}


@app.post("/api/obsidian/sync/push")
async def push_obsidian_sync(body: ObsidianPushBody, request: Request) -> Any:
    actor = require_access(request, "writer", "obsidian:sync:push")
    citadel = get_citadel()
    mesh_state = get_mesh()
    push_dataset = resolve_write_dataset(actor, body.dataset, citadel.config)
    push_session_id = resolve_session_id(actor, body.session_id)
    push_documents = [
        SyncPushDocument(
            path=document.path,
            content=document.content,
            base_rev=document.base_rev,
            deleted=document.deleted,
            tags=tuple(document.tags),
            dataset=document.dataset,
        )
        for document in body.documents
    ]
    try:
        result = get_obsidian_sync().push(
            vault_id=body.vault_id,
            actor=actor,
            documents=push_documents,
            dataset=push_dataset,
        )
        manifest = get_obsidian_sync().manifest(vault_id=body.vault_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vault not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    documents_by_path = {}
    for document in body.documents:
        try:
            documents_by_path[normalize_path(document.path)] = document
        except ValueError:
            continue

    learning = get_learning_process()
    ingest_results: list[dict[str, Any]] = []
    written_datasets: set[str] = set()
    for accepted in result["accepted"]:
        if accepted.get("deleted"):
            continue
        source_document = documents_by_path.get(accepted["path"])
        if not source_document:
            continue
        document_tags = seat_safe_tags(
            actor,
            [*body.tags, *source_document.tags, "obsidian", "obsidian_vault"],
        )
        document_targets = resolve_write_targets(
            actor,
            source_document.dataset or body.dataset,
            document_tags,
            citadel.config,
        )
        # Enforce the same byte cap as /ingest and /api/contribute on the per-document
        # obsidian write path (#51): an oversized note is rejected individually so it
        # cannot bloat the index, without failing the rest of the vault sync.
        try:
            enforce_ingest_size(source_document.content)
        except HTTPException as exc:
            ingest_results.append(
                {
                    "document_id": accepted["document_id"],
                    "accepted": False,
                    "reason": exc.detail,
                    "dataset": document_targets[0].dataset,
                    "tags": list(document_tags),
                }
            )
            continue
        try:
            outcome, _ = await execute_learning_writes(
                learning,
                data=source_document.content,
                targets=document_targets,
                tags=document_tags,
                session_id=push_session_id,
                operation="obsidian_sync",
                detect_conflicts=False,
            )
        except SecretContentError as exc:
            get_access_store().record_event(
                action="obsidian_sync",
                actor=actor,
                success=False,
                dataset=document_targets[0].dataset,
                detail={
                    "operation": "obsidian_sync",
                    "blocked": "secret_content",
                    "highest_severity": exc.highest_severity,
                    "finding_count": len(exc.findings),
                },
            )
            raise HTTPException(status_code=422, detail=exc.public_message) from exc
        except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        ingest_result = outcome.ingest
        ingest_results.append(
            {
                "document_id": accepted["document_id"],
                "accepted": ingest_result.accepted,
                "reason": ingest_result.reason,
                "dataset": ingest_result.dataset,
                "tags": list(ingest_result.tags),
            }
        )
        # A promotion writes more than the primary outcome's dataset, so record
        # every target (node + Central) for an accurate audit trail.
        written_datasets.update(target.dataset for target in document_targets)

    # Keep every push conflict visible as a Knowledge Conflict (never silently
    # overwritten) and surface detection in the activity stream.
    conflict_store = get_conflict_store()
    for sync_conflict in result["conflicts"]:
        conflict_record = conflict_store.record(
            obsidian_push_conflict_candidate(
                sync_conflict,
                vault_name=manifest["vault"].get("name"),
            )
        )
        await mesh_state.record_conflict(citadel.config, conflict=conflict_record)

    await mesh_state.record_obsidian_sync(
        citadel.config,
        vault=manifest["vault"],
        result=result,
        dataset=push_dataset,
    )
    get_access_store().record_event(
        action="obsidian.sync.push",
        actor=actor,
        success=True,
        dataset=push_dataset,
        detail={
            "vault_id": body.vault_id,
            "accepted": len(result["accepted"]),
            "skipped": len(result["skipped"]),
            "conflicts": len(result["conflicts"]),
            # push_dataset is the vault's home binding; tag routing can additionally
            # land a note in Central (and a promotion dual-writes node + Central),
            # so record every dataset that actually received content.
            "written_datasets": sorted(written_datasets),
        },
    )
    return {"ok": True, **jsonable_encoder(result), "ingest_results": ingest_results}


@app.get("/api/obsidian/sync/pull")
async def pull_obsidian_sync(request: Request, vault_id: str, cursor: int | None = None) -> Any:
    require_access(request, "reader", "obsidian:sync:pull")
    try:
        result = get_obsidian_sync().pull(vault_id=vault_id, cursor=cursor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vault not found.") from exc
    return {"ok": True, **jsonable_encoder(result)}


@app.post("/api/obsidian/conflicts/{conflict_id}/resolve")
async def resolve_obsidian_conflict(
    conflict_id: str,
    body: ObsidianConflictResolveBody,
    request: Request,
) -> Any:
    actor = require_access(request, "writer", "obsidian:sync:push")
    try:
        result = get_obsidian_sync().resolve_conflict(
            conflict_id=conflict_id,
            actor=actor,
            resolution=body.resolution,
            body=body.body,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conflict not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    get_access_store().record_event(
        action="obsidian.conflict.resolve",
        actor=actor,
        success=True,
        detail={"conflict_id": conflict_id, "resolution": body.resolution},
    )
    return {"ok": True, "conflict": jsonable_encoder(result)}


@app.get("/api/documents/{document_id}")
async def source_document(document_id: str, request: Request) -> Any:
    require_access(request, "reader", "kb:read")
    if document_id.startswith(f"{GITHUB_DOC_ID_PREFIX}:"):
        github_document = github_section_document(document_id, get_citadel().config)
        if github_document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return {"ok": True, "document": jsonable_encoder(github_document)}
    try:
        document = get_obsidian_sync().document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found.") from exc
    return {"ok": True, "document": jsonable_encoder(document)}


@app.get("/api/learning-agent")
async def learning_agent_status(request: Request) -> Any:
    require_access(request, "reader", "sources:read")
    return jsonable_encoder(await get_learning_agent().status())


@app.get("/api/backup-mirror")
async def backup_mirror_status(request: Request) -> Any:
    require_access(request, "admin", "sources:sync")
    return jsonable_encoder(get_backup_mirror().status())


@app.post("/api/backup-mirror/run")
async def run_backup_mirror(body: BackupMirrorRunBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    try:
        result = get_backup_mirror().run(dry_run=body.dry_run)
    except BackupMirrorDisabled as exc:
        get_access_store().record_event(
            action="backup_mirror.run",
            actor=actor,
            success=False,
            detail={"dry_run": body.dry_run, "reason": "disabled"},
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BackupMirrorPublishError as exc:
        logger.error("Backup mirror publish failed: %s", exc.__class__.__name__)
        get_access_store().record_event(
            action="backup_mirror.run",
            actor=actor,
            success=False,
            detail={"dry_run": body.dry_run, "reason": "publish_failed"},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    manifest = result.get("manifest") if isinstance(result, dict) else {}
    summary = manifest.get("summary") if isinstance(manifest, dict) else {}
    get_access_store().record_event(
        action="backup_mirror.run",
        actor=actor,
        success=True,
        detail={
            "dry_run": body.dry_run,
            "written": result.get("written"),
            "published": result.get("published"),
            "snapshot_id": result.get("snapshot_id"),
            "tracked_files": summary.get("tracked_files"),
            "available_files": summary.get("available_files"),
            "missing_files": summary.get("missing_files"),
        },
    )
    return jsonable_encoder(result)


@app.get("/api/promote")
async def promotion_status(request: Request) -> Any:
    require_access(request, "admin", "sources:sync")
    return jsonable_encoder(get_promotion_engine().status())


@app.post("/api/promote/run")
async def run_promotion(body: PromoteRunBody, request: Request) -> Any:
    actor = require_access(request, "writer", "kb:ingest")
    if not is_seat_dataset(body.dataset):
        raise HTTPException(
            status_code=400,
            detail="dataset must be a seat node (seat:<slug>) to promote from.",
        )
    if not can_run_promotion(actor, body.dataset):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to run promotion for this seat dataset.",
        )
    try:
        result = await get_promotion_engine().run(
            body.dataset,
            dry_run=body.dry_run,
            max_items=body.max_items,
        )
    except SecretContentError as exc:
        get_access_store().record_event(
            action="promotion.run",
            actor=actor,
            success=False,
            dataset=body.dataset,
            detail={
                "dry_run": body.dry_run,
                "blocked": "secret_content",
                "highest_severity": exc.highest_severity,
            },
        )
        raise HTTPException(status_code=422, detail=exc.public_message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - depends on Cognee runtime.
        logger.error("Promotion run failed: %s", exc.__class__.__name__)
        get_access_store().record_event(
            action="promotion.run",
            actor=actor,
            success=False,
            dataset=body.dataset,
            detail={"dry_run": body.dry_run, "error_type": exc.__class__.__name__},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    get_access_store().record_event(
        action="promotion.run",
        actor=actor,
        success=True,
        dataset=body.dataset,
        detail={
            "dry_run": body.dry_run,
            "enabled": result.get("enabled"),
            "candidates": result.get("candidates"),
            "proposed": result.get("proposed"),
            "promoted": result.get("promoted"),
            "pending_approval": result.get("pending_approval"),
            "queued": result.get("queued"),
            "max_items": result.get("max_items"),
        },
    )
    return jsonable_encoder(result)


@app.get("/api/promotion/pending")
async def list_promotion_pending(
    request: Request,
    status: str = PENDING_STATUS,
) -> dict[str, Any]:
    identity = require_access(request, "reader", "kb:read")
    seat_slug = promotion_pending_filter_seat(identity)
    if status not in {PENDING_STATUS, REJECTED_STATUS, APPROVED_STATUS}:
        raise HTTPException(status_code=422, detail=f"Unsupported status filter: {status}")
    items = get_access_store().list_promotion_pending(seat_slug=seat_slug, status=status)
    return {
        "ok": True,
        "status": status,
        "items": [redact_pending_item(item.to_dict()) for item in items],
        "count": len(items),
    }


@app.post("/api/promotion/pending/{item_id}/approve")
async def approve_promotion_pending(
    item_id: str,
    request: Request,
    body: PromotionDecisionBody | None = None,
) -> dict[str, Any]:
    # Approving commits a candidate into Central, so it requires admin — a
    # seat-writer is rejected with 403 BEFORE the item lookup, closing the gap
    # where a seat could self-promote its own pending item into Central (#48).
    identity = require_access(request, "admin", "sources:sync")
    item = get_access_store().get_promotion_pending(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Promotion item not found: {item_id}")
    allowed, delegate = can_decide_promotion_item(identity, item.seat_slug)
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to approve this promotion item.")
    try:
        result = await get_promotion_engine().approve_pending(
            item_id,
            identity,
            delegate=delegate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body and body.note:
        get_access_store().record_event(
            action="promotion.approve.note",
            actor=identity,
            success=True,
            dataset=item.seat_dataset,
            detail={"item_id": item_id, "note": body.note[:400]},
        )
    return jsonable_encoder(result)


@app.post("/api/promotion/pending/{item_id}/reject")
async def reject_promotion_pending(
    item_id: str,
    request: Request,
    body: PromotionDecisionBody | None = None,
) -> dict[str, Any]:
    # Symmetric with approve: deciding a Central-bound promotion is admin-only, so
    # a seat-writer is 403'd before the item lookup (#48).
    identity = require_access(request, "admin", "sources:sync")
    item = get_access_store().get_promotion_pending(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Promotion item not found: {item_id}")
    allowed, delegate = can_decide_promotion_item(identity, item.seat_slug)
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to reject this promotion item.")
    try:
        result = await get_promotion_engine().reject_pending(
            item_id,
            identity,
            delegate=delegate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body and body.note:
        get_access_store().record_event(
            action="promotion.reject.note",
            actor=identity,
            success=True,
            dataset=item.seat_dataset,
            detail={"item_id": item_id, "note": body.note[:400]},
        )
    return jsonable_encoder(result)


@app.post("/api/learning-agent/run")
async def run_learning_agent(body: LearningAgentRunBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    citadel = get_citadel()
    mesh_state = get_mesh()
    try:
        result = await get_learning_agent().run(
            force=body.force,
            dry_run=body.dry_run,
            post_to_chat=body.post_to_chat,
            include_digest_preview=body.include_digest_preview,
        )
    except Exception as exc:  # pragma: no cover - depends on external sources and Cognee config.
        logger.error("Learning agent run failed: %s", exc.__class__.__name__)
        await mesh_state.record_error(citadel.config, operation="learning_agent", error=str(exc))
        get_access_store().record_event(
            action="learning_agent.run",
            actor=actor,
            success=False,
            detail={
                "force": body.force,
                "dry_run": body.dry_run,
                "post_to_chat": body.post_to_chat,
                "error": str(exc),
            },
        )
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=get_citadel().config.github_sync_dataset,
            detail={
                "operation": "learning_agent.run",
                "force": body.force,
                "dry_run": body.dry_run,
                "post_to_chat": body.post_to_chat,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    github_result = result.get("sources", {}).get("github")
    if isinstance(github_result, dict):
        await mesh_state.record_github_sync(citadel.config, github_result)
    repo_content_result = result.get("sources", {}).get("repo_content")
    if (
        isinstance(repo_content_result, dict)
        and repo_content_result.get("enabled") is not False
        and not body.dry_run
    ):
        await mesh_state.record_repo_content_sync(citadel.config, repo_content_result)
    get_access_store().record_event(
        action="learning_agent.run",
        actor=actor,
        success=True,
        detail={
            "force": body.force,
            "dry_run": body.dry_run,
            "post_to_chat": body.post_to_chat,
            "ingested": result.get("ingested"),
            "improved": result.get("improved"),
            "files_ingested": (
                repo_content_result.get("files_ingested") if isinstance(repo_content_result, dict) else None
            ),
            "digest_meaningful": (result.get("organization_digest") or {}).get("meaningful"),
            "google_chat_sent": (
                (result.get("notifications") or {}).get("google_chat") or {}
            ).get("sent"),
        },
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=citadel.config.github_sync_dataset,
        detail={
            "operation": "learning_agent.run",
            "force": body.force,
            "dry_run": body.dry_run,
            "post_to_chat": body.post_to_chat,
            "ingested": result.get("ingested"),
            "improved": result.get("improved"),
            "digest_meaningful": (result.get("organization_digest") or {}).get("meaningful"),
            "google_chat_sent": (
                (result.get("notifications") or {}).get("google_chat") or {}
            ).get("sent"),
        },
    )
    return jsonable_encoder(result)


@app.post("/api/cognify/run")
async def run_cognify(body: CognifyRunBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    citadel = get_citadel()
    dataset = body.dataset or citadel.config.default_dataset
    try:
        result = await citadel.cognify_dataset(dataset=dataset, verify=body.verify, force=body.force)
    except Exception as exc:  # pragma: no cover - depends on Cognee config.
        logger.error("Cognify run failed: %s", exc.__class__.__name__)
        get_access_store().record_event(
            action="cognify.run",
            actor=actor,
            success=False,
            dataset=dataset,
            detail={"verify": body.verify, "force": body.force, "error": str(exc)},
        )
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=dataset,
            detail={
                "operation": "cognify.run",
                "verify": body.verify,
                "force": body.force,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    verification = result.get("verification") or {}
    get_access_store().record_event(
        action="cognify.run",
        actor=actor,
        success=True,
        dataset=dataset,
        detail={
            "verify": body.verify,
            "force": body.force,
            "graph_grew": result.get("graph_grew"),
            "graph_before": result.get("graph_before"),
            "graph_after": result.get("graph_after"),
            "verification_ok": verification.get("ok") if body.verify else None,
        },
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=dataset,
        detail={
            "operation": "cognify.run",
            "verify": body.verify,
            "force": body.force,
            "graph_grew": result.get("graph_grew"),
            "verification_ok": verification.get("ok") if body.verify else None,
        },
    )
    return jsonable_encoder(result)


@app.post("/api/learning-agent/google-chat/test")
async def test_learning_agent_google_chat(body: GoogleChatTestBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    result = await get_learning_agent().test_google_chat_delivery(message=body.message)
    detail = {
        "sent": result.get("sent"),
        "reason": result.get("reason"),
        "status_category": result.get("status_category"),
        "status_code": result.get("status_code"),
        "message_name": result.get("message_name"),
        "thread_name": result.get("thread_name"),
    }
    get_access_store().record_event(
        action="learning_agent.google_chat_test",
        actor=actor,
        success=bool(result.get("sent")),
        detail={key: value for key, value in detail.items() if value is not None},
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=bool(result.get("sent")),
        dataset=get_citadel().config.github_sync_dataset,
        detail={
            "operation": "learning_agent.google_chat_test",
            **{key: value for key, value in detail.items() if value is not None},
        },
    )
    return jsonable_encoder(result)


@app.post("/api/learning-agent/gateways/{gateway_name}/test")
async def test_learning_agent_gateway(
    gateway_name: str,
    body: GoogleChatTestBody,
    request: Request,
) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    if not re.fullmatch(r"[a-z0-9_-]{1,80}", gateway_name):
        raise HTTPException(status_code=400, detail="Gateway names may contain a-z, 0-9, _, and -.")
    result = await get_learning_agent().test_gateway_delivery(gateway_name, message=body.message)
    detail = {
        "gateway": gateway_name,
        "sent": result.get("sent"),
        "reason": result.get("reason"),
        "status_category": result.get("status_category"),
        "status_code": result.get("status_code"),
        "message_name": result.get("message_name"),
        "thread_name": result.get("thread_name"),
    }
    get_access_store().record_event(
        action="learning_agent.gateway_test",
        actor=actor,
        success=bool(result.get("sent")),
        detail={key: value for key, value in detail.items() if value is not None},
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=bool(result.get("sent")),
        dataset=get_citadel().config.github_sync_dataset,
        detail={
            "operation": "learning_agent.gateway_test",
            **{key: value for key, value in detail.items() if value is not None},
        },
    )
    return jsonable_encoder(result)


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    require_access(request, "reader", "kb:read")
    mesh_state = get_mesh()
    queue = mesh_state.subscribe()

    async def stream() -> Any:
        try:
            snapshot = await mesh_state.snapshot(get_citadel().config)
            yield sse("snapshot", snapshot)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield sse("mesh-event", event)
        finally:
            mesh_state.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/ingest")
async def ingest(body: IngestBody, request: Request) -> Any:
    actor = require_access(request, "writer", "kb:ingest")
    enforce_ingest_size(body.data)
    citadel = get_citadel()
    learning = get_learning_process()
    write_targets = resolve_write_targets(actor, body.dataset, body.tags, citadel.config)
    session_id = resolve_session_id(actor, body.session_id)
    primary_dataset = write_targets[0].dataset
    try:
        outcome, _ = await execute_learning_writes(
            learning,
            data=body.data,
            targets=write_targets,
            tags=body.tags,
            session_id=session_id,
            operation="ingest",
        )
    except SecretContentError as exc:
        get_access_store().record_event(
            action="ingest",
            actor=actor,
            success=False,
            dataset=primary_dataset,
            detail={
                "operation": "ingest",
                "blocked": "secret_content",
                "highest_severity": exc.highest_severity,
                "finding_count": len(exc.findings),
            },
        )
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=primary_dataset,
            detail={
                "operation": "ingest",
                "blocked": "secret_content",
                "highest_severity": exc.highest_severity,
            },
        )
        raise HTTPException(status_code=422, detail=exc.public_message) from exc
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=primary_dataset,
            detail={"operation": "ingest", "error_type": exc.__class__.__name__},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = outcome.ingest
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=outcome.dataset,
        detail={
            "operation": "ingest",
            "accepted": result.accepted,
            "reason": result.reason,
            "data_bytes": len(body.data.encode("utf-8")),
            "tag_count": len(body.tags),
            "write_targets": [target.dataset for target in write_targets],
            "scope_override": scope_override_active(
                actor, [target.dataset for target in write_targets]
            ),
        },
    )
    payload = jsonable_encoder(result)
    # Inline cognify (opt-in) so the just-written data is immediately searchable.
    # The write already succeeded; a cognify failure must NOT fail the ingest.
    if body.cognify and result.accepted:
        try:
            await citadel.cognify_dataset(dataset=outcome.dataset)
            payload["cognified"] = True
        except Exception as exc:  # pragma: no cover - depends on runtime Cognee state
            logger.error("inline cognify after ingest failed: %s", exc.__class__.__name__)
            payload["cognified"] = False
    return payload


@app.get("/api/contributions/recent")
async def recent_contributions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    mine: bool = Query(default=False),
) -> Any:
    actor = require_access(request, "reader", "kb:read")
    actor_id = actor.actor_id if mine else None
    events = get_access_store().recent_audit_events(
        action="contribute",
        actor_id=actor_id,
        limit=limit,
    )
    return {
        "ok": True,
        "contributions": events,
        "filter": {"mine": mine, "limit": limit},
    }


@app.post("/api/contribute")
async def contribute(body: ContributeBody, request: Request) -> Any:
    """Simple write path for teammates and agents.

    Routes through the Learning Process (with LLM enrichment when enabled)
    and keeps conflict detection on, so a Vault Contribution behaves exactly
    like any other accepted Source Material.
    """
    actor = require_access(request, "writer", "kb:ingest")
    enforce_ingest_size(body.content)
    guard_seat_write_policy(
        actor,
        operation="contribute",
        dataset=body.dataset,
        tags=body.tags,
    )
    citadel = get_citadel()
    learning = get_learning_process()
    contribution_tags = _contribution_tags(body.tags, actor)
    write_targets = resolve_write_targets(actor, body.dataset, contribution_tags, citadel.config)
    parts = [f"# {body.title.strip()}", "", body.content.strip()]
    if body.source_url and body.source_url.strip():
        parts.extend(["", f"Source: {body.source_url.strip()}"])
    if actor.actor_name:
        parts.extend(["", f"Author: {actor.actor_name.strip()}"])
    data = "\n".join(parts)
    try:
        outcome, _ = await execute_learning_writes(
            learning,
            data=data,
            targets=write_targets,
            tags=contribution_tags,
            session_id=None,
            operation="contribute",
            run_improve=citadel.config.contribute_run_improve,
        )
    except SecretContentError as exc:
        get_access_store().record_event(
            action="contribute",
            actor=actor,
            success=False,
            dataset=write_targets[0].dataset,
            detail={
                "operation": "contribute",
                "blocked": "secret_content",
                "highest_severity": exc.highest_severity,
                "finding_count": len(exc.findings),
            },
        )
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=write_targets[0].dataset,
            detail={
                "operation": "contribute",
                "blocked": "secret_content",
                "highest_severity": exc.highest_severity,
            },
        )
        raise HTTPException(status_code=422, detail=exc.public_message) from exc
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        get_access_store().record_event(
            action="contribute",
            actor=actor,
            success=False,
            dataset=write_targets[0].dataset,
            detail={"error_type": exc.__class__.__name__},
        )
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=write_targets[0].dataset,
            detail={"operation": "contribute", "error_type": exc.__class__.__name__},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    accepted = any(result.accepted for result in outcome.all_ingests)
    get_access_store().record_event(
        action="contribute",
        actor=actor,
        success=accepted,
        dataset=outcome.dataset,
        detail={
            "accepted": accepted,
            "chunks": outcome.accepted_chunks,
            "conflict": bool(outcome.conflict),
            "reason": outcome.ingest.reason,
            "title": body.title.strip(),
            "tags": contribution_tags,
            "tag_count": len(contribution_tags),
            "content_bytes": len(body.content.encode("utf-8")),
        },
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=accepted,
        dataset=outcome.dataset,
        detail={
            "operation": "contribute",
            "accepted": accepted,
            "chunks": outcome.accepted_chunks,
            "conflict": bool(outcome.conflict),
            "scope_override": scope_override_active(
                actor, [target.dataset for target in write_targets]
            ),
        },
    )
    return jsonable_encoder(
        {
            "ok": True,
            "accepted": accepted,
            "chunks": outcome.accepted_chunks,
            "conflict": outcome.conflict,
            "dataset": outcome.dataset,
            "reason": outcome.ingest.reason,
            "enrichment": outcome.enrichment,
        }
    )


def flat_knowledge_result(result: Any) -> dict[str, Any]:
    """Flatten one search hit into the agent-friendly knowledge shape."""
    if not isinstance(result, dict):
        return {"text": str(result), "source": None}
    provenance = result_provenance(result)
    text = first_string(
        result.get("text"),
        result.get("content"),
        result.get("chunk"),
        result.get("body"),
        result.get("summary"),
        result.get("title"),
    )
    if not text:
        text = json.dumps(
            {key: value for key, value in result.items() if key != "_citadel"},
            sort_keys=True,
            default=str,
        )[:500]
    payload: dict[str, Any] = {
        "text": text,
        "source": provenance.get("source_url")
        or provenance.get("source")
        or provenance.get("path"),
    }
    score = result.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        payload["score"] = score
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    tags = result.get("tags") or metadata.get("citadel_tags") or metadata.get("tags")
    if isinstance(tags, list):
        payload["tags"] = [str(tag) for tag in tags if isinstance(tag, (str, int, float))]
    return payload


@app.get("/api/knowledge")
async def knowledge(
    request: Request,
    q: str,
    limit: int = 10,
    dataset: str | None = None,
) -> Any:
    """Thin reader alias over /search with a flat, agent-friendly shape."""
    identity = require_access(request, "reader", "kb:search")
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query q must not be empty.")
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 50.")
    citadel = get_citadel()
    mesh_state = get_mesh()
    search_datasets = resolve_search_datasets(identity, dataset, citadel.config)
    search_sessions = resolve_search_sessions(identity, None, search_datasets)
    try:
        merged = await search_across_datasets(
            citadel,
            query=query,
            datasets=search_datasets,
            sessions=search_sessions,
            top_k=limit,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        await mesh_state.record_error(citadel.config, operation="search", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    for search_dataset, _ in merged:
        await mesh_state.record_search(
            citadel.config,
            query=query,
            dataset=search_dataset,
            result_count=sum(1 for ds, _ in merged if ds == search_dataset),
        )
    primary_dataset = search_datasets[0]
    return jsonable_encoder(
        {
            "ok": True,
            "query": query,
            "dataset": primary_dataset,
            "datasets": search_datasets if len(search_datasets) > 1 else None,
            "results": [flat_knowledge_result(result) for _, result in merged],
        }
    )


@app.post("/api/learning-agent/optimize")
async def optimize_learning_agent(body: OptimizeBody, request: Request) -> Any:
    """Bounded self-improvement pass. Admin only; never deletes knowledge."""
    actor = require_access(request, "admin", "sources:sync")
    citadel = get_citadel()
    mesh_state = get_mesh()
    optimizer = SelfImprovement(
        citadel,
        mesh=mesh_state,
        learning=get_learning_process(),
        access_store=get_access_store(),
    )
    try:
        result = await optimizer.run(
            dry_run=body.dry_run,
            max_items=body.max_items,
            actor=actor,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        await mesh_state.record_error(citadel.config, operation="self_improve", error=str(exc))
        get_access_store().record_event(
            action="learning_agent.optimize",
            actor=actor,
            success=False,
            detail={"dry_run": body.dry_run, "error_type": exc.__class__.__name__},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=result.get("dataset"),
        detail={
            "operation": "learning_agent.optimize",
            "reviewed": result.get("reviewed"),
            "optimized": result.get("optimized"),
            "dry_run": body.dry_run,
        },
    )
    return jsonable_encoder(result)


@app.post("/search")
async def search(body: SearchBody, request: Request) -> Any:
    actor = require_access(request, "reader", "kb:search")
    citadel = get_citadel()
    mesh_state = get_mesh()
    search_datasets = resolve_search_datasets(actor, body.dataset, citadel.config)
    search_sessions = resolve_search_sessions(actor, body.session_id, search_datasets)
    try:
        merged = await search_across_datasets(
            citadel,
            query=body.query,
            datasets=search_datasets,
            sessions=search_sessions,
            top_k=body.top_k,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        await mesh_state.record_error(citadel.config, operation="search", error=str(exc))
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=search_datasets[0],
            detail={
                "operation": "search",
                "query_sha256": hashlib.sha256(body.query.encode("utf-8")).hexdigest(),
                "query_length": len(body.query),
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    for search_dataset in search_datasets:
        await mesh_state.record_search(
            citadel.config,
            query=body.query,
            dataset=search_dataset,
            result_count=sum(1 for ds, _ in merged if ds == search_dataset),
        )
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=search_datasets[0],
        detail={
            "operation": "search",
            "query_sha256": hashlib.sha256(body.query.encode("utf-8")).hexdigest(),
            "query_length": len(body.query),
            "result_count": len(merged),
            "top_k": body.top_k,
            "datasets": search_datasets,
            "scope_override": scope_override_active(actor, search_datasets),
        },
    )
    normalized = [
        with_result_metadata(result, index, dataset)
        for index, (dataset, result) in enumerate(merged)
    ]
    primary_dataset = search_datasets[0]
    payload: dict[str, Any] = {
        "results": normalized,
        "dataset": primary_dataset,
    }
    if len(search_datasets) > 1:
        payload["datasets"] = search_datasets
    if not normalized and body.dataset is None:
        payload["note"] = (
            "No results in the default dataset. Pass an explicit \"dataset\" to search a "
            "specific source; see known_datasets."
        )
        payload["known_datasets"] = known_datasets(citadel.config)
    return jsonable_encoder(payload)


@app.post("/feedback")
async def feedback(body: FeedbackBody, request: Request) -> Any:
    actor = require_access(request, "writer", "kb:feedback")
    citadel = get_citadel()
    mesh_state = get_mesh()
    dataset = body.dataset or citadel.config.default_dataset
    try:
        result = await citadel.feedback(
            FeedbackRequest(
                qa_id=body.qa_id,
                score=body.score,
                text=body.text,
                session_id=body.session_id,
                dataset=body.dataset,
            )
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        await mesh_state.record_error(citadel.config, operation="feedback", error=str(exc))
        record_mcp_audit(
            request,
            actor=actor,
            success=False,
            dataset=dataset,
            detail={"operation": "feedback", "error_type": exc.__class__.__name__},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await mesh_state.record_feedback(
        citadel.config,
        qa_id=body.qa_id,
        dataset=dataset,
        result=result,
    )
    record_mcp_audit(
        request,
        actor=actor,
        success=True,
        dataset=dataset,
        detail={
            "operation": "feedback",
            "qa_id_sha256": hashlib.sha256(body.qa_id.encode("utf-8")).hexdigest(),
            "score": body.score,
            "has_text": bool(body.text),
            "recorded": result.recorded,
            "improved": result.improved,
        },
    )
    return jsonable_encoder(result)


@app.post("/improve")
async def improve(body: ImproveBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    return await run_improve(body, request=request, actor=actor)


@app.post("/api/self-upgrade")
async def self_upgrade(body: ImproveBody, request: Request) -> Any:
    actor = require_access(request, "admin", "sources:sync")
    return await run_improve(body, request=request, actor=actor)


async def run_improve(
    body: ImproveBody,
    *,
    request: Request | None = None,
    actor: AccessIdentity | None = None,
) -> Any:
    citadel = get_citadel()
    mesh_state = get_mesh()
    dataset = body.dataset or citadel.config.default_dataset
    try:
        result = await citadel.improve(
            dataset=body.dataset,
            session_ids=body.session_ids,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        await mesh_state.record_error(citadel.config, operation="improve", error=str(exc))
        if request:
            record_mcp_audit(
                request,
                actor=actor,
                success=False,
                dataset=dataset,
                detail={"operation": "improve", "error_type": exc.__class__.__name__},
            )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await mesh_state.record_upgrade(
        citadel.config,
        dataset=dataset,
        session_ids=body.session_ids,
    )
    if request:
        record_mcp_audit(
            request,
            actor=actor,
            success=True,
            dataset=dataset,
            detail={
                "operation": "improve",
                "session_count": len(body.session_ids or []),
            },
        )
    return jsonable_encoder({"result": result})
