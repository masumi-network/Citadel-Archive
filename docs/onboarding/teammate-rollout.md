# Teammate Rollout — onboard a dev in 5 minutes

This is the canonical one-pager for M6.5. One admin step, then each teammate
runs **four setup steps** and is done — Claude Code sessions and git pushes
auto-save to their private Citadel node, and `citadel_search` works in any MCP
client. No dashboard login needed after setup.

> **Deep-dive:** [`citadel-autosync.md`](citadel-autosync.md) (what syncs),
> [`citadel-autosync-ides.md`](citadel-autosync-ides.md) (per-IDE notes).
> This page is the short version.

---

## Admin (once per teammate)

Mint a **seat-writer** token for the teammate. Seat-writer tokens route every
capture to that teammate's private node (`seat:{slug}`) — they cannot read or
write anyone else's node, and they get no admin powers.

```
Open:  https://citadel-archive-production.up.railway.app/skills/connect
       (admin → "Create seat" → role: writer → copy the ctdl_… token)
```

Hand the token to the teammate over a private channel. It is a secret — treat
it like a password.

---

## Teammate (4 steps)

> All four use the **same** `CITADEL_MCP_ACCESS_TOKEN`. Set it once; everything
> else points at it.

### 1 · Save your token

```bash
echo "export CITADEL_MCP_ACCESS_TOKEN='ctdl_…'" >> ~/.zshrc   # or ~/.bashrc
source ~/.zshrc
```

### 2 · Add the MCP server

Citadel is a hosted HTTP MCP server. Add this to the repo's `.mcp.json` (or your
global MCP config). The token is read from the env var set in step 1.

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

This gives any MCP client (Claude Code, Codex, Cursor) the `citadel_search`,
`citadel_session`, and `citadel_ingest` tools.

### 3 · Claude Code session hook (auto-sync on session close)

Copy the project template into the repo's Claude settings. This runs the
distill-and-save once per `SessionEnd`:

```bash
# From the repo root
mkdir -p .claude
cp skills/citadel-proactive-ingest/templates/claude-settings.json .claude/settings.json
```

The template wires a `SessionEnd` hook → `sync_session.py` with a 20s timeout.

### 4 · Git push hook (auto-sync on every push — all IDEs)

```bash
skills/citadel-proactive-ingest/scripts/install_autosync.sh
```

Works for Cursor, Codex, and Claude — git hooks are IDE-agnostic. Installs
`.git/hooks/pre-push` and prints SessionEnd instructions for Claude Code.

---

## Verify (30 seconds)

```bash
# Token works + MCP search returns results:
#   in Claude Code, ask: "use citadel_search to find what we decided about the vault"
# Linear tasks (after server cron sync):
#   ask: "what do I need to do?" → citadel_linear_my_issues
```

You should get a short note back sourced from your node / Central. If you get an
auth error, your token isn't in the environment of the client that's running
(restart the client so it picks up the new env var).

---

## What auto-syncs, and the guarantees

| Trigger | Captures | Destination |
|---|---|---|
| Claude Code `SessionEnd` | 1–2 line recap, decisions, files changed | your **Node** |
| `git push` | commit hash, message, author, branch, changed paths | your **Node** |
| Railway GitHub cron | org repo digest | **Central** |
| Railway Linear cron | workspace + your assigned issues (**Seat-Scoped Mirror**) | **Central** + your **Node** |

- **Always fail-silent.** Every hook ends in `exit 0` / `|| true`. If Citadel is
  down or the token is missing, your session close and your push still succeed.
- **Always personal.** Auto-sync sends no `dataset`, so it lands in your private
  node. To share org-wide, ingest mid-session with an `org-ready` tag.
- **No raw content.** Hooks capture metadata + a distilled recap, never raw
  transcripts or diffs.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `citadel_search` auth error | Restart the MCP client so it re-reads `CITADEL_MCP_ACCESS_TOKEN`. |
| Nothing lands in my node after a session | Confirm `.claude/settings.json` exists and the token env var is exported in the shell that *launched* Claude Code (not a later shell). |
| Push still works but no node entry | Expected for now — the hook only fires if `skills/citadel-proactive-ingest/scripts/sync_push.py` exists at repo root. Re-check step 4 from the repo root. |
| Token leaked in chat/logs | Ask the admin to **revoke + re-mint** (Access page → revoke). Old captures stay. |

---

## Rollout checklist (for the admin driving the team)

- [ ] Minted a seat-writer token for each teammate
- [ ] Each teammate confirmed `citadel_search` returns results
- [ ] Each teammate has `.claude/settings.json` + `.git/hooks/pre-push` in the org repos they work in
- [ ] Reminded everyone: leaked tokens get revoked, not recovered
- [ ] (Post-rollout) rotate `CITADEL_ADMIN_KEY` if it was shared during setup
