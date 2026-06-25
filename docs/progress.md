# Citadel Progress

Last updated: 2026-06-25.

## 2026-06-25

- **Knowledge-graph redesign — Phase 1 complete** (`feat/graph-logseq`). Replaced
  the hand-rolled Three.js 3D scene with a vendored 2D `force-graph` (Logseq-style):
  Central pinned at the centre, seat vaults tiered by size, hover neighbour dimming,
  click-to-inspect, labels-on-zoom, Fit/Pause controls, and Activity ↔ Knowledge
  graph toggle. Removed dead 3D layout code; timeline graph focus works in both modes.
  Phase 2 (explicit Central↔vault spokes, depth/scope controls) deferred.

## 2026-06-24

Major session: fixed broken ingest, upgraded the engine, shipped the per-seat
SaaS onboarding + autonomous sync, and started the knowledge-graph redesign.

- **Ingest was broken in production — root-caused and fixed.** `cognee.add`
  stored items but `cognee.cognify` failed on every one (empty knowledge graph,
  searches returned nothing). Cause: the Railway env var `LLM_MODEL=openrouter/free`
  is not a valid model id, so every litellm call during cognify returned
  `OpenrouterException - Invalid URL`. Fixed by setting
  `LLM_MODEL=openrouter/openai/gpt-4o-mini` on the web service (config only).
  Verified end-to-end: a marker note ingests (`cognee_result.status=completed`,
  `error=null`) and is found by search.
