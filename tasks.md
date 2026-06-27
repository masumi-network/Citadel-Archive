# Citadel Tasks

## ADR-0007 execution — seat capture, promotion, write policy (~15% overall)

**Plan:** [`docs/adr-0007-shipping-plan.md`](docs/adr-0007-shipping-plan.md)  
**ADR:** [`docs/adr/0007-seat-capture-promotion-write-policy.md`](docs/adr/0007-seat-capture-promotion-write-policy.md)

### Checkpoints

- [x] P0 Glossary + ADR-0007 + shipping plan + progress (2026-06-27)
- [x] P2 MCP seat write guards + secret scan extensions (local, pending deploy)
- [x] **P1 Seat write policy on all HTTP paths** (2026-06-27)
- [x] P3 Server capture policy API + admin baseline (2026-06-27)
- [x] P4 `citadel setup` + `citadel capture` + local allowlist (2026-06-27)
- [x] **CLI shipped** — `citadel onboard`/`status`/`tui`, headless `--json`,
  branded home screen; **published to PyPI** as `citadel-archive` v0.1.2 +
  bootstrap installer (beyond ADR-0007 scope; see progress.md) (2026-06-27)
- [ ] P5 Promotion Agent (GitHub + Central refs, tags, 6h + on demand)
- [ ] P6 Promotion Approval queue (dashboard + MCP, admin delegate + audit)

### P1 — Seat write policy ✅ (2026-06-27)

- [x] `guard_seat_write_policy` + `resolve_write_targets` seat branch
- [x] Seat org/Central/promotion tags → 403 on ingest
- [x] Seat `/api/contribute` → 403
- [x] Obsidian org tags stripped; push stays on **Node**
- [x] Admin / non-seat Central path unchanged; **385 tests** passing

### P3 — Capture policy ✅ (2026-06-27)

- [x] `GET/PUT /api/access/seats/{slug}/capture-policy` + org baseline endpoint
- [x] `merged_deny_globs` merges env excludes + org defaults + seat baseline
- [x] Settings + Access UI snippets for admin view/edit

### P4 — Capture CLI ✅ (2026-06-27)

- [x] 4.1 `citadel setup` wizard → `~/.citadel/capture.json` (roots + Capture Root Tags) (2026-06-27)
- [x] 4.2 `citadel capture` — summarize approved roots, POST to **Node** (2026-06-27)
- [x] 4.3 Git pre-push hook gates on local allowlist (skip + warn outside roots) (2026-06-27)
- [x] 4.4 Docs: teammate-rollout step 5 + proactive-ingest skill (2026-06-27)
- [x] Unit + API tests

---

## Phase 2 execution — sequential (~99% overall)

**Plan:** [`docs/phase-2-shipping-plan.md`](docs/phase-2-shipping-plan.md)

M0–M5 shipped on `main` (`5f6c0ed`+). Graph Phase 2 uses a **unified org view**
(seat **Nodes** + **Central** together — no scope toggles). M6 production rollout
pending: Linear read-only key, `linear-sync` cron, Central cognify verify, per-dev
`install_autosync.sh`.

### Checkpoints

