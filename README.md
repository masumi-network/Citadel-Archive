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

Copy `.env.example` to `.env` and fill in your providers and database settings.

## Run The HTTP Service

```bash
uv run uvicorn kb.server:app --reload --port 8000
```

Health endpoints:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Core API endpoints:

- `POST /ingest`
- `POST /search`
- `POST /feedback`
- `POST /improve`

## CLI

```bash
uv run citadel ingest "A useful note" --tag personal --tag research
uv run citadel ingest ./notes.md --dataset personal
uv run citadel search "What did I learn about Railway?"
uv run citadel feedback <qa-id> --score 1 --text "Useful answer"
uv run citadel improve
```

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
- One Railway Postgres service dedicated to Citadel.
- `pgvector` enabled in that Postgres database for the vector index.
- Cognee provider variables set on the web service through Railway variables.

Use Railway's private Postgres `DATABASE_URL` as the app database binding. If
your Cognee version expects split database variables instead of `DATABASE_URL`,
map Railway's `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`
values into the corresponding Cognee variables.

For the graph/mesh store, keep it durable:

- Prefer a Cognee graph backend that can use Railway Postgres if your installed
  Cognee version supports it.
- If you use Cognee's embedded Kuzu graph backend, attach a Railway persistent
  volume and point Cognee's Kuzu path at that mount.
- For later team use, you can move the graph store to a dedicated Neo4j or
  Memgraph service without changing Citadel's wrapper code.

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
