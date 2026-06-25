#!/usr/bin/env bash
# One-time Citadel autonomous sync setup for a repo clone.
# Installs the git pre-push hook and prints SessionEnd instructions for Claude Code.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SKILL_DIR="$ROOT/skills/citadel-proactive-ingest"
HOOK_SRC="$SKILL_DIR/templates/git-pre-push.sh"
HOOK_DST="$ROOT/.git/hooks/pre-push"

if [[ ! -f "$HOOK_SRC" ]]; then
  echo "Missing $HOOK_SRC — vendor citadel-proactive-ingest into this repo first." >&2
  exit 1
fi

mkdir -p "$ROOT/.git/hooks"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"

cat <<EOF
Citadel autosync installed.

1. Export your seat token once (same as MCP):
   export CITADEL_MCP_ACCESS_TOKEN='ctdl_...'

2. Git push hook: active at .git/hooks/pre-push
   Every push snapshots commit metadata to your private Node.

3. Claude Code SessionEnd (optional extra):
   Merge $SKILL_DIR/templates/claude-settings.json into .claude/settings.json

4. Cursor / Codex: git push is the universal path; no extra hook required.

Docs: docs/onboarding/citadel-autosync.md
EOF
