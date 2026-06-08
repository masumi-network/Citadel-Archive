# Citadel Progress

Last updated: 2026-06-08.

## 2026-06-08

- Created and pushed the separate Scout update-agent repository:
  - Repository: `https://github.com/masumi-network/Scout.git`.
  - Commit `5bc78d9` (`Scaffold Scout update agent`) is on Scout `main`.
  - Scout owns update-agent orchestration and delivery gateways while Citadel
    remains the Organization Vault/source contract.
  - Added a Citadel client, modular gateway registry, Google Chat gateway,
    CLI entrypoint (`uv run scout status`, `uv run scout run --post`), config
    example, and focused tests.
  - Added Scout's gateway guide at `docs/gateway-guide.md` with Google Chat
    setup, local smoke tests, deployment rules, failure modes, and the adapter
    contract for future gateways.
  - Verified Scout with `uv run pytest` and `uv run ruff check .`.
- Added Citadel-side modular gateway support for the external-agent split:
  - Added `kb/notification_gateways.py` with a small `NotificationGateway`
    protocol and configured gateway registry.
  - Refactored `LearningAgent` to emit `notifications.gateways` while preserving
    the existing `notifications.google_chat` compatibility key.
  - Added generic admin-only gateway smoke testing at
    `/api/learning-agent/gateways/{gateway_name}/test`.
  - Updated cron summary output to include sanitized gateway delivery status.
  - Documented the repo boundary and migration path in
    `docs/internal-update-agent-architecture.md`.
  - Updated the Google Chat rollout plan and README to describe Scout as the
    long-term poster and Citadel's built-in Chat delivery as a compatibility
    path.
- Fixed a time-sensitive GitHub sync PR test whose hard-coded June 3 PR
  timestamps had fallen outside its 48-hour window by June 8, 2026.
- Verified Citadel with `uv run pytest` and focused `uv run ruff check`.

## 2026-06-04

- Committed and pushed private GitHub sync privacy/security hardening:
  - Commit `f95486f` (`feat(github): harden private sync digests`) is on
    `main`.
  - Verified before push with `.venv/bin/python -m pytest`,
    `.venv/bin/python -m ruff check .`, and `git diff --check`.
  - Added summary-only cron output so scheduled logs expose counts and scan
    status rather than raw private repository payloads.
- Verified Railway post-deployment state for commit `f95486f`:
  - `Citadel-Archive` deployment `4081a3ad-c8cc-4913-90f6-bb194b3d00f1`
    reached `SUCCESS`.
  - `Citadel-GitHub-Sync` deployment
    `027df285-2a4f-4499-a193-40d64d6c32d2` reached `SUCCESS`.
  - `Postgres` remained `SUCCESS`.
  - Live `/healthz` returned `{"ok":true,"service":"citadel"}`.
- Ran the GitHub sync cron path manually through Railway production variables:
  - `railway run --service Citadel-GitHub-Sync --environment production ...`
    called the hosted `/api/learning-agent/run` endpoint with summary-only
    output.
  - The run completed with `ok=true`, `dry_run=false`, `ingested=true`, and
    `improved=false`.
  - It scanned 42 repositories, saw 1 changed repository, 1 organization event,
    1 commit, 5 open PRs, and 4 merged PRs.
  - The security scanner returned `ok=true`, `blocked=false`, and
    `finding_count=0`.
  - Google Chat delivery was not attempted because production returned
    `google_chat_disabled`.

## 2026-06-03

- Added Google Chat Organization Update Digest support:
  - `kb/organization_digest.py` builds a constructive source-linked digest from
    GitHub PR/activity data and recent Citadel context, with an OpenRouter-backed
    agent read and deterministic fallback.
  - `kb/google_chat.py` posts outbound-only messages via Google Chat API app
    auth, bounded retries, thread keys, client message IDs, and sanitized
    delivery status.
  - The learning-agent run now supports preview-only manual runs and explicit
    `post_to_chat` delivery for scheduled or admin-triggered posts.
  - Added an admin-only Google Chat test endpoint for rollout smoke tests:
    `/api/learning-agent/google-chat/test`.
  - Updated the Source Sync dashboard action to run the learning-agent path, show
    digest preview and Google Chat status, and expose a separate Google Chat
    smoke-test button.
  - Added ADR 0002 and the rollout plan in
    `docs/google-chat-organization-update-digest-plan.md`.
  - Verified with `uv run ruff check .` and `uv run pytest`.
