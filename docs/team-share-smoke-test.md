# Citadel Team Share Smoke Test

Last updated: 2026-06-02.

Use this checklist before sharing Citadel setup with teammates or agents.

## What To Share

For Codex-compatible agents:

```bash
npx skills add masumi-network/Citadel-Archive
```

For agents that cannot install skills:

```text
https://citadel-archive-production.up.railway.app/skills
```

Give each teammate or agent identity its own `ctdl_...` token. Use reader tokens
for search-only work and writer tokens only when the agent should ingest durable
context. Rotate any token that was pasted into chat, logs, issues, PRs, or public
files.

## Verified State

Verified on 2026-06-02, production commit
`7a4a1d9b0b3cd921f3863c5f81667973f231c7fe`.

- `npx skills add masumi-network/Citadel-Archive` installs the root
  `citadel-archive` skill.
- Public endpoints return `200` for `/healthz`, `/skills`, and
  `/skills/connect`.
- Hosted MCP initializes, lists 9 tools, and exposes `citadel_session`,
  `citadel_search`, and `citadel_ingest`.
- A writer token successfully reads and ingests through direct HTTP.
- A writer token successfully reads and ingests through hosted MCP.
- Railway `Citadel-Archive` production service is `SUCCESS` and `RUNNING` on the
  same commit.

## Public Endpoint Smoke Test

```bash
export CITADEL_BASE_URL=https://citadel-archive-production.up.railway.app

curl -fsS "$CITADEL_BASE_URL/healthz"
curl -fsS "$CITADEL_BASE_URL/skills" | python3 -m json.tool
curl -fsS "$CITADEL_BASE_URL/skills/connect" | sed -n '1,80p'
```

## Token Smoke Test

Keep token and vault output out of public repos, issues, PRs, and shared chats.

```bash
export CITADEL_BASE_URL=https://citadel-archive-production.up.railway.app
export CITADEL_MCP_ACCESS_TOKEN=ctdl_... # paste locally; never commit

curl -fsS -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  "$CITADEL_BASE_URL/api/session" | python3 -m json.tool

curl -fsS -X POST "$CITADEL_BASE_URL/search" \
  -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"query":"repositories commits events","dataset":"masumi-network","top_k":3}' \
  | python3 -m json.tool
```

## Hosted MCP Checks

A plain `curl` GET to `/mcp/` is not a valid MCP client request. The endpoint
expects streamable HTTP with `Accept: text/event-stream` or a real MCP client.

Expected MCP results with a writer token:

- `initialize`: `200`
- `tools/list`: includes 9 Citadel tools
- `citadel_session`: role `writer`, `read=true`, `write=true`
- `citadel_search`: `200`
- `citadel_ingest`: `200`

## Safety Notes

- One token per teammate or agent identity.
- Minimum role by default: reader for search, writer only for ingest.
- Never paste raw tokens or vault search output into public places.
- Rotate exposed tokens immediately.
