# Citadel Auto-Sync — dev onboarding

Your Claude Code sessions in org repos auto-save a short, distilled note to
**your private Citadel node** when each session ends. One setup step, then it's
automatic and personal.

## The one step

Mint a **seat-writer** token from the connect wizard and export it once:

```bash
# https://citadel-archive-production.up.railway.app/skills/connect
export CITADEL_MCP_ACCESS_TOKEN='ctdl_...'
```

Add it to your `~/.zshrc` / `~/.bashrc` so it persists. This is the same token
that powers `citadel_search` and your MCP config — if Citadel search already
works for you, you're done. The repo already ships the SessionEnd hook in
`.claude/settings.json`; no per-project setup beyond having the token in your
environment.

## What auto-syncs, and when

- **When:** once, on every Claude Code `SessionEnd` (session close).
- **What:** a short distilled note — a 1-2 line recap, key decisions, files
  changed, notable facts. **Not** the raw transcript.
- **Tags:** `dev-session`, your git branch, and the repo name.
- **How it behaves:** non-blocking and fail-silent. If Citadel is down or the
  token is unset, your session still closes instantly — nothing breaks.

## Personal vs shared

| | Goes where | Who reads it |
|---|---|---|
| **Auto-sync (default)** | your private node `seat:{slug}` | only you (+ Central) |
| **Promoted** (tag `org-ready` / `vault-contribution`) | shared Central `masumi-network` | the whole org |

Auto-sync is **always personal** — it sends no `dataset` field, so your
seat-writer token routes it to your own node. To share something org-wide, ask
your agent to `citadel_ingest` it mid-session with an `org-ready` tag (ADRs,
shared runbooks, interface contracts). Promotion is always explicit.

## Privacy

- Token read from `CITADEL_MCP_ACCESS_TOKEN` only — never printed, echoed, or
  committed.
- Distilled note, never the raw transcript.
- HTTPS only.

## Opt-out

- **Quick:** unset `CITADEL_MCP_ACCESS_TOKEN` (the hook becomes a no-op).
- **Persistent:** add a `SessionEnd` override in `.claude/settings.local.json`
  (gitignored, dev-local) to disable the hook for you only.

## More

- Skill: `https://citadel-archive-production.up.railway.app/skills/proactive-ingest`
- Connect wizard: `https://citadel-archive-production.up.railway.app/skills/connect`
- Repo setup details: `skills/citadel-proactive-ingest/README.md`