- Checked Railway rollout state for the digest:
  - Project `Citadel Archive`, production service `Citadel-GitHub-Sync` is still
    scheduled for `0 3 * * *`.
  - The cron service still has a start command override:
    `python -m kb.github_sync --org masumi-network`.
  - Target state is documented in the Google Chat rollout plan before mutating
    production Railway config.
- Installed this workspace's project MCP config against the hosted Citadel MCP
  endpoint:
  - `.mcp.json` now points to
    `https://citadel-archive-production.up.railway.app/mcp/`.
  - The config uses `${CITADEL_MCP_ACCESS_TOKEN}` and does not store a raw token.
- Added persistent MCP audit attribution:
  - MCP forwarded calls are recorded as `mcp.<tool_name>` audit events.
  - Events capture actor, role, tool, path, required role/scope, dataset when
    known, and success/failure.
  - Search queries, note bodies, feedback text, and tokens are not stored in the
    MCP audit detail; query and QA IDs are hashed where useful.
- Enforced token scopes server-side:
  - Protected API routes now require both a minimum role and the matching scope.
  - Bootstrap env keys use default role scopes.
  - Custom-scoped service-account tokens can only reduce permissions; scopes
    that exceed the selected role are rejected.
  - Session capabilities now reflect effective scopes, not only role labels.
- Added admin audit visibility for MCP operations:
  - Audit page has filters for all events, MCP events, non-MCP access/admin
    events, and failures.
  - The dashboard summarizes MCP event count, MCP failures, and distinct MCP
    actors.
  - Audit detail rendering redacts sensitive-looking fields by key.
- Added server-side audit views for admin/API clients:
  - `/api/audit` supports `view=all|mcp|access|failures` and a bounded `limit`.
  - Responses include summary counts for total events, returned events, MCP
    events, MCP failures, failed events, access events, and distinct MCP actors.
- Added a manifest-only Vault Backup Mirror tracking layer:
  - `kb/backup_mirror.py` tracks GitHub sync, Obsidian sync, and access/audit
    state files by path, size, timestamp, and SHA-256 hash without copying raw
    file bodies.
  - `/api/backup-mirror` and `/api/backup-mirror/run` expose admin status and
    dry-run/write flows; non-dry-run writes require
    `CITADEL_BACKUP_MIRROR_ENABLED=true`.
  - `scripts/run_backup_mirror.py` provides a cron-friendly wrapper for hosted
    API or in-process manifest export.
  - The Settings page now shows backup mirror status from the API.
  - Optional GitHub push publishes only `manifests/latest.json` and dated
    `snapshots/.../manifest.json` through the Contents API when
    `CITADEL_BACKUP_MIRROR_PUSH_ENABLED=true` and a dedicated mirror token is
    configured.
- Replaced Railway's inline shell start command with `scripts/run_railway.py`:
  - `web` execs Uvicorn.
  - `learning-agent`/`github-sync` run the GitHub learning cron wrapper.
  - `backup-mirror` runs the Vault Backup Mirror manifest cron wrapper.
- Added admin MCP tools for backup mirror operations:
  - `citadel_backup_mirror_status` inspects manifest status.
  - `citadel_run_backup_mirror` runs manifest export and defaults to dry-run.
- Added `citadel_audit_events`, an admin MCP tool for bounded
  `all|mcp|access|failures` audit views backed by the same `/api/audit` redaction
  path.
- Updated dashboard MCP setup snippets to use the hosted `/mcp/` endpoint instead
  of the older local `uv` wrapper path.
- Updated hosted MCP docs/templates so the no-clone `/mcp/` URL is the primary
  setup path, with the stdio wrapper left as a fallback/dev path.
- Added verifiable hosted skill metadata:
  - `/skills` now includes `size_bytes`, `sha256`, and SRI-style `integrity`
    values for each bundled skill.
  - `/skills/*` responses include matching digest headers and a content-derived
    ETag so agents can verify the markdown they loaded.
- Added a public well-known agent discovery manifest:
  - `/.well-known/citadel.json` lists the hosted MCP endpoint, token
    requirements, MCP tool policy metadata, approval recommendations, skill
    hashes, and public/private boundary rules.
  - The manifest is metadata-only and does not expose datasets, vault contents,
    Obsidian sync data, audit events, backup mirror contents, or raw tokens.
