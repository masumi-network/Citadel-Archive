from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any

from kb.config import CitadelConfig


# --- config parsing --------------------------------------------------------


def test_evolve_scheduler_config_from_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("CITADEL_EVOLVE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("CITADEL_EVOLVE_INTERVAL_SECONDS", "3600")
    config = CitadelConfig.from_env(env_file=None)
    assert config.evolve_scheduler_enabled is True
    assert config.evolve_interval_seconds == 3600


def test_evolve_scheduler_config_defaults(monkeypatch: Any) -> None:
    monkeypatch.delenv("CITADEL_EVOLVE_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("CITADEL_EVOLVE_INTERVAL_SECONDS", raising=False)
    config = CitadelConfig.from_env(env_file=None)
    assert config.evolve_scheduler_enabled is False
    assert config.evolve_interval_seconds == 21600


# --- scheduler wiring ------------------------------------------------------


def _fake_citadel(*, enabled: bool, interval: int = 21600) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            evolve_scheduler_enabled=enabled,
            evolve_interval_seconds=interval,
        )
    )


def test_start_evolve_scheduler_disabled_returns_none(monkeypatch: Any) -> None:
    import kb.server as server

    monkeypatch.setattr(server, "get_citadel", lambda: _fake_citadel(enabled=False))
    assert server._start_evolve_scheduler() is None


async def test_start_and_stop_evolve_scheduler_enabled(monkeypatch: Any) -> None:
    import kb.server as server

    # Huge interval: the loop sleeps before its first pass, so run_evolve never
    # fires here — we only assert the task starts and then cancels cleanly.
    monkeypatch.setattr(
        server, "get_citadel", lambda: _fake_citadel(enabled=True, interval=999_999)
    )
    task = server._start_evolve_scheduler()
    assert task is not None
    assert not task.done()
    await server._stop_evolve_scheduler(task)
    assert task.done()


async def test_stop_evolve_scheduler_handles_none() -> None:
    import kb.server as server

    # No-op when the scheduler was never started (disabled path).
    await server._stop_evolve_scheduler(None)


class _FakeProc:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:  # pragma: no cover - only on cancel
        pass


async def test_evolve_scheduler_loop_spawns_evolve_subprocess(monkeypatch: Any) -> None:
    import kb.server as server

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def fake_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        calls.append((args, kwargs))
        return _FakeProc(0)

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", fake_exec)

    task = asyncio.create_task(server._evolve_scheduler_loop(0.001))
    try:
        for _ in range(300):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(calls) >= 2
    # Runs scripts.run_railway in a fresh process, in evolve mode.
    args, kwargs = calls[0]
    assert args[1:] == ("-m", "scripts.run_railway")
    assert kwargs["env"]["CITADEL_RUN_MODE"] == "evolve"


async def test_evolve_scheduler_loop_survives_a_failed_pass(monkeypatch: Any) -> None:
    import kb.server as server

    calls: list[int] = []

    async def flaky_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("spawn boom")
        return _FakeProc(0)

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", flaky_exec)

    task = asyncio.create_task(server._evolve_scheduler_loop(0.001))
    try:
        for _ in range(300):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # First spawn raised; the loop kept going and spawned a second pass.
    assert len(calls) >= 2
