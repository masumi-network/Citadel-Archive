from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_home(tmp_path_factory, monkeypatch):
    """Point user-scope Claude config at a throwaway home for every test.

    Onboarding now writes session hooks to ~/.claude/settings.json (#38); without
    this guard the test suite would mutate the developer's real config. kb.onboard
    .claude_home() honors CITADEL_HOME, so this fully isolates it.
    """
    home = tmp_path_factory.mktemp("citadel_home")
    monkeypatch.setenv("CITADEL_HOME", str(home))
    yield
