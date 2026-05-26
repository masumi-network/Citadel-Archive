from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from kb.cognee_client import CogneePublicClient


@pytest.mark.asyncio
async def test_cognee_public_client_runs_startup_migrations_once(monkeypatch: Any) -> None:
    calls: list[str] = []

    async def run_startup_migrations() -> None:
        calls.append("migrate")

    async def remember(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def recall(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"ok": True}]

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            run_startup_migrations=run_startup_migrations,
            remember=remember,
            recall=recall,
        ),
    )
    client = CogneePublicClient()

    await client.remember("note", dataset_name="notes")
    await client.recall("note", dataset="notes")

    assert calls == ["migrate"]
