# Autonomous sync — Cursor and Codex

Citadel autosync is **IDE-agnostic** for git workflows.

## Universal: git push hook

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

## Claude Code (optional extra)

Merge `templates/claude-settings.json` into `.claude/settings.json` for
SessionEnd session distill on top of git push snapshots.

## Cursor

No Cursor-specific hook is required today. Use the git pre-push hook above.
Optionally add a project rule reminding agents to call `citadel_ingest` for
durable decisions mid-session.

## Codex / other agents

Same as Cursor: git push hook + MCP token. Agents read your Node and Central
via `citadel_search` and `citadel_session`.

## Linear tasks (after server sync)

Ask your agent: *"What do I need to do?"* — MCP tool `citadel_linear_my_issues`
reads your **Seat-Scoped Mirror** from the latest Linear sync.
