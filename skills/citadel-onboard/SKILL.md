---
name: citadel-onboard
description: One-command teammate onboarding for Citadel. Use when a teammate wants to set up Citadel in a repo — connect their seat token, install the autonomous git-push + SessionEnd capture hooks, add the Citadel MCP server, and (optionally) declare Approved Capture Roots. Triggers include "onboard me to citadel", "set up citadel", "citadel onboard", "connect citadel", "install citadel here", and https://citadel-archive-production.up.railway.app/skills/onboard.
---

# Citadel Onboard

`citadel onboard` collapses the whole teammate rollout into **one idempotent
command**. Run it from a repo that has `skills/citadel-proactive-ingest/`
vendored (the hooks live there).

```bash
citadel onboard
```

It walks these steps, merging into existing config (never clobbering) and safe
to re-run:

| Step | What it does | Required? |
|---|---|---|
| **Token** | Prompts for your `ctdl_…` seat token, writes `export CITADEL_MCP_ACCESS_TOKEN=…` to your shell rc (once) | yes |
| **Git pre-push hook** | Installs `.git/hooks/pre-push` → commit snapshots to your **Node** | yes |
| **SessionEnd hook** | Merges the Claude Code `SessionEnd` hook into `.claude/settings.json` | yes |
| **MCP server** | Adds the `citadel` HTTP MCP server to `.mcp.json` (in-session `citadel_search` + `citadel_ingest`) | optional, default on (`--no-mcp` to skip) |
| **Capture roots** | Optional `citadel setup` wizard → `~/.citadel/capture.json` | optional, prompted |

## Where to get the token

A Citadel admin mints a **seat-writer** token from the connect wizard
(`https://citadel-archive-production.up.railway.app/skills/connect` → Create
seat → role: writer). Paste it when `citadel onboard` asks. It is a secret —
share it over a private channel only.

## Security

- The seat token is written to **exactly one place** (your shell rc). The
  `.mcp.json` block references it as `${CITADEL_MCP_ACCESS_TOKEN}` — the secret
  is **never** stored in project config or echoed to the terminal (the summary
  masks it).
- Every dev-side hook is **fail-silent** — if Citadel is down or the token is
  unset, your `git push` and session close still succeed.

## MCP — needed or not?

- **Autonomous background sync** (git push, session close) is plain HTTPS +
  token — it does **not** need MCP.
- **In-session vault search and proactive ingest** (`citadel_search`,
  `citadel_ingest`) are MCP tools. Enable MCP (default) if you want your IDE
  agent to ground answers in the vault; skip with `--no-mcp` for capture-only.
- Manual ingest/search always works via the CLI (`citadel ingest`,
  `citadel search`, `citadel capture`).

## Non-interactive / scripted

```bash
citadel onboard --non-interactive --token "ctdl_…" \
  --repo /path/to/repo --shell-rc ~/.zshrc --no-capture
```

Flags: `--token`, `--repo`, `--shell-rc`, `--no-mcp`, `--no-capture`,
`--non-interactive`. Exits non-zero if no token is available.

## Check status (the dashboard replacement)

Teammates have no web dashboard — the CLI is the window into Citadel.

```bash
citadel status      # one-shot: connection, identity (seat/role), local setup, recent activity
citadel tui         # live terminal dashboard (needs the [tui] extra)
```

`citadel status` checks the Node (`/healthz`), your token (`/api/session` →
seat + role + capabilities), a search smoke, and local setup (token in env,
`.mcp.json`, git + SessionEnd hooks, capture roots). It exits non-zero when not
connected, so it doubles as a doctor.

### For AI agents (Claude Code / Codex / Cursor)

Agents should use the structured form to verify Citadel before relying on it:

```bash
citadel status --json
```

It returns `{healthy, identity{seat_slug,role,…}, checks[…], recent[…]}`. Use it
to confirm connectivity, discover the current seat, or diagnose why a capture
isn't landing — then fall back to `citadel_search` / `citadel_ingest` MCP tools
for in-session work. (The MCP `citadel_session` tool is the in-session whoami;
`citadel status` additionally sees **local** hook/config state the server can't.)

## Verify

Restart the shell (or `source ~/.zshrc`), then run `citadel status` (expect all
`●`), or in your agent ask: *"use citadel_search to find what we decided about
the vault."* A grounded answer means the token + MCP work. See
[`docs/onboarding/teammate-rollout.md`](../../docs/onboarding/teammate-rollout.md)
for the manual step-by-step and what auto-syncs.