- **cognee 1.1.2 -> 1.2.1** (PR #2). Clean lock re-resolution; the `cognee_client`
  call surface is version-defensive and the breaking env renames in the window are
  unused by Citadel. Deployed and verified live (clean boot, no Kuzu/auth-flip
  errors, data survived the upgrade).
- **Re-cognify / verify recovery tooling** (PR #2). New admin `POST /api/cognify/run`,
  CLI `citadel cognify [--verify]`, and `CITADEL_RUN_MODE=cognify` / `cognify-verify`
  run-modes that re-cognify already-added-but-uncognified data and (in verify mode)
  ingest + cognify + search a marker as an end-to-end health check. An adversarial
  review caught a bug where verify skipped the recovery cognify; fixed so verify is
  a superset.
- **GitHub-Sync cron 502 fixed** (env only). The daily cron invoked a ~26-min sync
  as one synchronous HTTP call to the public domain (proxy kills idle connections at
  ~5 min). Pointed it at the internal domain `http://citadel-archive.railway.internal:8080`
  with `CITADEL_GITHUB_SYNC_TIMEOUT_SECONDS=2400`; cognify runs in the fixed web
  service. Heals the items stranded during the broken era on its next run.
- **Per-seat onboarding** (PR #3), on the existing seat/node/Central engine:
  - **Connect wizard** — Create Seat renders a ready-to-paste `.mcp.json` (Claude
    Code + Codex) with the seat's scoped writer token + origin-derived `/mcp/` URL +
    copy buttons + a personal-vs-shared explainer.
  - **Self-describing seat** — `resolved_memory_scope` surfaces the caller's own
    `seat_slug` + node label (out through `/api/session` + `citadel_session`);
    `citadel_ingest`/`search`/`contribute` docstrings state personal-by-default,
    tag-to-share.
  - **Seat inventory** — admin `GET /api/access/seats` + per-seat revoke in the UI.
- **Autonomous personal-KB sync** (PR #4). A project-committed Claude Code `SessionEnd`
  hook (`skills/citadel-proactive-ingest/`) runs a stdlib-only `sync_session.py` that
  distills a dev's session and POSTs it to their private seat node — reusing the one
  `CITADEL_MCP_ACCESS_TOKEN` they already set for MCP, personal-by-default, HTTPS-only,
  refuses redirects, fail-silent. Plus a proactive-ingest skill + dev onboarding docs.
  Zero per-session steps; the only one-time step is exporting the token (the wizard
  delivers it). Teammates are headless (token + MCP + skill, no dashboard login).
- **Knowledge-graph redesign — Phase 1 started** (`feat/graph-logseq`). See
  2026-06-25 entry for completion.
- **Backprop:** `test_github_sync_returns_open_and_merged_pull_requests` hardcoded
  absolute PR dates that aged out of the reporting window; made it time-relative.
- Tests: 312 -> 328 passing across the session; every adversarial-review finding fixed.

## 2026-06-17

- Reviewed the seat/node/central Phase 1+2 work (commit `2cd3ac9`,
  `feat(access): add seat provisioning and multi-dataset search`) against
  ADR-0003 and hardened six isolation/correctness gaps. Changes are local on
  `main`, verified but not yet committed/pushed.
- Closed the seat-isolation gaps in `kb/server.py` and `kb/access.py`:
  - **Default-deny `seat:` namespace.** `enforce_dataset_allowlist` no longer
    lets a token with an empty `allowed_datasets` reach a seat node by naming it.
    Previously any legacy/non-seat token could read or write another seat's
    `seat:{slug}` node; now only the owning seat (plus audited admin/env bypass)
    can. Ordinary (non-seat) datasets stay open for unscoped tokens for backward
    compatibility.
  - **Seats cannot be admin.** `create_seat(role="admin")` is rejected and the
    Admin option is removed from the seat form, because an admin token bypasses
    the allowlist and would dissolve the node boundary. Admin tokens are issued
    directly via token creation.
  - **Central allow-entry derived from config.** `create_seat` now takes the
    resolved `central_dataset(config)` instead of hardcoding `masumi-network`, so
    the seat allowlist can no longer drift from the dataset the router targets
    when `CITADEL_GITHUB_SYNC_DATASET` is overridden.
  - **Central is curated.** A seat-holder's explicit write to the Central dataset
    must carry an org tag (`org-ready` / `vault-contribution`) or go through
    `/api/contribute`; an untagged direct write to Central is rejected (403).
    Admin/env callers and non-seat service accounts keep their direct path.
- Hardened multi-dataset search merge: `search_across_datasets` now queries every
  allowed dataset before ranking, with a reserved slice for secondaries, so a
  result-rich node can no longer short-circuit and silently drop Central. Dedup
  still favors the node copy.
- Added scope-override auditing: when a bypassing caller that carries its own
  allowlist reaches outside it, search/ingest/contribute audit detail records
  `scope_override: true`.
- Documented the model changes in `docs/adr/0003-seat-node-central-private-memory.md`
  (three new Consequence bullets) and `docs/agent-access-model.md` (Read/Write
  Scope, Admin Override, Token Memory Scope, and Security Rules).
- Verified with `uv run pytest -q`: 301 passed (294 prior + 7 new tests covering
  cross-seat denial, unscoped-token denial of a seat node, admin-seat rejection,
  the curated-Central gate, scope-override auditing, and the configurable Central
  allow-entry).
- Addressed the PR #1 (Cursor Bugbot) review — three further seat-isolation gaps,
  shipped as `84fdde6` (fix), `fb5dd74` (test), `d88ec79` (docs):
  - **Seat session leaked to Central search.** `search_across_datasets` applied a
    single `session_id` to every dataset, so a seat's `default_session` scoped the
    Central leg and hid org-wide hits. Sessions are now resolved per dataset
    (`resolve_search_sessions`): the implicit `default_session` scopes only the
    caller's own node; shared datasets are searched session-wide. An explicit
    `session_id` still applies to whatever was searched.
  - **Curated-Central gate bypassable.** The gate keyed off `default_dataset`
    only, so a token defaulting to Central skipped the org-tag requirement and the
    default-target branch had no gate. Seat membership is now judged by storage
    scope (`is_seat_identity`: a `seat:` node in `default_dataset` or
    `allowed_datasets`) and the gate (`guard_curated_central`) runs on both
    explicit and default targets. Scope-based detection deliberately covers the
    agents scoped into a seat node — they are `service_account` principals with no
    `seat_slug`, so a principal-identity check would under-gate them.
  - **Obsidian push ignored tag routing.** `resolve_write_dataset` passed empty
    tags, trapping org-bound notes in the node. The push loop now routes per
    document with the real tags via `resolve_write_targets` +
    `execute_learning_writes`, matching `/ingest`.
- Recorded the resolved design decisions in ADR-0003 and `CONTEXT.md`: seat
  detection by storage scope (covering a human's tokens and their agents), the
  default-target gate, and per-dataset session isolation.
- Verified with `uv run pytest tests/test_server.py tests/test_obsidian_sync.py -q`:
  70 passed (3 new regression tests). Pre-existing unrelated failure
  `test_github_sync_returns_open_and_merged_pull_requests` (date-window assertion)
  is not from this work.
- Ran a full adversarial (Bugbot-style) audit of the PR and fixed the gaps it
  surfaced:
  - **Cross-seat session read (the notable one).** Nothing validated a
    caller-supplied `session_id`, and session-scoped recall ignores the dataset
    allowlist, so a seat could name another seat's guessable `seat-{slug}` session
    and read its private node. Added `assert_requested_session_allowed`: a
    non-bypass caller may name only its own `default_session` (else 403);
    admin/env keep full reach. Enforced in both `resolve_session_id` (writes) and
    `resolve_search_sessions` (search), and an explicit own session now scopes the
    node only — Central stays session-wide.
  - **Session-scoping edge.** `resolve_search_sessions` no longer drops a session
    when the caller has no node of its own — a single-dataset search still scopes
    to that one dataset.
  - **Obsidian audit clarity.** The push audit now records `written_datasets`
    (where tag routing actually landed content) alongside the vault's home
    binding.
  - Accepted as intentional: scope-based seat detection can gate a service
    account granted seat-node read (Option A trade-off), and Obsidian-promoted
    Central writes keep conflict detection off (Obsidian's revision model).
- Verified with `uv run pytest -q`: 304 passed (2 new session tests), only the
  pre-existing unrelated github-sync date-window test failing.

## 2026-06-11

- Shipped the Logseq-inspired Live Knowledge Timeline work in small commits:
  - `2ea4f46` (`docs: map live knowledge timeline`) captured the product map,
    fast read path, live update path, event model, and performance rules.
  - `e17d9af` (`feat(api): add knowledge event timeline`) added normalized mesh
    event envelopes and `GET /api/knowledge/events` with `after_id`, `limit`,
    `type`, and `kind` filters.
  - `b484817` (`feat(ui): add live knowledge timeline`) rebuilt the Activity
    page into a live timeline with chunk freshness counters, selectable event
    rows, an inspector, and graph focus for related dataset/source/vault/org
    nodes.
  - `a2f3a19` (`docs: document live knowledge timeline`) updated README and the
    timeline design doc after the feature shipped.
- Added timeline freshness state to `/api/mesh` snapshots:
  - `indexed_chunks`, `pending_chunks`, `failed_chunks`, `last_indexed_at`, and
    `latest_event_id` now give the UI a fast indexed/chunked status read without
    fetching raw source data.
  - Live SSE mesh events keep the existing `id`, `type`, `message`, `details`,
    and `created_at` fields and now include a compact `timeline` envelope.
- Verified the backend and UI changes before pushing:
  - `uv run pytest tests/test_mesh.py tests/test_server.py` passed.
  - `uv run ruff check kb/mesh.py kb/server.py tests/test_mesh.py tests/test_server.py` passed.
  - `node --check kb/static/app.js` passed.
  - `git diff --check` passed.
- Confirmed production data safety before running sync work:
  - Railway production services `Citadel-Archive`, `Citadel-GitHub-Sync`, and
    `Postgres` all reported `SUCCESS` and `stopped=false`.
  - Postgres still has its dedicated persistent `/var/lib/postgresql/data`
    volume; the web and GitHub sync services both have `/data` volumes.
  - The GitHub sync service has `DATABASE_URL` and
    `CITADEL_GITHUB_SYNC_TARGET_URL`, so the manual cron run targeted the
    production web API and production database path rather than local defaults.
- Ran the GitHub sync cron path manually through Railway production variables:
  - The run called `https://citadel-archive-production.up.railway.app/api/learning-agent/run`.
  - It completed with `ok=true`, `dry_run=false`, `ingested=true`, and
    `improved=false`.
  - It scanned 42 repositories, found 2 changed repositories, 50 organization
    events, 10 commits, 4 open PRs, and 6 merged PRs.
  - The security scanner returned `ok=true`, `blocked=false`, and
    `finding_count=0`; Google Chat remained disabled.
- Ran the Vault Backup Mirror cron wrapper safely through the production web API
  in dry-run mode:
  - The manifest dry run returned `ok=true`, tracked 3 files, found 2 available
    files, 1 missing Obsidian state file, and 105501 tracked bytes.
  - It wrote and published nothing because production backup mirror config still
    has `enabled=false` and push disabled.
  - The manifest policy still excludes raw tokens, secret values, source bodies,
    embeddings, vector indexes, graph databases, and large binaries.

## 2026-06-08

- Checked current Citadel automation and tightened the cron/gateway path:
  - GitHub reports no Actions workflows and no Actions runs for
    `masumi-network/Citadel-Archive`; active automation is Railway, not GitHub
    Actions.
  - Railway production has `Citadel-Archive`, `Citadel-GitHub-Sync`, and
    `Postgres` deployed successfully.
  - `Citadel-Archive` is running on
    `citadel-archive-production.up.railway.app`; recent logs show startup and a
    successful `/healthz` response, with no recent HTTP `>=400` logs returned.
  - `Citadel-GitHub-Sync` is scheduled at `0 3 * * *` UTC with next run
    `2026-06-09T03:00:00Z`. It still uses `CITADEL_RUN_MODE=github-sync`, which
    is a compatibility alias for the learning-agent cron wrapper.
  - The cron service has target URL, access key, and GitHub token configuration;
    Citadel Google Chat credentials are unset, matching the Scout-owned gateway
    boundary.
  - A dry-run invocation through Railway production variables completed with
    `ok=true`, scanned 42 repositories, found 7 changed repositories, 49 org
    events, 24 commits, 6 open PRs, and 12 merged PRs, and left ingestion plus
    gateway posting disabled.
  - Refactored learning-agent gateway delivery to post configured gateways
    concurrently and avoid recomputing gateway status in the status endpoint.
  - Updated cron logging to summarize sanitized generic gateway delivery status
    instead of only the legacy Google Chat compatibility field.
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
- Corrected the Agent Messenger boundary:
  - Reverted the Citadel Agent Messenger bridge/API/config commits because
    Citadel should remain shared memory, not a messaging agent.
  - Moved Agent Messenger delivery responsibility to Scout, where the update
    agent owns outbound gateway communication.
  - Updated the external-agent architecture note to name Agent Messenger as a
    Scout-owned gateway and state that Citadel should not become an Agent
    Messenger actor.
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
