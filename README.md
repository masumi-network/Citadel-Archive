# Citadel

Citadel is a thin self-hosted knowledge-base wrapper built on top of
[Cognee](https://github.com/topoteretes/cognee), which is Apache-2.0 licensed.

This repository does not vendor Cognee. It imports Cognee as a dependency so the
upstream package can be upgraded independently.

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
curl http://localhost:8000/readyz
```

Core API endpoints:

- `GET /api/session`
- `GET /api/mesh`
- `GET /api/indexes`
- `GET /api/github-sync`
- `GET /api/learning-agent`
- `GET /events`
- `POST /ingest`
- `POST /search`
- `POST /feedback`
- `POST /improve`
- `POST /api/self-upgrade`
- `POST /api/github-sync/run`
- `POST /api/learning-agent/run`

## Citadel UI

The hosted UI is served by the same FastAPI process. It includes:

- A live knowledge mesh canvas backed by `/api/mesh`.
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

Use the Access page to create a user or service-account token. The token is
shown once; Citadel stores only its hash, prefix, role, scopes, expiry, and
last-used timestamp. Existing env keys remain the bootstrap/local fallback.
API and MCP clients can pass the token with `Authorization: Bearer <token>`.

Admin APIs:

- `GET /api/access`
- `POST /api/access/tokens`
- `POST /api/access/tokens/{token_id}/revoke`
- `GET /api/audit`

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

Citadel can fetch public repository activity from a GitHub organization, format
it as a daily digest, add recent commit summaries for changed repositories,
ingest that digest into Cognee, and run improvement for the configured sync
session.

Default sync target:

```bash
CITADEL_GITHUB_ORG=masumi-network
CITADEL_GITHUB_SYNC_DATASET=masumi-network
CITADEL_GITHUB_SYNC_SESSION=masumi-github-daily
CITADEL_GITHUB_SYNC_STATE_PATH=/data/.citadel/github_sync_state.json
CITADEL_GITHUB_SYNC_MAX_COMMITS_PER_REPO=5
CITADEL_GITHUB_SYNC_INCLUDE_COMMITS=true
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

Citadel requests GitHub organization repositories with `type=all`, so private
repositories visible to the token are included alongside public repositories.

For OpenRouter, set either `LLM_API_KEY` or `OPENROUTER_API_KEY` and use
`LLM_MODEL=openrouter/free`. Citadel maps `OPENROUTER_API_KEY` to Cognee's
expected `LLM_API_KEY` at runtime when needed.

For Railway, create a second service from this repo with:

```bash
CITADEL_RUN_MODE=learning-agent
```

and set its cron schedule to:

```cron
0 3 * * *
```

That runs once every 24 hours at 03:00 UTC. The included `railway.toml` keeps
the web service as the default mode and switches to the learning-agent command
when `CITADEL_RUN_MODE=learning-agent`. The older `github-sync` run mode still
works for compatibility.

## MCP Server

Citadel includes a stdio MCP server for team agents. It calls the hosted
Citadel HTTP API and uses the same reader/writer/admin tokens as the UI.

```bash
CITADEL_HTTP_BASE_URL=https://citadel-archive-production.up.railway.app
CITADEL_MCP_ACCESS_TOKEN=ctdl_...
uv run python -m kb.mcp_server
```

Recommended token roles:

- Reader tokens: search, mesh, source status, resources.
- Writer tokens: reader tools plus `citadel_ingest` and feedback.
- Admin tokens: writer tools plus learning-agent runs and Cognee improvement.

Example Claude/Codex MCP command:

```json
{
  "command": "uv",
  "args": ["run", "python", "-m", "kb.mcp_server"],
  "env": {
    "CITADEL_HTTP_BASE_URL": "https://citadel-archive-production.up.railway.app",
    "CITADEL_MCP_ACCESS_TOKEN": "${CITADEL_MCP_ACCESS_TOKEN}"
  }
}
```

Exposed tools include `citadel_search`, `citadel_get_mesh`,
`citadel_list_sources`, `citadel_ingest`, `citadel_record_feedback`,
`citadel_run_learning_agent`, and `citadel_improve`.

## Python API

```python
import asyncio
from kb import Citadel


async def main() -> None:
    kb = Citadel.from_env()
    await kb.ingest("Citadel keeps my knowledge base organized.", tags=["personal"])
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
- One Railway Postgres service dedicated to Citadel.
- `pgvector` enabled in that Postgres database for the vector index.
- One Railway volume mounted at `/data` for Cognee's local Kuzu graph files.
- Cognee provider variables set on the web service through Railway variables.

Use Railway's private Postgres `DATABASE_URL` as the app database binding. If
your Cognee version expects split database variables instead of `DATABASE_URL`,
map Railway's `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`
values into the corresponding Cognee variables.

For the graph/mesh store, v1 uses Cognee's embedded Kuzu backend on the Railway
volume:

```bash
GRAPH_DATABASE_PROVIDER=kuzu
SYSTEM_ROOT_DIRECTORY=/data/.cognee_system
DATA_ROOT_DIRECTORY=/data/.data_storage
```

The GitHub sync cron service should also have a Railway volume mounted at
`/data` so `/data/.citadel/github_sync_state.json` persists between daily runs.

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
