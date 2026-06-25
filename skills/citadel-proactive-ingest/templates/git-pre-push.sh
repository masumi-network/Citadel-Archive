#!/bin/sh
# Citadel — autonomous commit snapshot to your private Node on git push.
#
# Install (from repo root):
#   cp skills/citadel-proactive-ingest/templates/git-pre-push.sh .git/hooks/pre-push
#   chmod +x .git/hooks/pre-push
#
# Requires CITADEL_MCP_ACCESS_TOKEN in the environment (same as MCP / SessionEnd).
# Always exits 0 — never blocks git push.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
SCRIPT="$ROOT/skills/citadel-proactive-ingest/scripts/sync_push.py"
if [ ! -f "$SCRIPT" ]; then
  exit 0
fi

python3 "$SCRIPT" "$1" || true
exit 0
