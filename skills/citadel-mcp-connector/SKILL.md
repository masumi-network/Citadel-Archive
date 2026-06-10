---
name: citadel-mcp-connector
description: Connects Claude Code, Cursor, Codex, or any MCP-capable agent to the Citadel Archive Organization Vault over its hosted MCP endpoint — no clone, no Python, no local install. Use when the user shares this skill URL, pastes a Citadel token, or says connect/set up/configure Citadel MCP, citadel plugin, organization vault MCP, or "add citadel to my agent". Run the full workflow: detect client, collect only the token, write the remote MCP config (URL + Authorization header), verify, then search the vault. Triggers include "connect citadel", "set up citadel mcp", "citadel mcp connector", "citadel archive mcp", and https://citadel-archive-production.up.railway.app/skills/connect.
---

# Citadel MCP Connector

Citadel is served as a **hosted MCP endpoint**. Agents connect with a URL and a
token — there is **no repository to clone**, no `uv`, and no local Python.

```
MCP endpoint:  https://citadel-archive-production.up.railway.app/mcp/
Auth:          Authorization: Bearer ctdl_<your-token>
```

## Public vs private (read first)

| Public | Private |
|---|---|
| The hosted REST + MCP API surface and these `/skills/*` docs | The vault contents — only readable with a `ctdl_` token |
| [Citadel-Archive](https://github.com/masumi-network/Citadel-Archive) — app code, skills | Team/organization memory behind the token |

Never commit tokens. Never copy vault search results into a public repo or issue.
Boundary detail: `https://citadel-archive-production.up.railway.app/skills/boundary`

## Skill URLs

- Connect (this skill): `https://citadel-archive-production.up.railway.app/skills/connect`
- After MCP works: `https://citadel-archive-production.up.railway.app/skills/vault`
- Full repo skill install: `npx skills add masumi-network/Citadel-Archive`

If the user shares the `npx skills add` command, install the root
`citadel-archive` skill first, then continue this connector workflow.

## Agent workflow (run in order)

When this skill is loaded — especially from the URL above — **do not stop at
explaining**. Execute the steps below unless the user only asked for docs.

### 1. Collect the one required secret

Ask for the **Citadel access token** if it is not already in the environment or
client config:

- Must start with `ctdl_`.
- Create one in the Citadel UI → **Access** → **Create Token** (reader is enough
  for search; writer for ingest; admin for ops).
- The user pastes it once. **Never echo it back** in chat, logs, or commits.

That is the only secret. Do **not** ask for clone paths, `uv`, seed phrases,
wallet keys, or unrelated API keys.

Defaults (override only if the user does):

| Setting | Default |
|---|---|
| MCP endpoint | `https://citadel-archive-production.up.railway.app/mcp/` |
| Token env name | `CITADEL_MCP_ACCESS_TOKEN` |
| Search dataset | `masumi-network` (the server defaults this too) |

### 2. Write the remote MCP config

Pick the user's client. Each config points at the hosted `/mcp/` URL and sends the
token in the `Authorization` header. Store the token in an env var or the client's
secret store — **never** as a literal in a tracked file.

#### Claude Code — project `.mcp.json`

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

Or one command (token expanded from your shell):

```bash
claude mcp add --transport http citadel \
  https://citadel-archive-production.up.railway.app/mcp/ \
  --header "Authorization: Bearer ${CITADEL_MCP_ACCESS_TOKEN}"
```

Export the token first: `export CITADEL_MCP_ACCESS_TOKEN='ctdl_...'`.

#### Cursor — `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "citadel": {
      "url": "https://citadel-archive-production.up.railway.app/mcp/",
      "headers": { "Authorization": "Bearer ctdl_..." }
    }
  }
}
```

#### Codex / stdio-only hosts — `mcp-remote` bridge

For a client that only speaks stdio, bridge to the hosted endpoint with
`mcp-remote` (no clone, just `npx`):

```toml
# ~/.codex/config.toml
[mcp_servers.citadel]
command = "npx"
args = [
  "-y", "mcp-remote",
  "https://citadel-archive-production.up.railway.app/mcp/",
  "--header", "Authorization: Bearer ctdl_...",
]
```

#### Any other MCP host

Point it at the streamable-HTTP URL `…/mcp/` with header
`Authorization: Bearer ctdl_…`. If it cannot send headers, use the `mcp-remote`
bridge above.

### 3. Verify (before claiming success)

**A. HTTP reachability (works immediately):**

```bash
curl -fsS "https://citadel-archive-production.up.railway.app/healthz"
curl -fsS -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  "https://citadel-archive-production.up.railway.app/api/session"
```

Expect HTTP 200 and JSON with `role` / `actor`. On 401 the token is missing,
wrong, or revoked. Never print the token in errors.

**B. MCP (after the user restarts the client):**

Ask the user to **restart** the client so the new server loads, then call tools:

1. `citadel_discovery` — confirm the MCP endpoint, skill hashes, tool policy,
   and public/private boundary metadata.
2. `citadel_session` — confirm role and capabilities.
3. `citadel_search` with a small query (e.g. `architecture` or a project name).
4. From a search hit, pass its `id` to `citadel_get_document` to drill down.

Production smoke status, last verified 2026-06-02 at commit `7a4a1d9`:

- hosted MCP initializes and lists Citadel tools;
- `citadel_discovery` returns the safe public manifest;
- `citadel_session` returns the caller role and capabilities;
- `citadel_search` returns company search results;
- `citadel_ingest` succeeds with a writer token.

### 4. Start fetching (normal operation)

- **Before** answering project/architecture/source questions → `citadel_search`.
- Cite from each hit's `_citadel.provenance` and `_citadel.content_sha256`.
- To open a hit in full → `citadel_get_document` with the result `id`, but only
  when `_citadel.retrieval.document_drilldown_available` is true.
- **When** the user asks to remember something durable → `citadel_contribute`
  for titled notes or `citadel_ingest` for raw context (writer token + approval).
- Follow the **citadel-vault** skill for read/write/admin rules.

## Tools

| Tool | Role | What it does |
|---|---|---|
| `citadel_discovery` | reader | Safe manifest with MCP endpoint, skill hashes, and tool policy |
| `citadel_session` | reader | Authenticated role, actor, scopes |
| `citadel_search` | reader | Search the vault (dataset defaults server-side) |
| `citadel_get_document` | reader | Fetch a full document by a search hit `id` |
| `citadel_get_mesh` | reader | Knowledge-mesh snapshot |
| `citadel_list_sources` | reader | GitHub sync, learning-agent, index status |
| `citadel_ingest` | writer | Add durable context |
| `citadel_contribute` | writer | Add a titled Vault Contribution (enrichment + conflict detection) |
| `citadel_record_feedback` | writer | Record feedback on a QA result |
| `citadel_run_learning_agent` | admin | Run source learning |
| `citadel_backup_mirror_status` | admin | Inspect backup mirror manifest status |
| `citadel_run_backup_mirror` | admin | Run backup mirror manifest export |
| `citadel_audit_events` | admin | Inspect bounded audit events |
| `citadel_improve` | admin | Run Cognee improvement |

## Safety rules

- Do not commit tokens to git or paste them into PRs/issues.
- Do not echo tokens in chat, logs, or tool output.
- Prefer **reader** tokens; use writer/admin only for explicit write/ops actions.
- Approval-gate `citadel_ingest`, `citadel_contribute`, `citadel_record_feedback`,
  `citadel_run_learning_agent`, `citadel_run_backup_mirror`, and
  `citadel_improve` when the client supports per-tool approval.

## Troubleshooting

| Symptom | Fix |
|---|---|
| 401 on session/search | Set the token; check it is not revoked |
| 403 on ingest | Token is reader-only; create a writer token |
| Tools missing after config | Restart the MCP host |
| Client can't send headers | Use the `mcp-remote` stdio bridge above |
| Endpoint unreachable | Check `…/healthz`; confirm the `…/mcp/` URL |

## Reference

- Hosted MCP URL: `https://citadel-archive-production.up.railway.app/mcp/`
- Hosted UI (create tokens): `https://citadel-archive-production.up.railway.app`
- Vault usage skill: `https://citadel-archive-production.up.railway.app/skills/vault`
