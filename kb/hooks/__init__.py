"""Citadel autosync hooks (stdlib-only, fail-silent).

Bundled in the package so `citadel onboard` can install working git pre-push and
Claude Code SessionEnd hooks with no vendored skill directory. Run as modules:
``python -m kb.hooks.sync_push`` / ``python -m kb.hooks.sync_session``.
"""
