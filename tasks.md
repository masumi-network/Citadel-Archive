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

## Current Railway State

- Latest deploy was triggered after `requirements.txt`.
- Build installed deps correctly.
- Last observed status: deploying, not yet verified live.
- Health URL still needs final check:
  - `https://citadel-archive-production.up.railway.app/healthz`
- UI URL still needs final check:
  - `https://citadel-archive-production.up.railway.app/`

## Needed From User

- OpenRouter API key.
  - Set as `LLM_API_KEY`.
  - Current model config:
    - `LLM_PROVIDER=custom`
    - `LLM_ENDPOINT=https://openrouter.ai/api/v1`
    - `LLM_MODEL=openrouter/google/gemini-2.0-flash-lite-preview-02-05:free`
- Enable pgvector in Railway Postgres.
  - Run in DB console/psql:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

- Optional: rotate `CITADEL_ADMIN_KEY` after first login test.

## Next

- Check Railway deploy status/logs.
- Verify `/healthz`.
- Verify `/login` redirects from `/`.
- Verify admin key unlocks UI.
- Set OpenRouter key.
- Redeploy/restart app.
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
