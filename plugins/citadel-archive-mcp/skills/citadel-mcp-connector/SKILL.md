---
name: citadel-mcp-connector
description: Connects Claude Code, Codex, Cursor, Pi, or any MCP-capable coding agent to Citadel Archive. Use when the user shares this skill URL, pastes a Citadel token, or says connect/set up/configure Citadel MCP, citadel plugin, organization vault MCP, or "add citadel to my agent". The agent should run the full setup workflow—detect client, ask only for missing secrets, write local MCP config, verify health, then search the vault. Triggers include "connect citadel", "set up citadel mcp", "citadel mcp connector", "citadel archive mcp", and https://citadel-archive-production.up.railway.app/skills/connect.
---

# Citadel MCP Connector

## Public vs private (read first)

| Public | Private |
|---|---|
| [Citadel-Archive](https://github.com/masumi-network/Citadel-Archive) — code, this skill | Railway vault — team memory (query with `ctdl_` token only) |
| `/skills/*` markdown on the hosted URL | [Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror) — backup git |

Never commit tokens. Never copy vault search results into the public repo.  
Boundary detail: `https://citadel-archive-production.up.railway.app/skills/boundary`

## Skill URLs

**Connect (this skill):**

```
https://citadel-archive-production.up.railway.app/skills/connect
```

Aliases: `/skills/mcp`, `/skills/mcp-connector`

**After MCP works:**

```
https://citadel-archive-production.up.railway.app/skills/vault
```

## Agent workflow (run in order)

When this skill is loaded—especially from the URL above—**do not stop at explaining**. Execute the steps below unless the user only asked for documentation.

### 1. Detect environment

Infer the **client** from context (ask only if unclear):

| Signal | Client |
|---|---|
| `.mcp.json` in project, Claude Code, `claude mcp` | Claude Code |
| `~/.codex/config.toml`, Codex CLI, OpenAI Codex | Codex |
| Cursor Settings → MCP, `.cursor/mcp.json` | Cursor |
| Pi + `.codex-plugin` | Pi / Codex plugin |
| Other MCP host | Generic stdio |

Set these defaults unless the user overrides them:

| Variable | Default |
|---|---|
| Citadel URL | `https://citadel-archive-production.up.railway.app` |
| GitHub repo | `https://github.com/masumi-network/Citadel-Archive.git` |
| Max ingest bytes | `200000` |
| Token env name | `CITADEL_MCP_ACCESS_TOKEN` |
| Search dataset | `masumi-network` |

### 2. Ask the user (minimal)

Ask **only** for values you cannot infer or read from config:

1. **Citadel access token** (required if not already in env/config).  
   - Must start with `ctdl_`.  
   - Tell the user: create one in Citadel UI → **Access** → **Create Token** (reader is enough for search).  
   - Ask them to paste it once. **Never echo it back** in chat or commits.

2. **Local clone path** (only if [Citadel-Archive](https://github.com/masumi-network/Citadel-Archive) is not present).  
   - If missing: `git clone` the public repo, then `uv sync --dev`.  
   - Use `.` in `.mcp.json` when the config lives at the repo root; otherwise set the absolute clone path.

3. **Citadel URL** (only if not using the hosted default).

4. **Role intent** (optional): reader (default), writer (ingest), or admin.

Do **not** ask for seed phrases, wallet keys, cloud API keys, or unrelated secrets.

### 3. Prerequisites (fix before configuring)

Run or guide the user to run:

```bash
# uv required
command -v uv || echo "Install uv: https://docs.astral.sh/uv/"

# clone if needed
git clone https://github.com/masumi-network/Citadel-Archive.git
cd Citadel-Archive   # or the path the user chose
uv sync --dev
```

Set `CITADEL_REPO_PATH` to the directory containing `pyproject.toml` and `kb/mcp_server.py`
(use `.` when configuring from the repo root).

### 4. Store the token safely (never in git)

Pick **one** storage method per client. Prefer env vars over literals in tracked files.

| Client | Where to put the token |
|---|---|
| Claude Code | Shell: `export CITADEL_MCP_ACCESS_TOKEN='ctdl_...'` and use `${CITADEL_MCP_ACCESS_TOKEN}` in `.mcp.json` |
| Codex | `~/.codex/config.toml` `[mcp_servers.citadel.env]` (local file, not the repo) |
| Cursor | MCP server env in Cursor Settings (UI), or user-level secret store—not committed project files |
| Generic | Process environment for the MCP child process |

**Never** commit the raw token to `.mcp.json`, `config.toml`, or any file under git.

### 5. Write MCP config

Set `--directory` to `.` (repo root) or the user's clone path. Merge if a `citadel` server entry already exists.

#### Claude Code — project `.mcp.json`

Copy from `.mcp.json.example` at the repo root, or use:

```json
{
  "mcpServers": {
    "citadel": {
      "command": "uv",
      "args": [
        "--directory",
        ".",
        "run",
        "python",
        "-m",
        "kb.mcp_server"
      ],
      "env": {
        "CITADEL_HTTP_BASE_URL": "https://citadel-archive-production.up.railway.app",
        "CITADEL_MCP_ACCESS_TOKEN": "${CITADEL_MCP_ACCESS_TOKEN}",
        "CITADEL_MCP_DEFAULT_DATASET": "masumi-network",
        "CITADEL_MCP_MAX_INGEST_BYTES": "200000"
      }
    }
  }
}
```

Ensure the user's shell exports `CITADEL_MCP_ACCESS_TOKEN` before starting Claude Code.

#### Codex — `~/.codex/config.toml`

Append (token goes in the local Codex config only):

```toml
[mcp_servers.citadel]
command = "uv"
args = [
  "--directory",
  "/absolute/path/to/Citadel-Archive",
  "run",
  "python",
  "-m",
  "kb.mcp_server",
]

[mcp_servers.citadel.env]
CITADEL_HTTP_BASE_URL = "https://citadel-archive-production.up.railway.app"
CITADEL_MCP_ACCESS_TOKEN = "PASTE_ONCE_IN_LOCAL_CONFIG"
CITADEL_MCP_DEFAULT_DATASET = "masumi-network"
CITADEL_MCP_MAX_INGEST_BYTES = "200000"

[mcp_servers.citadel.tools.citadel_ingest]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_record_feedback]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_run_learning_agent]
approval_mode = "approve"

[mcp_servers.citadel.tools.citadel_improve]
approval_mode = "approve"
```

#### Cursor — MCP server (Settings → MCP)

| Field | Value |
|---|---|
| Name | `citadel` |
| Command | `uv` |
| Args | `--directory`, `.` or clone path, `run`, `python`, `-m`, `kb.mcp_server` |
| Env | `CITADEL_HTTP_BASE_URL`, `CITADEL_MCP_ACCESS_TOKEN`, `CITADEL_MCP_DEFAULT_DATASET`, `CITADEL_MCP_MAX_INGEST_BYTES` |

Optional project file: `.cursor/mcp.json` with the same shape as Claude's `.mcp.json` if the team uses project-scoped MCP.

#### Codex plugin (Pi / plugin install)

Point the host at `plugins/citadel-archive-mcp/` in the cloned repo. Update `.mcp.json` inside that plugin directory to use `CITADEL_REPO_PATH`, or install via marketplace if available.

#### Generic stdio

```bash
export CITADEL_HTTP_BASE_URL=https://citadel-archive-production.up.railway.app
export CITADEL_MCP_ACCESS_TOKEN=ctdl_...
export CITADEL_MCP_DEFAULT_DATASET=masumi-network
export CITADEL_MCP_MAX_INGEST_BYTES=200000
uv --directory "/absolute/path/to/Citadel-Archive" run python -m kb.mcp_server
```

### 6. Verify (before claiming success)

**A. HTTP (works before MCP restart)**

```bash
curl -fsS "https://citadel-archive-production.up.railway.app/healthz"
curl -fsS -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  "https://citadel-archive-production.up.railway.app/api/session"
```

Expect HTTP 200 and JSON with `role` / `actor`. On 401, token is missing, wrong, or revoked. Do not print the token in errors.

**B. MCP (after user restarts the client)**

Ask the user to **restart** Claude Code, Codex, or Cursor so the new MCP server loads.

Then call tools in order:

1. `citadel_session` — confirm role and capabilities  
2. `citadel_search` with a small test query (e.g. `architecture` or a project name the user gave)  
3. Optionally `citadel_list_sources` or `citadel_get_mesh` for richer smoke test

If MCP tools are not visible yet, fall back to HTTP `POST /search` with the same bearer token until restart completes.

### 7. Start fetching (normal operation)

Once verified, treat Citadel as live organization memory:

- **Before** answering project/architecture/source questions → `citadel_search`  
- **When** the user asks to remember something durable → `citadel_ingest` (writer token + approval if required)  
- Follow the **citadel-vault** skill for read/write/admin rules and safety

Default prompt for the user after setup:

> Citadel is connected. Search the vault for context on [their topic], then answer using what you find.

## Safety rules

- Do not commit tokens to git or paste them into PRs/issues.  
- Do not echo tokens in chat, logs, or tool output.  
- Prefer **reader** tokens; use writer/admin only when the user needs ingest or ops.  
- Use HTTPS for hosted URLs; plain HTTP only for `localhost` unless `CITADEL_MCP_ALLOW_INSECURE_HTTP=true`.  
- Approval-gate `citadel_ingest`, `citadel_record_feedback`, `citadel_run_learning_agent`, and `citadel_improve` when the client supports per-tool approval.

## Troubleshooting

| Symptom | Fix |
|---|---|
| MCP server fails to start | `uv sync --dev` in the Citadel-Archive clone; confirm `uv` on PATH |
| 401 on session/search | Set `CITADEL_MCP_ACCESS_TOKEN`; check token not revoked |
| 403 on ingest | Token is reader-only; create writer token or use reader tools only |
| Connection refused | Wrong `CITADEL_HTTP_BASE_URL`; check `/healthz` |
| Tools missing after config | User must restart the MCP host |
| Ingest too large | Chunk/summarize; respect `CITADEL_MCP_MAX_INGEST_BYTES` |

## Reference

- Full integration guide: `docs/mcp/README.md` in the repo  
- MCP tools: `citadel_session`, `citadel_search`, `citadel_get_mesh`, `citadel_list_sources`, `citadel_ingest`, `citadel_record_feedback`, `citadel_run_learning_agent`, `citadel_improve`  
- Hosted UI (create tokens): `https://citadel-archive-production.up.railway.app` → Access