- [x] M0 Graph Phase 1 merged (PR #5)
- [x] M1 Git push sync (`sync_push.py`, 7 tests)
- [x] M2 Session + IDE docs, `install_autosync.sh`
- [x] M3 Linear backend (ADR-0004, `/api/linear-sync`)
- [x] M4 MCP `citadel_linear_my_issues`, `citadel_linear_search`
- [x] M5 Graph unified org view / depth / spokes (scope toggles removed; depth
      0–3 + Central↔seat hub spokes)
- [x] M5.5 Browser QA (2026-06-25): prod healthz/login/asset 200, login renders
      desktop+mobile, graph toolbar (mode/depth/fit/pause) verified in code

### M6 — Production rollout

- [x] Phase 2 merged to `main` (`5f6c0ed`+)
- [x] Cognify **Central** unblocked (`LLM_MODEL` fix 2026-06-24; optional
      `POST /api/cognify/run?force=true` for stale graph store)
- [ ] **Full graph repopulation** — fixes verified (2026-06-26):
      `/api/mesh/graph` now displays (25 nodes) after a partial re-ingest. The
      complete GitHub re-sync 502s through the public proxy, so run it via the
      internal cron (`Citadel-GitHub-Sync`, 2400s timeout) or wait for the next
      scheduled run, then confirm `/api/mesh/graph` climbs toward the full
      corpus (~214). (Optional cleanup: remove the `COGNIFY_TEST_MARKER` node.)
- [x] M6.5 teammate one-pager: [`docs/onboarding/teammate-rollout.md`](docs/onboarding/teammate-rollout.md)
- [ ] Set read-only `CITADEL_LINEAR_API_KEY` (Linear **Read** scope) on Railway web
- [ ] Create Railway `linear-sync` cron (`CITADEL_RUN_MODE=linear-sync`)
- [ ] Verify sync: `GET /api/linear-sync` → `enabled`, `issue_count`, `last_synced_at`
- [ ] Per-dev `skills/citadel-proactive-ingest/scripts/install_autosync.sh`

---

## Done (2026-06-25 session — Phase 2 implementation)

- Graph Phase 1 production (PR #5). Git push sync, Linear sync + mirror, unified
  org graph UI, MCP tools, IDE onboarding. Tests 346 passing.

## Done (2026-06-25 session — planning)

- Fixed broken production ingest: the invalid `LLM_MODEL=openrouter/free` (every
  cognify call failed) -> `openrouter/openai/gpt-4o-mini`. Verified end-to-end.
- Upgraded cognee 1.1.2 -> 1.2.1 (PR #2), deployed + verified.
- Added re-cognify / verify recovery tooling: `POST /api/cognify/run`,
  `citadel cognify [--verify]`, `CITADEL_RUN_MODE=cognify` / `cognify-verify` (PR #2).
- Fixed the GitHub-Sync cron 502 (internal domain + `*_TIMEOUT_SECONDS=2400`).
- Shipped per-seat onboarding (PR #3): connect wizard, self-describing seat
  (`resolved_memory_scope` + tool docstrings), admin `GET /api/access/seats`.
- Shipped autonomous personal-KB sync (PR #4): `citadel-proactive-ingest` skill +
  a project-committed Claude Code `SessionEnd` hook (`sync_session.py`) +
  `docs/onboarding/citadel-autosync.md`. Teammates are headless (token + MCP +
  skill, no dashboard login).
- Backprop-fixed the time-dependent `test_github_sync` PR-window test.
- Completed knowledge-graph redesign Phase 1 (`feat/graph-logseq`): vendored 2D
  `force-graph` replacing the Three.js scene, shared Central pinned as the center hub,
  hover/click/labels, Activity + Knowledge graph modes.
- Tests 312 -> 328. See `docs/progress.md` (2026-06-24) for detail.

## Done

- Repo reset from Cognee fork -> clean Citadel wrapper.
- Cognee kept as dep only. No vendored upstream source.
- Python package `citadel`, import package `kb`.
- CLI added: ingest, search, feedback, improve.
- FastAPI service added.
- Railway config added.
- Hosted UI added at `/`.
- Live mesh UI added:
  - graph canvas
  - index panels
  - ingest form
  - search form
  - self-upgrade button
  - SSE live events
- Admin key gate added:
  - `/login`
  - `/admin/session`
  - `/admin/logout`
  - UI/API/SSE protected
  - `/healthz` public for Railway health
- Railway resources created/wired:
  - app service: `Citadel-Archive`
  - Postgres service: `Postgres`
  - app volume: `/data`
  - Postgres refs wired into app vars
  - Kuzu graph path -> `/data/.cognee_system`
  - data path -> `/data/.data_storage`
- Runtime deps made explicit via `requirements.txt`.
- Tests passing locally: `18 passed`.
- GitHub organization sync added:
  - fetches `masumi-network` repos and public org events
  - creates a daily digest
  - ingests digest into Citadel
  - runs improvement for `masumi-github-daily`
  - persists scan state at `/data/.citadel/github_sync_state.json`
  - admin API added: `/api/github-sync`, `/api/github-sync/run`
- UI pass added:
  - GitHub sync status/manual run panel
  - richer runtime stats
  - better loading/empty/error states
  - improved mobile layout and focus/interaction states
- Feedback UI added:
  - manual QA ID feedback form
  - score selection and optional note/dataset/session metadata
  - search-result helper button when a QA ID is present
  - mesh feedback counter/status updates
- OS dashboard redesign added:
  - top system bar and persistent status chrome
  - separate pages for overview, search, ingest, feedback, sources, events, and access
  - left workspace navigation rail
  - central mesh window and runtime metrics strip
  - responsive mobile/tablet layout smoke-checked with browser automation
- Role-based access keys added:
  - reader keys can view/search only
  - writer keys can ingest and record feedback
  - admin key can run GitHub sync, self-upgrade, and view access setup
  - `/api/session` exposes current role/capabilities to the UI
- Agent access research captured:
  - docs note: `docs/agent-access-model.md`
  - decision: build one secure Citadel MCP server as the shared capability layer
  - wrap the MCP server with thin Claude/Codex skills or plugins for workflows
  - keep Search and Ingest as separate read/write surfaces
- Persistent access-token foundation added:
  - JSON-backed access store at `CITADEL_ACCESS_STORE_PATH`
  - `User`/`ServiceAccount`-style principals
  - hashed API tokens with prefix, role, scopes, expiry, last-used timestamp,
    and revoked state
  - admin APIs for access snapshot, token creation, token revocation, and audit
  - Access page token creation/list/revoke/audit UI
  - tests passing locally: `20 passed`
- Production health verified on 2026-05-21:
  - `Citadel-Archive`, `Citadel-GitHub-Sync`, and `Postgres` all `SUCCESS`
  - `/healthz` returns `{"ok":true,"service":"citadel"}`
  - `/` redirects to `/login`
- Railway cron service created:
  - service: `Citadel-GitHub-Sync`
  - schedule: `0 3 * * *`
  - volume: `/data`
- Source learning-agent foundation added:
  - wraps GitHub source sync as `kb.learning_agent`
  - captures recent commit summaries for changed repositories
  - API added: `/api/learning-agent`, `/api/learning-agent/run`
  - CLI added: `citadel learn`
  - Railway run mode supports `CITADEL_RUN_MODE=learning-agent`
- MCP support added:
  - stdio server: `uv run python -m kb.mcp_server`
  - tools for search, mesh, sources, ingest, feedback, learning-agent run, and improve
  - resources for session, sources, indexes, and recent events
  - prompts for answer-from-KB, ingest decision, and source-change summaries
  - HTTP bearer tokens reuse Citadel reader/writer/admin access roles
  - project `.mcp.json` added with `CITADEL_MCP_ACCESS_TOKEN` env expansion
- Organization Vault dashboard build started:
  - added Knowledge, Agents, Audit, and Settings workspace pages
  - made Search the default reader page when no hash route is selected
  - surfaced repository daily update, source snapshot, index, and runtime event state
  - surfaced service-account tokens, MCP setup snippets, and role/tool matrix
  - surfaced access audit and runtime activity side by side
  - surfaced readiness and learning-agent runtime checks
  - reduced duplicate dashboard navigation chrome and made mobile content-first
  - rewrote the overview header around current vault state and primary actions
  - tests passing locally: `30 passed`
- Production rollout verified on 2026-06-02:
  - functional rollout commit: `cd33217` (`fix(mcp): default search to company dataset`)
  - Railway web deployment: `891c81ee-4c44-4303-8792-0a282d9d62be` (`SUCCESS`)
  - `/healthz` returns `{"ok":true,"service":"citadel"}`
  - `/skills` returns HTTPS URLs plus content hashes for hosted skills
  - `/.well-known/citadel.json` returns MCP, skill, auth, tool-policy, and
    boundary metadata without vault contents
  - `/search` returns additive `_citadel` provenance and retrieval metadata on
    dict results so agents can cite and decide when drill-down is available
  - Dashboard search cards surface `_citadel` provenance and only show source
    drill-down links when the backend marks them available
  - HTTP responses include baseline browser security headers; HSTS is limited to
    HTTPS/HTTPS-forwarded requests
  - Private/authenticated responses default to `Cache-Control: no-store`; public
    skill/discovery/static metadata is short-cacheable
  - failed deployment `7658403e-d79e-4d89-969b-34bb3aa45374` was caused by
    Railway health checks receiving `404` from `/healthz`; fixed in `68d729e`
  - `CITADEL_MCP_DEFAULT_DATASET=masumi-network` added for company MCP search
  - MCP `citadel_search` returns live results through the reader service account
  - local test suite passing: `53 passed`
- Company reader service-account token created for MCP bootstrap:
  - role: reader
  - scopes: `kb:read`, `kb:search`, `sources:read`, `obsidian:sync:pull`
  - raw token stored only in ignored local `.citadel/company-reader-mcp.env`
- Team-share flow verified on 2026-06-02:
  - share command: `npx skills add masumi-network/Citadel-Archive`
  - production verification commit: `7a4a1d9`
  - hosted MCP `citadel_session`, `citadel_search`, and `citadel_ingest`
    succeed with a writer token
  - rotate any token that was pasted into chat or logs before team rollout
- MCP audit trail added:
  - forwarded MCP calls are tagged with `X-Citadel-MCP-Tool`
  - persistent audit events use `mcp.<tool_name>` actions
  - events capture actor, role, tool, required scope, dataset when known, and
    success/failure
  - audit details store safe counts and hashes instead of raw tokens, queries,
    note bodies, or feedback text
- Token scopes are enforced server-side:
  - protected API routes use role plus required scope checks
  - bootstrap env keys receive the default scopes for their role
  - service-account tokens can be narrowed to custom scopes
  - custom scopes that exceed the selected role are rejected
- Admin audit dashboard can filter MCP-originated events, non-MCP access/admin
  events, and failures; MCP summary counts are visible in the Audit page.
- Live learning-agent sync run on 2026-06-02:
  - scanned 41 repositories
  - processed 50 organization events and 198 commits
  - ingestion accepted for the `masumi-network` dataset
- Vault Backup Mirror initialized:
  - repo: `masumi-network/Vault-Backup-Mirror`
  - visibility: private
  - branch: `main`
  - scaffold commit: `deeb1c9`
- GitHub sync cron verified on 2026-06-03:
  - service: `Citadel-GitHub-Sync`
  - scheduled run logged at `2026-06-03T03:04:06Z`
  - result: `ingested=true`, `dry_run=false`, `improved=false`
  - next scheduled run: `2026-06-04T03:00:00Z`
- Hosted MCP/security rollout deployed on 2026-06-03:
  - production commit: `3c70e92`
  - `/healthz` returns `200` with private no-store cache policy and security headers
  - `/.well-known/citadel.json` returns public discovery metadata and advertises
    `/mcp/`
  - legacy `/mcp` redirects to `/mcp/` with relative `Location: /mcp/`
  - hosted MCP `initialize` returns `200`
  - hosted MCP `tools/list` returns 13 tools
  - hosted MCP `citadel_session` succeeds and writes an `mcp.citadel_session`
    audit event
  - backup-mirror dry-run returns `ok=true`, `written=false`, `published=false`

## Current Railway State

- Web service `Citadel-Archive` is live and auto-deploys `main`:
  - `https://citadel-archive-production.up.railway.app/healthz` (200)
  - `https://citadel-archive-production.up.railway.app/` and `/mcp/`
- Running **cognee 1.2.1** (upgraded + deployed + verified 2026-06-24).
- `LLM_MODEL=openrouter/openai/gpt-4o-mini` on the web service (was the invalid
  `openrouter/free`, which had silently broken all cognify; fixed 2026-06-24).
  `EMBEDDING_PROVIDER=fastembed`, `VECTOR_DB_PROVIDER=pgvector`,
  `GRAPH_DATABASE_PROVIDER=kuzu`, `CITADEL_SEARCH_DEFAULT_DATASET=masumi-network`.
- Cron `Citadel-GitHub-Sync` (schedule `0 3 * * *`): now targets the internal
  domain `http://citadel-archive.railway.internal:8080` with
  `CITADEL_GITHUB_SYNC_TIMEOUT_SECONDS=2400` to avoid the public-proxy 5-min 502 on
  the ~26-min sync (fixed 2026-06-24). Its own stale `LLM_MODEL=openrouter/free` is
  moot in this mode (cognify runs in the web service).
- Postgres healthy; pgvector working (ingest -> cognify -> search verified
  end-to-end 2026-06-24).
- Live deploy is commit `171f386` (web deployment `e225c16a`, `SUCCESS`).
- **LLM_MODEL fixed (2026-06-26):** was the prefix-less `google/gemini-2.5-flash`
  (broke all cognify with litellm "LLM Provider NOT provided"); now
  `openrouter/deepseek/deepseek-v4-flash`. cognify verified to build a
  214-node / 385-edge graph.
- **cognee partitioning disabled:** `ENABLE_BACKEND_ACCESS_CONTROL=false` so the
  org-wide graph read and cognify share one global Kuzu graph (the prior default
  partitioned the built graph into a per-dataset `.pkl` the read never resolved).
- **Knowledge graph display fixed + verified (2026-06-26):** `/api/mesh/graph`
  returns **25 nodes / 38 edges, `fallback:false`** (was `graph_empty`);
  `/search` works (vector). 25 nodes is partial (interrupted re-ingest + a verify
  marker); full repopulation (~214) needs the complete GitHub re-sync via the
  internal cron (the public proxy 502s on it) or the next scheduled cron run. No
  `seat:` nodes exist yet; Linear sync is `enabled:false` (no key).

## Needed From User

- **Run the Cognee graph recovery** (confirmed needed 2026-06-26): prod
  `/api/mesh/graph` is `graph_empty` (0 nodes) despite 45 added GitHub docs, so
  the knowledge-graph view and graph-backed retrieval are non-functional.
  Trigger `POST /api/cognify/run?force=true` (admin) or a one-off
  `CITADEL_RUN_MODE=cognify` Railway run to build the graph. Vector search is
  unaffected (works today).
- **Operational rollout of autonomous sync** (not code): provision a seat per dev
  via the connect wizard, then each dev exports `CITADEL_MCP_ACCESS_TOKEN` and runs
  `skills/citadel-proactive-ingest/scripts/install_autosync.sh` per org-repo clone.
  See [`docs/onboarding/teammate-rollout.md`](docs/onboarding/teammate-rollout.md).
- **Linear rollout** (operator): set read-only `CITADEL_LINEAR_API_KEY` on Railway
  web + create `linear-sync` cron; verify `GET /api/linear-sync`.
- **Rotate `CITADEL_ADMIN_KEY`** — it was used over the wire during the 2026-06-24
  debugging; rotate it (and consider rotating the GitHub PAT + OpenRouter key, which
  live in plaintext Railway env).
- OpenRouter model/key config (done):
  - `OPENROUTER_API_KEY` set on `Citadel-Archive`; `Citadel-GitHub-Sync` references
    the same key; Citadel maps it to Cognee's `LLM_API_KEY` at runtime.
  - `LLM_PROVIDER=custom`, `LLM_ENDPOINT=https://openrouter.ai/api/v1`,
    `LLM_MODEL=openrouter/openai/gpt-4o-mini` (web service).
- pgvector: working (cognify + search verified end-to-end). The earlier
  `CREATE EXTENSION IF NOT EXISTS vector` step is no longer outstanding.

## Research-Backed Direction

- Citadel should act like a workspace OS for the Organization Vault, not a
  single crowded dashboard page.
- MCP is the main integration surface for Claude Code, Codex, OpenAI
  Responses/Agents workflows, and future autonomous agents.
- Skills/plugins are distribution and workflow wrappers. They should not own
  authorization or duplicate Citadel business logic.
- Team access should move from shared env keys to durable principals:
  - users
  - service accounts
  - teams
  - memberships
  - role-based API tokens for Phase 1
  - scoped API tokens after the initial team workflow is proven
  - audit events
- Human access should use browser sessions. Agent access should use bearer
  tokens first, then OAuth/OIDC for hosted production.
- Sensitive agent tools must require approval:
  - source sync
  - self-improve
  - reindex/delete
  - invite/team changes
  - token creation
- Vault Backup Mirror private repo: `masumi-network/Vault-Backup-Mirror` (created).
  Citadel Archive is public. Large blobs should move to object storage if the
  mirror approaches GitHub repository limits.

## Backlog (after Phase 2 ships)

- **Better admin panel for access / tokens / keys / seats** (user request
  2026-06-26): turn the Access page into a complete admin console — create +
  revoke API tokens and bootstrap keys, full **seat lifecycle** (provision /
  view / revoke / rotate), and clear per-principal management. Basic
  create/list/revoke exists today (`kb/access.py`, `/api/access`,
  `/api/access/tokens`, `/api/access/seats`, Access page); this is the UX +
  completeness pass (rotation, key management, disable-principal). Ties into the
  UI-minimalization track (Access absorbs Agents + Audit into one admin home).
- Create the Railway `backup-mirror` cron service after deciding whether the
  first scheduled runs should stay dry-run or write local manifests.
- Multi-dataset search (own node + Central in one query).
- Tag routing for node vs Central lanes.
- Verify admin key unlocks UI; test hosted feedback with real Cognee QA ID.
- Issue fresh per-teammate/per-agent tokens for rollout.

## Next

Finish **M6 rollout:** set read-only `CITADEL_LINEAR_API_KEY` on Railway web +
`linear-sync` cron → `POST /api/linear-sync/run` or wait for cron → verify
`GET /api/linear-sync` → re-cognify **Central** if needed → per-dev
`install_autosync.sh`. See [`docs/onboarding/teammate-rollout.md`](docs/onboarding/teammate-rollout.md).

## Next: Team Access

- Keep Phase 1 whole-vault access constrained by reader/writer/admin role.
- Later add full team/membership scoping:
  - named teams
  - memberships between users/service accounts and teams
  - dataset-scoped grants
- Add token expiry validation UI and creation controls.
- Add token rotation flow.
- Add disabled principal flow.
- Add admin Access UI:
  - edit teammate/service-account role
  - assign dataset/team scope after scoped access is introduced
  - rotate token
  - disable principal
- Keep existing env role keys as bootstrap/local fallback.

## Next: Agent Integrations

- Add Codex skill or plugin package:
  - `SKILL.md` workflow instructions
  - bundled MCP server config
  - install/setup docs
- Add Claude Code skill:
  - search-before-answer workflow
  - ingest-project-decision workflow
  - source-sync/admin workflow

## Next: Dashboard

- Continue OS-style page deepening:
  - add richer Knowledge document/source drilldowns
  - add drill-down views for MCP audit events and linked source documents
  - add audit export and event detail pages on top of `/api/audit?view=...`
  - add editable Settings controls after backend policy modules exist
- Make Sources/Ingest the default writer workspace.
- Make Home/Access/Agents/Audit the admin workspace.
- Add model/provider state once the server exposes it safely.
- Add Vault Backup Mirror write controls and export history drill-downs.

## Later

- OAuth/OIDC login for hosted team deployments.
- Dataset-level and team-level ACLs.
- Approval queue for high-impact agent actions.
- Rate limiting per user/service account/tool.
- Structured audit export.
- Secret rotation reminders.
- Prompt-injection hardening for retrieved vault content:
  - mark retrieved text as untrusted context
  - keep source citations
  - reject tool instructions found inside retrieved content
- OAuth 2.1 + Protected Resource Metadata for remote hosted MCP.
- Secure MCP tunnel option for private/on-prem deployments.
- Mesh introspection:
  - pull real Cognee graph nodes
  - pull real vector index stats
  - show failed pipeline jobs
  - show memify/self-upgrade history

## Done (2026-06-10 improvement pass)

- Production hardening:
  - structured logging with secret redaction across `kb/` (`CITADEL_LOG_LEVEL`)
  - shared retry helper with jitter + Retry-After (`kb/retry.py`) applied to GitHub sync, backup mirror, Google Chat, digest LLM
  - expired/revoked tokens rejected centrally with `access.token.rejected` audit events
  - tests for security_scan, google_chat, access, mesh, obsidian_sync, learning_agent
- Knowledge Conflicts (per CONTEXT.md):
  - `kb/conflicts.py` store + detection (Obsidian push conflicts, ingest content-hash mismatch)
  - `GET /api/conflicts`, `POST /api/conflicts/{id}/resolve`, mesh `conflict` events
  - Conflicts page in dashboard with resolve flow
- Real Knowledge Mesh:
  - `GET /api/mesh/graph` pulls actual Cognee/Kuzu nodes + edges (Later item "pull real Cognee graph nodes" done)
  - dashboard Activity <-> Knowledge-graph toggle
- Architecture deepening:
  - Learning Process isolated into `kb/learning.py`
  - Repository Daily Update rules isolated into `kb/repository_update.py`
- Obsidian-style dashboard redesign (dark minimal theme, sidebar, design tokens).
- LLM-assisted learning:
  - `kb/llm_enrichment.py` semantic chunking + summaries/tags (default model `deepseek/deepseek-v4-flash`, deterministic fallback, secret-gated)
  - `kb/self_improve.py` bounded self-improvement pass + `POST /api/learning-agent/optimize`
- Cron pipeline mode (`CITADEL_RUN_MODE=pipeline`): github sync -> skills refresh -> self-improve -> backup mirror, per-stage toggles.
- Teammate/agent access:
  - `POST /api/contribute`, `GET /api/knowledge`, MCP `citadel_contribute` tool
  - README "For Teammates & Agents" section
- SKILL.md + skills/ updated for the current API surface.
- Tests: 262 passing.