- Added MCP-native discovery:
  - `citadel_discovery` lets connected agents fetch the same safe discovery
    manifest after an authenticated `/api/session` probe.
  - `citadel://discovery` exposes the public manifest as a lightweight MCP
    resource without requiring vault/search reads.
- Added agent-facing search provenance metadata:
  - `/search` now adds an additive `_citadel` envelope to dict results with
    rank, dataset, stable result ID, content hash, source provenance hints, and
    retrieval safety flags.
  - Document drill-down is explicitly marked with
    `_citadel.retrieval.document_drilldown_available` so agents do not assume
    every generated chunk ID can be fetched as a full source document.
- Surfaced provenance in the dashboard search results:
  - Search cards now show source, path, session, dataset, content hash, and
    untrusted-context status before the raw JSON payload.
  - Full-source links only render when the backend marks document drill-down as
    available.
- Added baseline browser security headers:
  - HTTP responses now include a self-only CSP, `nosniff`, frame blocking,
    no-referrer policy, restrictive permissions policy, and same-origin
    cross-origin policies.
  - HSTS is sent only for HTTPS or HTTPS-forwarded requests.
  - Login JavaScript moved from inline HTML to `/static/login.js` so CSP does not
    require `unsafe-inline`.
- Added explicit cache policy:
  - Public skill/discovery/static metadata uses `Cache-Control: public,
    max-age=300`.
  - Health, login, authenticated API, vault search/document, audit, and MCP
    responses default to `Cache-Control: no-store` and `Pragma: no-cache`.
- Verified Railway GitHub sync cron state:
  - `Citadel-GitHub-Sync` ran at `2026-06-03T03:04:06Z`.
  - The run ended with ingestion accepted (`ingested=true`, `dry_run=false`).
  - Next scheduled run is `2026-06-04T03:00:00Z`.
- Dry-ran the backup-mirror cron path against production and confirmed rollout
  is still pending:
  - `scripts/run_backup_mirror.py` called
    `https://citadel-archive-production.up.railway.app/api/backup-mirror/run`.
  - Production returned `404 Not Found` because the live web service is still on
    the older commit without the backup-mirror API.
- Deployed hosted MCP/security hardening:
  - Commit `7c37c86` deployed the role/scope enforcement, MCP audit, discovery
    manifest, skill hashes, backup-mirror API, security headers, and cache policy.
  - Commit `3c70e92` made `/mcp/` the canonical hosted MCP endpoint and kept
    legacy `/mcp` as a relative redirect to avoid an absolute `http://` Location
    behind Railway.
  - Production `/.well-known/citadel.json` now advertises
    `https://citadel-archive-production.up.railway.app/mcp/`.
  - Hosted MCP `initialize` returns `200`, `tools/list` returns 13 tools, and a
    `citadel_session` tool call is recorded in MCP audit as
    `mcp.citadel_session`.
  - Backup mirror dry-run through the hosted API returns `ok=true`,
    `written=false`, and `published=false`.

## 2026-06-02

- Team-share readiness verified after commit `7a4a1d9`:
  - `npx skills add masumi-network/Citadel-Archive` installs the root
    `citadel-archive` skill.
  - Production web service `Citadel-Archive` is `SUCCESS` and `RUNNING` on
    Railway at commit `7a4a1d9`.
  - Public endpoints `/healthz`, `/skills`, and `/skills/connect` return `200`.
  - Direct HTTP with a writer token verifies `/api/session`, `/search`, and
    `/ingest`.
  - Hosted MCP verifies `initialize`, `tools/list`, `citadel_session`,
    `citadel_search`, and `citadel_ingest`.
  - Fixed hosted MCP self-call timeouts by offloading forwarded HTTP API calls
    from the event loop.
  - Any token pasted into chat or logs should be rotated before team rollout.
- Production rollout checkpoint, verified after commit `cd33217`:
  - Railway web service `Citadel-Archive` deployment `891c81ee-4c44-4303-8792-0a282d9d62be`
    is `SUCCESS` and serves `/healthz`.
  - Hosted skill index serves HTTPS URLs for `/skills/connect`, `/skills/vault`,
    and `/skills/boundary`.
  - Reader service-account MCP token was created for company bootstrap and stored
    only in ignored local `.citadel/` files.
  - Local MCP `citadel_search` smoke test returns results when using
    `CITADEL_MCP_DEFAULT_DATASET=masumi-network`.
