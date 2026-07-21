```text
     ▛▜   ▛▜   ▛▜   ▛▜   ▛▜   ▛▜   ▛▜
    ▕══════════════════════════════════▏
    ▕   ____  _ _____ _   ___  ___ _    ▏
    ▕  / ___|| |_   _/ \ |   \| __| |   ▏
    ▕ | |__  | | | |/ _ \| |) | _|| |__ ▏
    ▕  \___| |_| |_/_/ \_\___/|___|____|▏
    ▕══════════════════════════════════▏
    ▕    ▟▀▙       ▟▀▙       ▟▀▙        ▏
    ▕▄▄▄▄█ █▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▏
```

# Citadel

> A self-hosted **Organization Vault** — shared, access-controlled memory for
> your team and its AI agents. Built on [Cognee](https://github.com/topoteretes/cognee).

![License](https://img.shields.io/badge/license-Apache--2.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Client](https://img.shields.io/badge/cli-zero--dependency-green)
![MCP](https://img.shields.io/badge/MCP-hosted-7c3aed)

Citadel turns approved sources — commits, sessions, docs, issues — into
structured, source-linked knowledge, and exposes it to people and agents through
a **CLI**, a **hosted MCP endpoint**, an **HTTP API**, and a **web UI**. Capture
is personal-by-default (your private **Node**); the shared **Central** vault
evolves only through governed promotion and org sync.

## Features

- **One-command onboarding** — `citadel onboard` wires the seat token, autosync
  git/session hooks, MCP server, and capture roots. Idempotent, self-contained.
- **Autonomous capture** — fail-silent git pre-push + Claude Code `SessionEnd`
  hooks snapshot work to your private Node. No per-session ceremony.
- **Headless by design** — every teammate command speaks `--json`, so Claude /
  Codex / Cursor and CI can drive it. Token from env, never argv.
- **Hosted MCP** — agents connect with a URL + token; `citadel_search` to read,
  `citadel_ingest` / `citadel_contribute` to write. Per-call audit.
- **Governed sharing** — seat writes stay on your Node; Central updates via org
  sync and the Promotion Agent. Secrets blocked on every write path.
- **Knowledge Mesh + Vault Activity** — two canvases in the web UI: the
  **Knowledge Mesh** (source-linked documents, concepts, and the seats they
  belong to) and **Vault Activity** (the live sync/search/ingest timeline).
  Every seat is visible as a presence hub, but content stays caller-scoped —
  you see Central plus your own Node, never another seat's Node content
  (ADR-0009). Click any node to read its document.
- **Zero-dependency client** — `pip install citadel-archive` is pure stdlib; the
  server stack is an opt-in extra.

## Quick start

### Teammate CLI

```bash
pipx install citadel-archive          # the `citadel` command (zero-dep client)
# upgrade: pipx install --force citadel-archive --pip-args=--no-cache-dir

citadel onboard                       # token + hooks + MCP + capture roots (idempotent)
source ~/.zshrc                       # load CITADEL_MCP_ACCESS_TOKEN into this shell
claude                                # Claude Code — token must be in the process env
citadel status                        # connection · identity · local setup  (--json for agents)
citadel doctor                        # diagnose setup; --fix repairs hooks + .mcp.json
citadel activity                      # what your Node is doing — captures, syncs, promotions
```

> **No Python yet?** The bootstrap installer checks for Python 3.10+, **asks
> before installing it** if it's missing, then sets up pipx + the CLI:
> ```bash
> curl -fsSL https://raw.githubusercontent.com/masumi-network/Citadel-Archive/main/install.sh | sh
> ```
> (`citadel` is a Python tool; pipx keeps its interpreter isolated so you don't
> manage Python yourself. Add `-s -- -y` to skip prompts, `--dry-run` to preview.)

```
  ▙ ▟ ▙ ▟ ▙ ▟ ▙ ▟
  ███████████████   CITADEL
  ██ ▟▀▙   ▟▀▙ ██   the organization vault
  ██ █ █   █ █ ██
  ███████████████
```

`citadel onboard` installs the bundled autosync hooks (`kb.hooks.*` — no vendored
skill), writes the seat token to your shell rc (masked), writes hosted HTTP MCP
to the project `.mcp.json`, and offers Approved Capture Roots. When setup
finishes it prints Claude Code MCP next steps (reload shell before `claude`;
cloud sessions need the token in cloud env settings — not only in repo config).
Get a `ctdl_…` seat token from a vault admin (the Access page or
`POST /api/access/tokens`). One token per person or agent; rotate anything that
lands in chat or logs.

> **Admins: mint a seat-bound token, not a bare service account.** On the Access
> page pick a seat under *Assign to seat* (or run `citadel seat token <slug>`) so
> the token inherits a `seat:<slug>` default dataset. A seat-less
> (service-account) token has **no default dataset** — the teammate authenticates
> fine but every search fails with `DatasetNotFoundError` and writes route to the
> shared org dataset. A correct token shows `seat_slug` + `default_dataset:
> seat:<slug>` in `citadel status --json`.

### Self-host the server

```bash
uv sync --dev                         # full server stack (cognee, fastapi, …)
cp .env.example .env                  # set providers, access keys, database
uv run uvicorn kb.server:app --reload --port 8000
```

Open `http://localhost:8000/` for the UI. See
[`docs/operations.md`](docs/operations.md) for deployment, environment, and
integrations.

## How it works

| Concept | What it is |
|---|---|
| **Node** (`seat:{slug}`) | Your private working memory. Default target for all capture. |
| **Central** (`masumi-network`) | The shared org vault. Read-only for seats; evolves via sync + promotion. |
| **Capture** | Approved Capture Roots auto-sync to your Node; everything else needs approval. |
| **Promotion** | A Promotion Agent moves qualifying Node knowledge into Central (tag-governed). |

Four surfaces sit on the same FastAPI process and the same `ctdl_` tokens: the
**CLI**, the **hosted MCP** endpoint (`/mcp/`), the **HTTP API**, and the **web
UI**. The domain language is defined in [`CONTEXT.md`](CONTEXT.md); architecture
decisions live in [`docs/adr/`](docs/adr/).

## Usage

### CLI

```bash
citadel onboard                       # one-command setup
citadel doctor [--fix]                # diagnose (and repair) your local setup
citadel status [--json]               # health + identity + local setup + knowledge mesh
citadel activity [--watch] [--global] # your Node's vault activity (--watch live-tails); --global = team presence board (counts only); --local = offline capture receipts
citadel capture [--dry-run] [--json]  # push summaries of Approved Capture Roots
citadel search "what did we decide about the vault?"   # HTTP-backed via your seat (--json)
citadel ingest "A durable note" --tag decision         # → your seat Node, cognified inline
citadel mcp add claude                # ~/.claude.json (user scope) + project .mcp.json
citadel mcp add cursor                # wire another coding tool to the hosted MCP
citadel seat create "Jane Dev" jane   # admin: mint a seat + its seat-scoped writer token
```

### MCP (hosted)

Agents connect with a URL and a token — no clone, no local Python. `citadel
onboard` and `citadel mcp add claude` write this to the project `.mcp.json`
(the legacy stdio/`kb.mcp_server` plugin path is deprecated — run `citadel
doctor --fix` if you still have a `command`-based entry):

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

**Claude Code:** `${CITADEL_MCP_ACCESS_TOKEN}` is expanded only when the variable
is in the **process environment** that launched Claude — local CLI: `source
~/.zshrc` (or open a new terminal) before `claude`; **cloud:** add
`CITADEL_MCP_ACCESS_TOKEN` in Claude cloud environment settings. Verify with
`claude mcp list` (no missing-env warning) and `/mcp` (citadel tools, not "zero
tools"). `citadel doctor` flags token-in-rc-but-not-env and legacy stdio MCP.

Per-client setup: [`docs/mcp/README.md`](docs/mcp/README.md).

### HTTP API

```bash
export CITADEL_BASE_URL=https://citadel-archive-production.up.railway.app

# Read — flat, agent-friendly alias over search
curl -fsS -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" \
  "$CITADEL_BASE_URL/api/knowledge?q=payment+flow&limit=5"

# Contribute (writer) — routed through the Learning Process with conflict detection
curl -fsS -X POST "$CITADEL_BASE_URL/api/contribute" \
  -H "Authorization: Bearer $CITADEL_MCP_ACCESS_TOKEN" -H "Content-Type: application/json" \
  --data '{"title":"Decision: deepseek-v4-flash","content":"Standardized on it via OpenRouter.","tags":["decision"]}'
```

Full endpoint reference: [`docs/operations.md`](docs/operations.md#http-api-reference).

### Python

```python
import asyncio
from kb import Citadel

async def main() -> None:
    kb = Citadel.from_env()
    await kb.ingest("Citadel keeps my Organization Vault organized.", tags=["personal"])
    print(await kb.search("What does Citadel do?"))

asyncio.run(main())
```

## Skills & agent discovery

The agent skills live in `skills/` and are installable straight from this repo:

```bash
npx skills add masumi-network/Citadel-Archive
```

The hosted [`/skills`](https://citadel-archive-production.up.railway.app/skills)
index and the
[discovery manifest](https://citadel-archive-production.up.railway.app/.well-known/citadel.json)
publish each skill's `sha256` / SRI `integrity` and the MCP endpoint, token
requirements, and public/private boundary — without exposing vault content.

## Documentation

| Topic | Doc |
|---|---|
| Operations & self-hosting | [`docs/operations.md`](docs/operations.md) |
| Teammate rollout (5 min) | [`docs/onboarding/teammate-rollout.md`](docs/onboarding/teammate-rollout.md) |
| MCP integration (Claude, Cursor, …) | [`docs/mcp/README.md`](docs/mcp/README.md) |
| Autonomous sync | [`docs/onboarding/citadel-autosync.md`](docs/onboarding/citadel-autosync.md) |
| Domain glossary | [`CONTEXT.md`](CONTEXT.md) |
| Architecture decisions | [`docs/adr/`](docs/adr/) |
| Brand | [`brand.md`](brand.md) |
| Publishing the CLI | [`PUBLISHING.md`](PUBLISHING.md) |

| Repo | Visibility | Role |
|---|---|---|
| [Citadel Archive](https://github.com/masumi-network/Citadel-Archive) (this) | **Public** | app, hosted MCP, docs, agent skills (no vault content) |
| Vault Backup Mirror | Private | manifest-only backup of vault evidence |
| [Railway deployment](https://citadel-archive-production.up.railway.app) | Private | live Organization Vault |

## Contributing

Issues and pull requests welcome. Tests run with `uv run pytest`; lint with
`uv run ruff check .`. Keep the lightweight client free of server dependencies —
the base package is stdlib-only (a test guards the import boundary).

## License & attribution

Apache-2.0. Citadel builds on [Cognee](https://github.com/topoteretes/cognee)
(developed by Topoteretes UG, Apache-2.0) and imports it as a dependency rather
than vendoring it, so upstream can be upgraded independently.
