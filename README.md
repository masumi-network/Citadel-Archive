# Citadel

Last updated: 2026-06-03.

Citadel is a thin self-hosted Organization Vault wrapper built on top of
[Cognee](https://github.com/topoteretes/cognee), which is Apache-2.0 licensed.

This repository does not vendor Cognee. It imports Cognee as a dependency so the
upstream package can be upgraded independently.

## Product Direction

Citadel is evolving into an **Organization Vault**: a cloud-hosted,
access-controlled shared memory layer that syncs approved sources, turns source
material into structured knowledge, and exposes that knowledge to teammates and
agents through the UI, API, and MCP.

The shareable plan lives in
[`docs/organization-vault-plan.md`](docs/organization-vault-plan.md). The
canonical domain language lives in [`CONTEXT.md`](CONTEXT.md). Architecture
decisions live in [`docs/adr/`](docs/adr/), and current refactor candidates live
in [`docs/architecture-deepening-opportunities.md`](docs/architecture-deepening-opportunities.md).

## Repository layout

| Repo | URL | Role |
|---|---|---|
| **Citadel Archive** (this repo) | https://github.com/masumi-network/Citadel-Archive | **Public** — app, MCP plugin, docs, agent skills (no vault content) |
| **Vault Backup Mirror** | https://github.com/masumi-network/Vault-Backup-Mirror | **Private** — NAS-style backup of vault evidence |
| **Railway deployment** | https://citadel-archive-production.up.railway.app | **Private** — live Organization Vault (search, ingest, mesh) |

What may be public vs private: [`docs/public-and-private.md`](docs/public-and-private.md)

| Agent skill | URL |
|---|---|
| Connect MCP | https://citadel-archive-production.up.railway.app/skills/connect |
| Use vault | https://citadel-archive-production.up.railway.app/skills/vault |
| Data boundary | https://citadel-archive-production.up.railway.app/skills/boundary |
| All skills | https://citadel-archive-production.up.railway.app/skills |
| Agent discovery manifest | https://citadel-archive-production.up.railway.app/.well-known/citadel.json |

The skills also live in the top-level `skills/` directory, so they can be
installed straight from this repo via [skills.sh](https://skills.sh):

```bash
npx skills add masumi-network/Citadel-Archive
```

The hosted `/skills` index includes `size_bytes`, `sha256`, and SRI-style
`integrity` metadata for each skill. The individual `/skills/*` markdown
responses include matching `X-Citadel-Skill-SHA256` and
`X-Citadel-Skill-Integrity` headers so agents can verify what they loaded.
The well-known discovery manifest repeats the skill metadata and lists the
hosted MCP endpoint, token requirements, tool policy metadata, and public/private
boundary rules without exposing vault content.

Verified team-share flow: see
[`docs/team-share-smoke-test.md`](docs/team-share-smoke-test.md).

## Agent Entrypoint

For a Codex-compatible agent, share this command first:

```bash
npx skills add masumi-network/Citadel-Archive
```

The installed root skill points the agent to the hosted MCP endpoint, the
connector skill, the vault usage skill, and the public/private boundary rules.

For agents that cannot install skills, share this URL instead:

```text
https://citadel-archive-production.up.railway.app/skills
```

Give every teammate or agent identity its own Citadel access token. Do not reuse
tokens between people, agents, or machines. Rotate a token immediately if it was
pasted into chat, logs, issues, PRs, or any public repo.

Verified on 2026-06-02 after commit `7a4a1d9`:

- `npx skills add masumi-network/Citadel-Archive` installs the root
  `citadel-archive` skill.
- Hosted MCP `/mcp/` lists tools and supports `citadel_session`,
  `citadel_search`, and `citadel_ingest`.
- A writer token can read and ingest through both direct HTTP and hosted MCP.

Copy-paste public smoke test:

```bash
export CITADEL_BASE_URL=https://citadel-archive-production.up.railway.app

curl -fsS "$CITADEL_BASE_URL/healthz"
curl -fsS "$CITADEL_BASE_URL/.well-known/citadel.json" | python3 -m json.tool
curl -fsS "$CITADEL_BASE_URL/skills" | python3 -m json.tool
curl -fsS "$CITADEL_BASE_URL/skills/connect" | sed -n '1,80p'
```

Copy-paste token smoke test:

Do not paste the token or vault search output into public repos, issues, or chats.

```bash
export CITADEL_BASE_URL=https://citadel-archive-production.up.railway.app
export CITADEL_MCP_ACCESS_TOKEN=ctdl_... # paste a reader/writer/admin token locally

curl -fsS -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  "$CITADEL_BASE_URL/api/session" | python3 -m json.tool

curl -fsS -X POST "$CITADEL_BASE_URL/search" \
  -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"query":"repositories commits events","dataset":"masumi-network","top_k":3}' \
  | python3 -m json.tool
```

Copy-paste local MCP wrapper start:

```bash
export CITADEL_HTTP_BASE_URL=https://citadel-archive-production.up.railway.app
export CITADEL_MCP_ACCESS_TOKEN=ctdl_... # paste locally; never commit
export CITADEL_MCP_DEFAULT_DATASET=masumi-network

uv run python -m kb.mcp_server
```

Mirror manifest export is available, with opt-in GitHub push to the private
mirror repo. See [`docs/vault-backup-mirror.md`](docs/vault-backup-mirror.md).

## What This Adds

- Pre-ingest filtering for empty, tiny, ignored, or duplicate inputs.
- Tag normalization and metadata helpers before content reaches Cognee.
- A small service layer around Cognee's public async API.
- Feedback helpers that write to Cognee session feedback and can trigger
  `cognee.improve()`.
- A simple `citadel` CLI for solo use today, with tenant/team config already
  represented through environment variables.

## Install

```bash
uv sync --dev
```

Copy `.env.example` to `.env` and fill in your providers, access keys, and
database settings.

Set `CITADEL_ADMIN_KEY` before exposing the service publicly. Add
`CITADEL_WRITER_KEYS` and `CITADEL_READER_KEYS` when sharing the workspace with
teammates.

Set `CITADEL_SEARCH_DEFAULT_DATASET` to the dataset that searches should target
when a request omits `dataset` (e.g. `masumi-network`). Without it, a
dataset-less `/search` queries the per-tenant `CITADEL_DEFAULT_DATASET`
(`personal`) and the response includes a `note` plus `known_datasets` instead of
silently returning an empty list.

For OpenRouter, Cognee expects the custom provider form:

```bash
LLM_PROVIDER=custom
LLM_ENDPOINT=https://openrouter.ai/api/v1
LLM_MODEL=openrouter/free
LLM_API_KEY=sk-or-...
```

## Run The HTTP Service

```bash
uv run uvicorn kb.server:app --reload --port 8000
```

Open `http://localhost:8000/` for the Citadel UI.

Health endpoints:

```bash
curl http://localhost:8000/healthz
curl -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" http://localhost:8000/readyz
```

Core API endpoints:

- `GET /api/session`
- `GET /api/mesh`
- `GET /api/indexes`
- `GET /api/sources`
- `GET /api/github-sync`
- `GET /api/learning-agent`
- `GET /events`
- `POST /api/obsidian/vaults`
- `GET /api/obsidian/manifest`
- `POST /api/obsidian/sync/push`
- `GET /api/obsidian/sync/pull`
- `POST /api/obsidian/conflicts/{conflict_id}/resolve`
- `GET /api/documents/{document_id}`
- `POST /ingest`
- `POST /search`
- `POST /feedback`
- `POST /improve`
- `POST /api/self-upgrade`
- `POST /api/github-sync/run`
- `POST /api/learning-agent/run`
- `POST /api/learning-agent/google-chat/test`

## Citadel UI

The hosted UI is served by the same FastAPI process. It includes:

- A live knowledge mesh canvas backed by `/api/mesh`.
- A stable Three.js 3D mesh view with deterministic node placement, restrained
  orbit controls, zoom limits, and desktop/mobile canvas coverage checks.
- An OS-style dashboard shell with system chrome, runtime metrics, source
  status, page navigation, access controls, and a persistent status bar.
- Server-Sent Events at `/events` for real-time ingest, search, feedback, and
  self-upgrade updates.
- Index status panels for graph, vector, feedback, and global context stores.
- Ingest, search, feedback, and self-upgrade controls that call the wrapper API.
- GitHub organization sync status and a manual run control for the Masumi
  Network repository digest.
- A source-learning agent API that can scan GitHub activity, summarize commits,
  ingest source digests, and trigger Cognee improvement.

Pages:

- Overview: runtime metrics and the knowledge mesh.
- Search: query existing indexed memory.
- Ingest: add new memory/source material to the archive.
- Feedback: record feedback against Cognee QA IDs.
- Sources: GitHub sync, indexes, and self-improvement controls.
- Access: role setup, teammate tokens, service-account tokens, and audit trail.

The first version visualizes Citadel's wrapper-level mesh activity. Deeper
Cognee graph introspection can be added behind the same `/api/mesh` contract
once the production Cognee database providers are finalized.

## Access Roles

Citadel supports bootstrap environment keys plus a lightweight persistent access
store for teammate and agent tokens.

```bash
CITADEL_READER_KEYS=alice-reader-key,bob-reader-key
CITADEL_WRITER_KEYS=teammate-writer-key
CITADEL_ADMIN_KEY=owner-admin-key
CITADEL_ACCESS_STORE_PATH=/data/.citadel/access.json
CITADEL_AUDIT_MAX_EVENTS=1000
```

Role permissions:

- Reader: view mesh, sources, indexes, events, and search.
- Writer: reader permissions plus ingest and feedback.
- Admin: writer permissions plus GitHub sync, self-upgrade, token creation,
  token revocation, and audit viewing.

Tokens are checked by both role and scope. Custom scopes can only reduce a
token's permissions within its role; Citadel rejects scopes that exceed the
selected role. For example, a writer token with only `kb:ingest` can ingest but
cannot search, record feedback, or run admin jobs.

Use the Access page to create a user or service-account token. The token is
shown once; Citadel stores only its hash, prefix, role, scopes, expiry, and
last-used timestamp. Existing env keys remain the bootstrap/local fallback.
API and MCP clients can pass the token with `Authorization: Bearer <token>`.

## Obsidian Vault Sync

Citadel includes an Obsidian-compatible source path for team vaults. The server
stores vault registration, document hashes, revisions, sync cursors, and
conflicts in:

```bash
CITADEL_OBSIDIAN_SYNC_STATE_PATH=/data/.citadel/obsidian_sync_state.json
```

The first sync mode is explicit push from an Obsidian plugin or API client. It
does not silently crawl a full vault and it does not overwrite local Obsidian
files from the server.

The private beta plugin scaffold lives in `plugins/obsidian-citadel/`. It uses
Obsidian `SecretStorage` for Citadel bearer tokens, `requestUrl` for HTTP, and
the Vault APIs for note reads/frontmatter updates.

Admin APIs:

- `GET /api/access`
- `POST /api/access/tokens`
- `POST /api/access/tokens/{token_id}/revoke`
- `GET /api/audit?view=all|mcp|access|failures&limit=50`
- `GET /api/backup-mirror`
- `POST /api/backup-mirror/run`

## CLI

```bash
uv run citadel ingest "A useful note" --tag personal --tag research
uv run citadel ingest ./notes.md --dataset personal
uv run citadel search "What did I learn about Railway?"
uv run citadel feedback <qa-id> --score 1 --text "Useful answer"
uv run citadel improve
uv run citadel sync-github --org masumi-network
uv run citadel learn --force
uv run python -m kb.github_sync --org masumi-network --dry-run
uv run python -m kb.learning_agent --status
```

## GitHub Organization Sync

Citadel can fetch repository activity from a GitHub organization, format it as a
daily digest, add recent commit summaries for changed repositories, ingest that
digest into Cognee, and run improvement for the configured sync session. When a
GitHub token can see private repositories, treat the sync as sensitive metadata.
See [`docs/private-github-sync-security.md`](docs/private-github-sync-security.md)
before enabling private repo access.

Default sync target:

```bash
CITADEL_GITHUB_ORG=masumi-network
CITADEL_GITHUB_SYNC_DATASET=masumi-network
CITADEL_GITHUB_SYNC_SESSION=masumi-github-daily
CITADEL_GITHUB_SYNC_STATE_PATH=/data/.citadel/github_sync_state.json
CITADEL_GITHUB_SYNC_MAX_COMMITS_PER_REPO=5
CITADEL_GITHUB_SYNC_MAX_PULL_REQUESTS_PER_REPO=5
CITADEL_GITHUB_SYNC_INCLUDE_COMMITS=true
CITADEL_GITHUB_SYNC_INCLUDE_PRIVATE=true
CITADEL_GITHUB_SYNC_REPO_ALLOWLIST=
CITADEL_GITHUB_SYNC_REPO_DENYLIST=
CITADEL_GITHUB_SYNC_SECURITY_SCAN_ENABLED=true
CITADEL_GITHUB_SYNC_SECURITY_BLOCK_SEVERITY=high
CITADEL_GITHUB_SYNC_OUTPUT_MODE=summary
```

Use `GITHUB_TOKEN` or `CITADEL_GITHUB_TOKEN` for higher GitHub API limits or
private repository access. Prefer `CITADEL_GITHUB_TOKEN` on both the web
service and the learning-agent/cron service. The token only needs read access to
the repositories Citadel should learn from; a fine-grained GitHub token scoped
to the Masumi organization repositories is enough. The public Masumi repository
scan works without a token.

For Railway, set the token on both services:

```bash
CITADEL_GITHUB_TOKEN=github_pat_...
```

Citadel requests GitHub organization repositories with `type=all` when
`CITADEL_GITHUB_SYNC_INCLUDE_PRIVATE=true`, so private repositories visible to
the token are included alongside public repositories. Use
`CITADEL_GITHUB_SYNC_REPO_ALLOWLIST` and `CITADEL_GITHUB_SYNC_REPO_DENYLIST` to
scope exactly what Citadel may learn from. The cron output defaults to a
sanitized summary and the pre-ingest metadata scanner blocks high-severity
secret, phishing-link, and corruption indicators before the digest is ingested.

For OpenRouter, set either `LLM_API_KEY` or `OPENROUTER_API_KEY` and choose a
concrete `LLM_MODEL` from the current OpenRouter model catalog. Citadel maps
`OPENROUTER_API_KEY` to Cognee's expected `LLM_API_KEY` at runtime when needed.
GitHub source sync does not require LLM improvement by default; enable
`CITADEL_GITHUB_SYNC_RUN_IMPROVE=true` only when the configured LLM is known to
work.
Organization digest LLM summarization is disabled for private repository
metadata unless `CITADEL_ORG_DIGEST_LLM_ALLOW_PRIVATE=true`.

For Railway, create a second service from this repo with:

```bash
CITADEL_RUN_MODE=learning-agent
```

and set its cron schedule to:

```cron
0 8 * * *
```

That runs once every 24 hours at 08:00 UTC, which is 10:00 Europe/Berlin during
summer time. If Railway cron remains UTC-only, adjust the cron expression when
Berlin switches between CET and CEST. The included `railway.toml` keeps
the web service as the default mode and switches to the learning-agent command
when `CITADEL_RUN_MODE=learning-agent`. The older `github-sync` run mode still
works for compatibility.

## Google Chat Organization Update Digest

Citadel can post an outbound-only **Organization Update Digest** to one
dedicated Google Chat space after the learning-agent cron runs. See
[`docs/google-chat-organization-update-digest-plan.md`](docs/google-chat-organization-update-digest-plan.md)
and [ADR 0002](docs/adr/0002-google-chat-app-auth-for-update-digests.md).

The long-term modular shape is a separate internal update-agent repository that
uses Citadel for source-linked vault context and owns scheduling plus delivery
gateways. The repo boundary and first contract are documented in
[`docs/internal-update-agent-architecture.md`](docs/internal-update-agent-architecture.md).
Keep only one production poster enabled at a time: either the Citadel cron
compatibility path below or the separate update-agent repo.

Phase 1 uses Google Chat API app authentication, not incoming webhooks. Configure
these only on the Railway learning-agent service unless manual posting from the
web service is needed. If `CITADEL_GITHUB_SYNC_TARGET_URL` points the cron at
the web service, then the web service is the process that posts to Google Chat
and must also have these Google Chat variables.

Google-side setup:

1. Enable the Google Chat API in the Google Cloud project for the Chat app.
2. Configure the Chat app name, avatar, description, and org visibility.
3. Create a service account in that project.
4. Add the Chat app to the dedicated Google Chat space.
5. Store the service account JSON as a Railway secret.
6. Set `CITADEL_GOOGLE_CHAT_SPACE_NAME` to the target `spaces/...` resource.

```bash
CITADEL_ORG_DIGEST_ENABLED=true
CITADEL_ORG_DIGEST_WINDOW_HOURS=24
CITADEL_ORG_DIGEST_POST_TO_CHAT=true
CITADEL_ORG_DIGEST_INCLUDE_PREVIEW_IN_CRON_OUTPUT=false
CITADEL_GOOGLE_CHAT_ENABLED=true
CITADEL_GOOGLE_CHAT_SPACE_NAME=spaces/...
CITADEL_GOOGLE_CHAT_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

Manual admin-triggered runs preview only by default. Add
`{"post_to_chat": true}` to `POST /api/learning-agent/run` or use
`uv run citadel learn --post-to-chat` when an explicit manual post is intended.

After configuring the Chat app and Railway variables, send one controlled test
message before enabling cron posting:

```bash
curl -fsS -X POST "$CITADEL_BASE_URL/api/learning-agent/google-chat/test" \
  -H "Authorization: Bearer $CITADEL_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  --data '{"message":"Citadel Google Chat delivery test"}'
```

The test endpoint is admin-only and stores only sanitized delivery status in the
audit log.

For future gateway adapters, use the generic admin-only smoke-test endpoint:

```bash
curl -fsS -X POST "$CITADEL_BASE_URL/api/learning-agent/gateways/google_chat/test" \
  -H "Authorization: Bearer $CITADEL_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  --data '{"message":"Citadel gateway delivery test"}'
```

## Vault Backup Mirror

Citadel includes a manifest-only Vault Backup Mirror exporter for the private
`masumi-network/Vault-Backup-Mirror` repository path. The first implementation
tracks state files by path, size, timestamp, and SHA-256 hash; it does not copy
raw source bodies, token stores, embeddings, vector indexes, graph databases, or
large binaries into the mirror.

```bash
CITADEL_BACKUP_MIRROR_REPO=masumi-network/Vault-Backup-Mirror
CITADEL_BACKUP_MIRROR_BRANCH=main
CITADEL_BACKUP_MIRROR_ROOT_PATH=/data/.citadel/backup_mirror
CITADEL_BACKUP_MIRROR_ENABLED=false
CITADEL_BACKUP_MIRROR_PUSH_ENABLED=false
```

Admin APIs:

- `GET /api/backup-mirror` shows tracked state files and latest manifest status.
- `POST /api/backup-mirror/run` accepts `{"dry_run": true}` by default.
- Non-dry-run local writes require `CITADEL_BACKUP_MIRROR_ENABLED=true`.
- GitHub publishing also requires `CITADEL_BACKUP_MIRROR_PUSH_ENABLED=true`
  and `CITADEL_BACKUP_MIRROR_TOKEN` with `contents: write` access to the private
  mirror repo.

Cron wrapper:

```bash
CITADEL_RUN_MODE=backup-mirror
CITADEL_BACKUP_MIRROR_TARGET_URL=https://citadel-archive-production.up.railway.app
CITADEL_BACKUP_MIRROR_ACCESS_KEY=ctdl_...
CITADEL_BACKUP_MIRROR_DRY_RUN=true
CITADEL_BACKUP_MIRROR_TOKEN=github_pat_... # only needed when push is enabled
uv run python scripts/run_railway.py
```

The current exporter writes local `manifests/latest.json` and dated
`snapshots/<date>/<snapshot_id>/manifest.json` files under
`CITADEL_BACKUP_MIRROR_ROOT_PATH`. When push is enabled, it commits those same
manifest files to the private mirror repository through the GitHub Contents API.

## MCP Server

Citadel serves a **hosted MCP endpoint** so agents connect with a URL and a
token — no clone, no local Python:

```text
https://citadel-archive-production.up.railway.app/mcp/
Authorization: Bearer ctdl_<token>
```

It is a streamable-HTTP server mounted into the same FastAPI process
(`kb/server.py` mounts `kb/mcp_server.py` at `/mcp/`). Each request is
authenticated by the caller's `ctdl_` bearer token — the same reader/writer/admin
tokens as the UI — and dispatched against the in-process API.

Forwarded MCP calls include `X-Citadel-MCP-Tool`, and Citadel records persistent
audit events for MCP-originated reads, writes, and admin jobs. Audit entries
capture actor, role, tool, path, required scope, dataset when known, status, and
safe counts or hashes. They do not store raw tokens, search queries, note bodies,
or feedback text.

Claude Code project `.mcp.json`:

```json
{
  "mcpServers": {
    "citadel": {
      "type": "http",
      "url": "https://citadel-archive-production.up.railway.app/mcp/",
      "headers": { "Authorization": "Bearer ${CITADEL_MCP_ACCESS_TOKEN}" }
    }
  }
}
```

The full per-client walkthrough (Cursor, Codex, the `mcp-remote` stdio bridge)
lives in the connect skill: `…/skills/connect`.

A **local stdio** server is still available for offline/dev use and points at the
hosted API:

```bash
CITADEL_HTTP_BASE_URL=https://citadel-archive-production.up.railway.app
CITADEL_MCP_ACCESS_TOKEN=ctdl_...
CITADEL_MCP_DEFAULT_DATASET=masumi-network
uv run python -m kb.mcp_server
```

Hosted-MCP environment (set on the Railway web service):

```bash
# Forwarded calls hit the API in-process; default targets http://127.0.0.1:$PORT.
CITADEL_MCP_SELF_BASE_URL=http://127.0.0.1:8000
# Optional: pin Host/Origin allow-lists (enables DNS-rebinding protection).
# Leave unset for a token-authenticated public endpoint.
CITADEL_MCP_ALLOWED_HOSTS=citadel-archive-production.up.railway.app
```

Recommended token roles:

- Reader tokens: search, mesh, source status, resources.
- Writer tokens: reader tools plus `citadel_ingest` and feedback.
- Admin tokens: writer tools plus learning-agent runs, backup-mirror exports,
  and Cognee improvement.
- Custom-scoped tokens are least-privilege subsets of those roles and are
  enforced server-side on API and MCP-forwarded calls.

Safe defaults:

- Use a reader service-account token for normal agent work.
- Configure the client to require approval for `citadel_ingest` and
  `citadel_record_feedback`.
- Configure the client to require approval, or keep disabled by default, for
  `citadel_run_learning_agent`, `citadel_run_backup_mirror`, and
  `citadel_improve`.
- Use `https://` for hosted Citadel URLs. The MCP wrapper only allows plain
  `http://` for localhost unless `CITADEL_MCP_ALLOW_INSECURE_HTTP=true` is set
  for a trusted development network.
- Keep `CITADEL_MCP_MAX_INGEST_BYTES` low enough that agents cannot accidentally
  push large logs or secrets into durable memory.
- Review `/api/audit` from an admin session when validating an agent rollout.
  MCP events appear as `mcp.<tool_name>` actions; admin MCP clients can also use
  `citadel_audit_events`.

Example Claude/Codex MCP command:

```json
{
  "command": "uv",
  "args": ["run", "python", "-m", "kb.mcp_server"],
  "env": {
    "CITADEL_HTTP_BASE_URL": "https://citadel-archive-production.up.railway.app",
    "CITADEL_MCP_ACCESS_TOKEN": "${CITADEL_MCP_ACCESS_TOKEN}",
    "CITADEL_MCP_DEFAULT_DATASET": "masumi-network"
  }
}
```

Exposed tools include `citadel_discovery`, `citadel_session`,
`citadel_search`, `citadel_get_document`, `citadel_get_mesh`,
`citadel_list_sources`, `citadel_ingest`, `citadel_record_feedback`,
`citadel_run_learning_agent`, `citadel_backup_mirror_status`,
`citadel_run_backup_mirror`, `citadel_audit_events`, and `citadel_improve`.
`citadel_discovery` returns the safe public manifest for connected agents;
`citadel_search` returns each hit with an additive `_citadel` provenance envelope
(`rank`, `dataset`, `result_id`, `content_sha256`, `provenance`, and
`retrieval`); `citadel_get_document` takes the `id` returned on a search hit when
`_citadel.retrieval.document_drilldown_available` is true.

The plugin is intentionally thin. It does not run a second Citadel backend. It
bundles `.mcp.json` and a small agent skill so Codex can launch the stdio MCP
server, pass `CITADEL_MCP_ACCESS_TOKEN`, and call the hosted Citadel API through
that server.

## Python API

```python
import asyncio
from kb import Citadel


async def main() -> None:
    kb = Citadel.from_env()
    await kb.ingest("Citadel keeps my Organization Vault organized.", tags=["personal"])
    results = await kb.search("What does Citadel do?")
    print(results)


asyncio.run(main())
```

## Multi-Tenant Shape

Start solo with:

```bash
CITADEL_TENANT_ID=personal
CITADEL_DEFAULT_DATASET=personal
```

When adding teammates later, keep the same wrapper and change tenant/user
configuration at deployment or request boundaries. The service layer accepts
dataset, session, and tenant-aware configuration without changing Cognee internals.

## Railway Hosting

This repo now includes `railway.toml`, so Railway can run Citadel as a web
service with:

```bash
uvicorn kb.server:app --host 0.0.0.0 --port $PORT
```

Recommended first deployment shape:

- One Railway web service for this repository.
- One Railway cron service for daily GitHub syncs.
- One Railway cron service for Vault Backup Mirror manifest export.
- One Railway Postgres service dedicated to Citadel.
- `pgvector` enabled in that Postgres database for the vector index.
- One Railway volume mounted at `/data` for Cognee's local Kuzu graph files.
- Cognee provider variables set on the web service through Railway variables.

Use Railway's private Postgres `DATABASE_URL` as the app database binding. At
runtime Citadel derives Cognee's split `DB_*` settings from `DATABASE_URL` when
needed, and maps `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, and
`DB_PASSWORD` into `VECTOR_DB_*` when `VECTOR_DB_PROVIDER=pgvector`. Set
explicit `VECTOR_DB_*` variables only when the vector store uses a different
Postgres target.

For the graph/mesh store, v1 uses Cognee's embedded Kuzu backend on the Railway
volume:

```bash
GRAPH_DATABASE_PROVIDER=kuzu
SYSTEM_ROOT_DIRECTORY=/data/.cognee_system
DATA_ROOT_DIRECTORY=/data/.data_storage
```

The GitHub sync and backup mirror cron services should also have a Railway
volume mounted at `/data` so `/data/.citadel/github_sync_state.json` and
`/data/.citadel/backup_mirror/` persist between runs. Set `CITADEL_RUN_MODE` to
`learning-agent` for source sync or `backup-mirror` for mirror manifest export.

For later team use, move the graph store to Neo4j or Memgraph without changing
Citadel's wrapper code.

After creating Railway Postgres, enable pgvector in the database before
production ingest:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Railway should keep the app and database in the same project/environment so the
database stays private to Citadel.

## Attribution

Citadel builds on Cognee and preserves upstream attribution. Cognee is developed
by Topoteretes UG and is licensed under Apache-2.0.
