# Citadel MCP Client Setup

Use these files when you want to connect Claude Code or Codex to the hosted
Citadel Archive with one copied config block.

## Claude Code

Copy `docs/mcp/claude-code-hosted.mcp.json` into your Claude project `.mcp.json`
or merge the `citadel` entry into an existing `.mcp.json`.

Replace:

```text
PASTE_CITADEL_TOKEN_HERE
```

with a Citadel service-account token.

## Codex

Copy `docs/mcp/codex-hosted.config.toml` into `~/.codex/config.toml`.

Replace:

```text
PASTE_CITADEL_TOKEN_HERE
```

with a Citadel service-account token.

The Codex template keeps write/admin tools approval-gated:

- `citadel_ingest`
- `citadel_record_feedback`
- `citadel_run_learning_agent`
- `citadel_improve`

## Connector Skill

Give another agent this raw skill URL and ask it to connect Citadel MCP:

```text
https://raw.githubusercontent.com/masumi-network/Citadel-Archive/main/plugins/citadel-archive-mcp/skills/citadel-mcp-connector/SKILL.md
```

The skill tells the agent to ask for the Citadel token, write the right client
config, and avoid committing or echoing the token.
