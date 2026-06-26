# Autonomous sync — Cursor and Codex

Citadel autosync is **IDE-agnostic** for git workflows. Background capture is
**fail-silent** — no extra dev steps after one-time setup.

## Universal: git push hook (required)

Install once per clone:

```bash
skills/citadel-proactive-ingest/scripts/install_autosync.sh
```

Or manually:

```bash
cp skills/citadel-proactive-ingest/templates/git-pre-push.sh .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

Requires `CITADEL_MCP_ACCESS_TOKEN` in your environment (same token as MCP).
Every push snapshots commit metadata to your private **Node** — always exits 0,
never blocks push.

## Claude Code (optional extra)

Merge `templates/claude-settings.json` into `.claude/settings.json` for
SessionEnd session distill on top of git push snapshots.

## Cursor

No Cursor-specific hook is required. The git pre-push hook is the universal
baseline. Optionally add a project rule reminding agents to call
`citadel_ingest` for durable decisions mid-session (see
`skills/citadel-proactive-ingest/SKILL.md`).

## Codex / other agents

Same as Cursor: git push hook + MCP token. Agents read your **Node** and
**Central** via `citadel_search` and `citadel_session`.

## Linear tasks (server cron + MCP)

Railway cron (`CITADEL_RUN_MODE=linear-sync`) syncs the Linear workspace to
**Central** and **Seat-Scoped Mirrors** assignee issues into each dev's **Node**.

Ask your agent:

- *"What do I need to do?"* → `citadel_linear_my_issues` (your **Node** mirror)
- *"Search Linear for …"* → `citadel_linear_search` (**Central**)

Agents should **not** trigger `POST /api/linear-sync/run` unless the user
explicitly asks for an immediate refresh — cron is the default.

## Agent sync policy (for project rules)

| Situation | Action |
|---|---|
| Project/architecture question | `citadel_search` |
| Task list / assigned work | `citadel_linear_my_issues` |
| Durable fact mid-session | `citadel_ingest` (personal-by-default) |
| Git push or session close | **Nothing** — hooks handle it |
| Stale org sources | **Do not** trigger admin sync unless user asks |

## Server-side cron (operators)

Devs do not configure Railway cron. Operators set `CITADEL_RUN_MODE` on cron
services:

- `learning-agent` — daily GitHub org digest
- `linear-sync` — Linear workspace + **Seat-Scoped Mirrors**
- `pipeline` — full scheduled run

See `.env.example` and `README.md` for env vars and schedules.
