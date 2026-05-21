# Citadel Tasks

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
- Tests passing locally: `14 passed`.
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
- Railway cron service created:
  - service: `Citadel-GitHub-Sync`
  - schedule: `0 3 * * *`
  - volume: `/data`

## Current Railway State

- Web service is live:
  - `https://citadel-archive-production.up.railway.app/healthz`
  - `https://citadel-archive-production.up.railway.app/`
- Cron service is deployed with the latest local code.
- OpenRouter is configured through `OPENROUTER_API_KEY` and
  `LLM_MODEL=openrouter/free` on both Railway services.

## Needed From User

- OpenRouter model/key config is done:
  - `OPENROUTER_API_KEY` is set on `Citadel-Archive`.
  - `Citadel-GitHub-Sync` references the same key.
  - Citadel maps `OPENROUTER_API_KEY` to Cognee's expected `LLM_API_KEY`
    at runtime.
  - `LLM_PROVIDER=custom`
  - `LLM_ENDPOINT=https://openrouter.ai/api/v1`
  - `LLM_MODEL=openrouter/free`
- Enable pgvector in Railway Postgres.
  - Run in DB console/psql:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

- Optional: rotate `CITADEL_ADMIN_KEY` after first login test.

## Next

- Verify cron service next run/status.
- Verify admin key unlocks UI.
- Verify `/api/github-sync` in the hosted UI.
- Run GitHub sync once manually.
- Test real ingest -> Cognee -> Postgres/pgvector/Kuzu.
- Test search.
- Test feedback.
- Test self-upgrade.

## Later

- Admin dashboard:
  - orgs
  - managers
  - members
  - roles
  - access grants
  - invite flow
  - audit log
- Auth hardening:
  - hashed admin secrets
  - session expiry UI
  - per-org RBAC
  - API tokens
- Mesh introspection:
  - pull real Cognee graph nodes
  - pull real vector index stats
  - show failed pipeline jobs
  - show memify/self-upgrade history
