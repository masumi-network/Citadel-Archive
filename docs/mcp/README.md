# Citadel Archive — Integration Guide

This guide covers how to connect any MCP-capable coding agent to the Citadel
Organization Vault.

## Public vs private

| Public | Private |
|---|---|
| This repo ([Citadel-Archive](https://github.com/masumi-network/Citadel-Archive)) — code, docs, skills | Railway vault — live memory, DB, hashed tokens |
| Hosted skill URLs (`/skills/connect`, `/skills/vault`, `/skills/boundary`) | [Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror) — backup exports |
| Agent discovery manifest (`/.well-known/citadel.json`) | `ctdl_` tokens, `.env`, vault search results |
| MCP tool names and API routes | Obsidian sync contents and source documents |

Do not commit tokens or vault content to git. See [public-and-private.md](../public-and-private.md).

**Agent skill URLs (share these):**

| Skill | URL |
|---|---|
| Connect MCP | `https://citadel-archive-production.up.railway.app/skills/connect` |
| Use vault | `https://citadel-archive-production.up.railway.app/skills/vault` |
| Data boundary | `https://citadel-archive-production.up.railway.app/skills/boundary` |
| Discovery manifest | `https://citadel-archive-production.up.railway.app/.well-known/citadel.json` |

For Codex-compatible agents, share the install command instead:

```bash
npx skills add masumi-network/Citadel-Archive
```

The root `citadel-archive` skill points agents to the hosted connector, vault
usage, and boundary skills. See
[`../team-share-smoke-test.md`](../team-share-smoke-test.md) for the latest
verified rollout checklist.

The hosted `/skills` index publishes `size_bytes`, `sha256`, and SRI-style
`integrity` values for each skill. Each `/skills/*` response repeats the digest
in `X-Citadel-Skill-SHA256` and `X-Citadel-Skill-Integrity` headers.
The well-known discovery manifest also publishes the hosted MCP endpoint, token
requirements, tool policy metadata, approval recommendations, and public/private
boundary rules.

**Table of contents:**

- [Prerequisites](#prerequisites)
- [Claude Code](#claude-code)
- [Codex (OpenAI)](#codex-openai)
- [Cursor](#cursor)
- [Pi (Coding Agent Harness)](#pi-coding-agent-harness)
- [Any MCP Client (Generic)](#any-mcp-client-generic)
- [Direct HTTP API (No MCP)](#direct-http-api-no-mcp)
- [Token Management](#token-management)
- [Tool Reference](#tool-reference)
- [Troubleshooting](#troubleshooting)
- [Architecture Notes](#architecture-notes)

---

## Prerequisites

Before connecting, you need:

1. **Citadel URL.** Default: `https://citadel-archive-production.up.railway.app`
2. **Citadel access token.** A service-account token beginning with `ctdl_`.
   Create one through the Citadel UI (Access page) or ask your vault admin.
3. **An MCP-capable client.** Hosted MCP needs only the `/mcp/` URL plus the
   Authorization header. Clone this repo only for local development or legacy
   stdio-wrapper use.

### Getting a token

1. Open the Citadel UI at the URL above.
2. Go to the **Access** page.
3. Click **Create Token**.
4. Choose a role:
   - **Reader**: search, mesh, sources, events. Best for most agent work.
   - **Writer**: reader + ingest + feedback. Use when the agent should also add knowledge.
   - **Admin**: writer + learning-agent + improvement + token management. Use sparingly.
5. Copy the token. It is shown **once**. Citadel stores only its hash.

### Role summary

| Role | Search/Read | Ingest/Feedback | Learning Agent | Token Management |
|---|---|---|---|---|
| Reader | ✅ | — | — | — |
| Writer | ✅ | ✅ | — | — |
| Admin | ✅ | ✅ | ✅ | ✅ |

---

## Claude Code

### Step 1 — Create or update `.mcp.json`

In your project root, create or merge into `.mcp.json`:

```json
{
  "mcpServers": {
    "citadel": {
      "type": "http",
      "url": "https://citadel-archive-production.up.railway.app/mcp/",
      "headers": {
        "Authorization": "Bearer ${CITADEL_MCP_ACCESS_TOKEN}"
      }
    }
  }
}
```

Set the `CITADEL_MCP_ACCESS_TOKEN` environment variable in your shell (do not
hard-code it in a tracked project file):

```bash
export CITADEL_MCP_ACCESS_TOKEN="ctdl_..."
```

### Step 2 — Verify

Restart Claude Code. Run:

```
Use the citadel_discovery tool, then use the citadel_session tool.
```

If discovery returns the safe manifest and session returns your role and actor
info, the connection works.

### Step 3 — Try a search

```
Search Citadel for "architecture decisions"
```

### Template file

A ready-to-copy template is at `docs/mcp/claude-code-hosted.mcp.json`. Replace
`PASTE_CITADEL_TOKEN_HERE` with your token or use `${CITADEL_MCP_ACCESS_TOKEN}`
for environment variable substitution.

---

## Codex (OpenAI)

### Step 1 — Add to `~/.codex/config.toml`

Append this to `~/.codex/config.toml`:

```toml
[mcp_servers.citadel]
command = "npx"
args = [
  "-y",
  "mcp-remote",
  "https://citadel-archive-production.up.railway.app/mcp/",
  "--header",
  "Authorization: Bearer PASTE_ONCE_IN_LOCAL_CODEX_CONFIG",
]

[mcp_servers.citadel.tools.citadel_ingest]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_record_feedback]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_run_learning_agent]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_run_backup_mirror]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_improve]
approval_mode = "approve"
```

Write/admin tools are approval-gated so Codex asks before making vault changes.

### Step 2 — Verify

Restart Codex. Ask it to call `citadel_discovery`, then `citadel_session`.

### Template file

A ready-to-copy template is at `docs/mcp/codex-hosted.config.toml`.

---

## Cursor

### Step 1 — Add MCP server

Open Cursor Settings → Features → Model Context Protocol. Add a new MCP server:

- **Name**: `citadel`
- **Type**: hosted HTTP / streamable HTTP
- **URL**: `https://citadel-archive-production.up.railway.app/mcp/`
- **Headers**:
  - `Authorization` = `Bearer ctdl_...` (your token)

### Step 2 — Verify

Start a new chat in Cursor and ask it to use `citadel_discovery`, then
`citadel_session`.

---

## Pi (Coding Agent Harness)

### Using the Codex Plugin

The `plugins/citadel-archive-mcp/` directory contains a Codex-compatible plugin
with `.codex-plugin/plugin.json`, `.mcp.json`, and bundled skills. Point Pi at
this plugin directory.

### Using the Root SKILL.md

The root `SKILL.md` at the project root is a standalone skill file. Any agent
that discovers skills can load it to learn how to access Citadel.

### Connecting from Pi

If Pi supports hosted MCP servers, add the same URL/header config as Claude Code
above. If it only supports stdio, use the `mcp-remote` bridge shown in the Codex
section.

---

## Any MCP Client (Generic)

The supported production endpoint is hosted streamable HTTP:

```text
https://citadel-archive-production.up.railway.app/mcp/
Authorization: Bearer ctdl_<your-token>
```

If a client only supports stdio, bridge to the hosted endpoint:

```bash
npx -y mcp-remote \
  https://citadel-archive-production.up.railway.app/mcp/ \
  --header "Authorization: Bearer ctdl_..."
```

The server exposes:

- **13 tools**: `citadel_discovery`, `citadel_session`, `citadel_search`,
  `citadel_get_document`, `citadel_get_mesh`, `citadel_list_sources`,
  `citadel_ingest`, `citadel_record_feedback`, `citadel_run_learning_agent`,
  `citadel_backup_mirror_status`, `citadel_run_backup_mirror`,
  `citadel_audit_events`, `citadel_improve`
- **5 resources**: `citadel://discovery`, `citadel://session`,
  `citadel://sources`, `citadel://indexes`, `citadel://events/recent`
- **3 prompts**: `citadel_answer_from_kb`, `citadel_ingest_decision`,
  `citadel_summarize_source_changes`

The local stdio wrapper is still available for offline/dev use:

```bash
CITADEL_HTTP_BASE_URL=https://citadel-archive-production.up.railway.app
CITADEL_MCP_ACCESS_TOKEN=ctdl_...
CITADEL_MCP_DEFAULT_DATASET=masumi-network
CITADEL_MCP_MAX_INGEST_BYTES=200000
uv --directory "/absolute/path/to/Citadel-Archive" run python -m kb.mcp_server
```

---

## Direct HTTP API (No MCP)

If the client doesn't support MCP, call the HTTP API directly:

```bash
# Health check
curl https://citadel-archive-production.up.railway.app/healthz

# Search
curl -X POST https://citadel-archive-production.up.railway.app/search \
  -H "Authorization: Bearer ctdl_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "architecture decisions", "top_k": 5}'

# Ingest
curl -X POST https://citadel-archive-production.up.railway.app/ingest \
  -H "Authorization: Bearer ctdl_..." \
  -H "Content-Type: application/json" \
  -d '{"data": "Project decided on PostgreSQL + pgvector for vault storage.", "tags": ["architecture", "decision"]}'
```

All endpoints require `Authorization: Bearer <token>` except public health and
discovery metadata: `/healthz`, `/.well-known/citadel.json`, `/skills`, and
`/skills/*`. `/readyz` is authenticated because it checks private index state.

---

## Token Management

### Creating tokens

1. Through the Citadel UI: Access page → Create Token.
2. Through the API (admin only): `POST /api/access/tokens`
3. Through the CLI: not yet available (use the UI or API).

### Token format

All persistent tokens begin with `ctdl_` followed by a URL-safe random string.
Citadel stores only the SHA-256 hash. The raw token is shown once at creation.

### Revoking tokens

- Through the UI: Access page → Revoke.
- Through the API: `POST /api/access/tokens/{token_id}/revoke`
- Revoked tokens immediately lose all access.

### Token safety rules

- **Never commit** tokens to git. Use environment variables.
- **Never echo** tokens in chat or logs.
- **Never share** tokens between users or agents. One token per identity.
- **Rotate** if a token may have been exposed.
- Use the **minimum role** needed. Reader for search; writer only when ingesting.

---

## Tool Reference

### Reader Tools

| Tool | Description | Parameters |
|---|---|---|
| `citadel_discovery` | Safe agent discovery metadata: MCP endpoint, skill hashes, tool policy | — |
| `citadel_session` | Show authenticated role, actor, capabilities | — |
| `citadel_search` | Search the Organization Vault; each hit includes `_citadel` provenance, hash, and retrieval metadata | `query`, `dataset?`, `session_id?`, `top_k?` |
| `citadel_get_document` | Fetch a full document by a search hit `id` when `_citadel.retrieval.document_drilldown_available` is true | `document_id` |
| `citadel_get_mesh` | Current knowledge mesh snapshot | — |
| `citadel_list_sources` | Source-learning, GitHub sync, index status | — |

### Writer Tools

| Tool | Description | Parameters |
|---|---|---|
| `citadel_ingest` | Add durable context to the vault | `data`, `dataset?`, `tags?`, `session_id?` |
| `citadel_record_feedback` | Record QA feedback | `qa_id`, `score?`, `text?`, `session_id?`, `dataset?` |

### Admin Tools

| Tool | Description | Parameters |
|---|---|---|
| `citadel_run_learning_agent` | Run source-learning agent | `force?`, `dry_run?` |
| `citadel_backup_mirror_status` | Inspect backup mirror manifest status | — |
| `citadel_run_backup_mirror` | Run backup mirror manifest export | `dry_run?` |
| `citadel_audit_events` | Inspect bounded audit events | `view?`, `limit?` |
| `citadel_improve` | Run Cognee improvement cycle | `dataset?`, `session_ids?` |

### Resources

| URI | Description |
|---|---|
| `citadel://discovery` | Safe public discovery metadata |
| `citadel://session` | Current role and capabilities |
| `citadel://sources` | Source-learning status |
| `citadel://indexes` | Index status |
| `citadel://events/recent` | Recent mesh events |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CITADEL_HTTP_BASE_URL` | `http://localhost:8000` | Citadel backend URL |
| `CITADEL_MCP_ACCESS_TOKEN` | — | Bearer token for Citadel API |
| `CITADEL_MCP_DEFAULT_DATASET` | — | Dataset used by `citadel_search` when callers omit `dataset` |
| `CITADEL_MCP_MAX_INGEST_BYTES` | `200000` | Max ingest payload size |
| `CITADEL_MCP_ALLOW_INSECURE_HTTP` | `false` | Allow non-localhost HTTP |
| `CITADEL_MCP_TRANSPORT` | `stdio` | MCP transport (stdio or sse) |

---

## Troubleshooting

### Server won't start

```bash
# Ensure dependencies are installed
cd "/absolute/path/to/Citadel-Archive"
uv sync --dev

# Test the MCP server manually
CITADEL_HTTP_BASE_URL=https://citadel-archive-production.up.railway.app \
CITADEL_MCP_ACCESS_TOKEN=ctdl_... \
uv run python -m kb.mcp_server
```

### 401 Unauthorized

- Check that `CITADEL_MCP_ACCESS_TOKEN` is set and starts with `ctdl_`.
- Check that the token hasn't been revoked.
- Try calling `citadel_session` to see the error detail.

### 403 Forbidden

- The token's role doesn't have the required scope.
- Reader tokens cannot ingest. Writer tokens cannot run admin operations.
- Check the token's role in the Citadel UI Access page.

### Connection refused / Could not reach Citadel

- Check that `CITADEL_HTTP_BASE_URL` is correct and reachable.
- Check that the URL uses `https://` for hosted Citadel.
- Plain `http://` only works for `localhost` unless
  `CITADEL_MCP_ALLOW_INSECURE_HTTP=true` is set.

### Ingest payload too large

- `citadel_ingest` rejects payloads over `CITADEL_MCP_MAX_INGEST_BYTES` (default 200KB).
- Summarize or chunk large content before ingesting.

### Citadel returns non-JSON

- The backend may be restarting or misconfigured.
- Check `/healthz` and `/readyz` endpoints.
- Check Railway logs if using the hosted deployment.

---

## Architecture Notes

- The MCP server is a **thin stdio wrapper**. It does not run a second Citadel
  backend. It forwards all calls to the hosted HTTP API.
- The MCP server is safe to run multiple instances (e.g. one per agent session).
  It is stateless — all state lives in the hosted Citadel backend.
- Tool annotations follow the MCP spec: reader tools are marked `readOnlyHint=true`,
  writer tools are `destructiveHint=false` but not read-only, admin tools are
  `openWorldHint=true` because they trigger backend jobs.
- Secret redaction is applied to error messages and debug output. Tokens are
  never echoed in MCP responses.
- The MCP server validates that Citadel URLs use HTTPS for non-localhost hosts.
  Set `CITADEL_MCP_ALLOW_INSECURE_HTTP=true` only on trusted development networks.

---

## Connector Skill

For agents that support loading skills from a URL, use the hosted paths (no
GitHub auth; vault content is never in these files):

| Skill | URL |
|---|---|
| MCP setup | `https://citadel-archive-production.up.railway.app/skills/connect` |
| Vault usage | `https://citadel-archive-production.up.railway.app/skills/vault` |
| Public vs private | `https://citadel-archive-production.up.railway.app/skills/boundary` |
| Index | `https://citadel-archive-production.up.railway.app/skills` |
| Discovery manifest | `https://citadel-archive-production.up.railway.app/.well-known/citadel.json` |

Use the index when an agent needs verification metadata. Skill responses include
`X-Citadel-Skill-SHA256`, `X-Citadel-Skill-Integrity`, and an ETag derived from
the served markdown bytes.

Optional GitHub raw mirrors (same markdown as public Citadel-Archive):

```
https://raw.githubusercontent.com/masumi-network/Citadel-Archive/main/skills/citadel-mcp-connector/SKILL.md
https://raw.githubusercontent.com/masumi-network/Citadel-Archive/main/skills/citadel-data-boundary/SKILL.md
```