- Diagnosed the failed Railway deployment `7658403e-d79e-4d89-969b-34bb3aa45374`:
  - The app container started and Uvicorn served traffic, but Railway health checks
    requested `/healthz` and received `404 Not Found`.
  - Fixed by restoring the `/healthz` route and adding test coverage.
- Fixed hosted skill URL generation behind Railway:
  - `/skills` now prefers configured public base URLs or forwarded proxy headers,
    so shareable skill URLs use `https://citadel-archive-production.up.railway.app`.
- Updated MCP connector defaults:
  - Added `CITADEL_MCP_DEFAULT_DATASET`; hosted company configs use
    `masumi-network` so agents do not need to remember the dataset for normal
    company knowledge searches.
- Ran live source learning:
  - Forced learning-agent run scanned 41 repositories, 50 organization events, and
    198 commits.
  - GitHub activity ingestion was accepted.
  - Live fallback search against the `masumi-network` dataset returns results from
    `github_sync_state`.
- Initialized the private NAS-style backup repository:
  - [Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror)
    is private, on `main`, and has initial scaffold commit `deeb1c9`.
  - Current scaffold includes `.gitignore`, `README.md`, `manifests/`, and
    `snapshots/`.
- Split repositories for production topology:
  - [Citadel-Archive](https://github.com/masumi-network/Citadel-Archive) is public
    (app, MCP, hosted agent skills).
  - [Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror) is
    private (Phase 1 Vault Backup Mirror target).
- Documented mirror policy in `docs/vault-backup-mirror.md` and reserved
  `CITADEL_BACKUP_MIRROR_*` configuration for the export job.
- Published public/private boundary: `docs/public-and-private.md`, `SECURITY.md`,
  hosted `/skills/boundary`, and scrubbed personal paths from MCP templates.

## 2026-05-29

- Checked the Organization Vault plan against the local implementation state.
- Started the next dashboard build slice:
  - added Knowledge, Agents, Audit, and Settings workspace pages
  - added reader default routing to Search when no page hash is present
  - wired Knowledge to source, index, digest, and runtime event state
  - wired Agents to service-account access tokens and MCP setup snippets
  - wired Audit to access audit events and runtime vault events
  - wired Settings to readiness and learning-agent status
- Verified static JavaScript syntax with `node --check kb/static/app.js`.
- Verified backend and API behavior with `uv run pytest`.
- Improved dashboard UX:
  - reduced duplicated navigation chrome to a compact workspace ribbon
  - made mobile pages content-first by hiding the sidebar
  - rewrote the dashboard header around current vault state and primary actions
  - added direct dashboard actions for search, source sync, note creation, access,
    source review, and agent management
  - browser-checked desktop and mobile dashboard rendering

## 2026-05-28

- Captured the shareable Organization Vault product plan in
  `docs/organization-vault-plan.md` and started the canonical domain glossary in
  `CONTEXT.md`.
- Resolved Phase 1 access, Agent Messenger, source retention, repository daily
  update, knowledge conflict, and Vault Backup Mirror language across docs.
- Recorded the first architecture-deepening candidates in
  `docs/architecture-deepening-opportunities.md`.
- Rethemed the Citadel web UI toward an Obsidian-style shared vault with a left
  ribbon, vault navigation, linked panes, and darker Obsidian-compatible visual
  tokens.
- Researched the official `obsidianmd` GitHub organization and documented the
  sync/plugin integration path in `docs/obsidian-integration-plan.md`.
- Added the Obsidian vault sync API, source status endpoint, revision/conflict
  store, UI source panel, and private beta plugin scaffold.
- Verified the web UI with browser render checks and backend tests with
  `uv run pytest`.

## 2026-05-26

- Replaced the sensitive 2D knowledge mesh force simulation with a deterministic
  Three.js 3D scene.
- Added restrained orbit and zoom controls, fixed camera bounds, stable node
  placement, and WebGL labels for the mesh.
- Vendored the Three.js browser modules under `kb/static/vendor/` so the hosted
  UI does not depend on a runtime CDN.
- Verified backend tests with `uv run pytest` and checked the 3D canvas with
  Playwright on desktop and mobile viewports.
