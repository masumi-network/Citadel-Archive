# citadel-proactive-ingest — org repo setup

Add autonomous personal-KB sync to a project repo: **SessionEnd** distill (Claude
Code) and **git push** commit snapshots (all IDEs) auto-sync to **their**
private Citadel node (`seat:{slug}`). One-time token setup per dev.

## What ships in this skill

| Path | Purpose |
|---|---|
| `SKILL.md` | Agent behavior + auto-sync docs |
| `scripts/sync_session.py` | SessionEnd distill + POST (stdlib only) |
| `scripts/sync_push.py` | Git pre-push commit snapshot + POST (stdlib only) |
| `templates/claude-settings.json` | Drop-in `.claude/settings.json` SessionEnd hook |
| `templates/git-pre-push.sh` | Installable `.git/hooks/pre-push` for push sync |
| `README.md` | This file |

## 1. Add the skill to the repo

Vendor this skill directory into the repo (or reference it from a shared skills
path) so that `skills/citadel-proactive-ingest/scripts/sync_session.py` exists
relative to the project root. The hook command resolves it via
`$CLAUDE_PROJECT_DIR`.

## 2. Copy the hook into `.claude/settings.json`

Merge `templates/claude-settings.json` into the repo's `.claude/settings.json`
(create the file if absent). The hook block:

```jsonc
{
  // SessionEnd fires once when a Claude Code session closes. The command is
  // NON-BLOCKING (the script always exits 0) and bounded by `timeout` seconds,
  // so a Citadel outage can never delay a dev's session close.
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            // Skill-relative path; $CLAUDE_PROJECT_DIR is the repo root.
            "command": "python3 \"$CLAUDE_PROJECT_DIR/skills/citadel-proactive-ingest/scripts/sync_session.py\"",
            "timeout": 20,
            // Only this var is exposed to the hook process — the seat token.
            "allowedEnvVars": ["CITADEL_MCP_ACCESS_TOKEN"]
          }
        ]
      }
    ]
  },
  // Whitelist the same var for the hook transport. The token is read from the
  // environment ONLY; it is never written into this committed file.
  "httpHookAllowedEnvVars": ["CITADEL_MCP_ACCESS_TOKEN"]
}
```

`.claude/settings.json` is committed and shared by the whole team, but it
contains **no secret** — only the var *name*. The token value lives in each
dev's shell environment.

## 3. One-time token export (per dev)

Each dev runs the connect wizard once to mint a **seat-writer** token and
exports it (the same token that powers `citadel_search` and MCP — most devs
already have it):

```bash
# https://citadel-archive-production.up.railway.app/skills/connect
export CITADEL_MCP_ACCESS_TOKEN='ctdl_...'
```

A seat-writer token has `default_dataset=seat:{slug}`, so the hook's POST omits
the `dataset` field and the write lands in that dev's private node. Add the
export to `~/.zshrc` / `~/.bashrc` to make it durable across shells.

Optional: set `CITADEL_BASE_URL` to override the hosted base (defaults to the
production URL). It must be `https://`.

## 4. Git push hook (universal — Cursor, Codex, Claude)

Install once per clone so every **push** snapshots commit metadata to your
private node:

```bash
cp skills/citadel-proactive-ingest/templates/git-pre-push.sh .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

The hook runs `scripts/sync_push.py` on pre-push. It captures commit hash,
message, author, branch, and changed file paths (not raw diffs). Same token,
same personal-by-default routing — **no `dataset` field**. Always exits 0; never
blocks push.

## 5. Opt-out

Either is enough:

- **Per dev, per machine:** unset `CITADEL_MCP_ACCESS_TOKEN`. With no token the
  hook is a clean no-op (no POST, exit 0).
- **Per dev, persistent:** add a `SessionEnd` override to
  `.claude/settings.local.json` (gitignored, dev-local) that drops or no-ops the
  hook. `settings.local.json` overrides the shared `settings.json`.

## Privacy posture

- **Personal-by-default.** Auto-sync sends **no `dataset` field** → the
  seat-writer token routes it to the dev's `seat:{slug}` node. Only that dev
  (and Central) can read it.
- **Distilled, not raw.** The hook sends a short curated note (recap, key
  decisions, files changed) — never the raw transcript.
- **Token never committed.** Read from the environment only; never printed,
  echoed, or written to `.claude/settings.json` or any tracked file.
- **HTTPS only.** The POST refuses any non-`https://` base URL.
- **Non-blocking.** The script catches everything and exits 0; it cannot block
  or fail a session close.

## Promote to shared Central

Auto-sync is always personal. To share a fact org-wide, ingest it mid-session
with a promotion **tag** (`org-ready` or `vault-contribution`) and still no
`dataset` field — see `SKILL.md`. Promote only ADRs, shared runbooks, and
interface contracts, and only when the user asks or the content is plainly
org-wide.
