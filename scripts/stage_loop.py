"""One shared event loop for a multi-stage entrypoint run (#69).

Cognee caches its async DB engine (the asyncpg pool) on the FIRST event loop that
touches it and raises ``RuntimeError: got Future attached to a different loop`` on
any later loop. The evolve cron chains several cognee-touching stages
(``github_sync`` → ``repo_content_sync`` → ``self_improve`` → ``promotion`` →
``linear_sync``), and each used to run its body in its own ``asyncio.run()`` — so
only the first stage's loop worked and every later cognee stage failed silently
(the pass still exited 0). A worker thread and a fresh subprocess both hit this;
the only fix is to run every cognee-touching stage body on the SAME loop.

``stage_loop()`` installs one shared :class:`asyncio.Runner` for the duration of a
stage sequence; ``run_async()`` runs a coroutine on it (via ``runner.run``) so all
stages share one loop and cognee binds its engine exactly once. Callers with no
active shared loop (standalone jobs, unit tests) fall back to ``asyncio.run``, so
behaviour is unchanged outside the shared-loop context.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine, Iterator
from typing import Any, TypeVar

_T = TypeVar("_T")

# The single Runner installed by stage_loop() for the current stage sequence.
# None outside a shared-loop context, where run_async() falls back to asyncio.run.
_RUNNER: asyncio.Runner | None = None


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run *coro* on the shared stage loop if one is active, else ``asyncio.run``.

    Every cognee-touching stage body funnels through here so the whole stage
    sequence shares one loop (#69). With no shared loop active this is a drop-in
    for ``asyncio.run`` — standalone jobs and unit tests keep their prior
    per-call-loop behaviour.
    """
    runner = _RUNNER
    if runner is None:
        return asyncio.run(coro)
    return runner.run(coro)


@contextlib.contextmanager
def stage_loop() -> Iterator[None]:
    """Install one shared event loop for the enclosed stage sequence (#69).

    Every ``run_async`` call inside the block runs on this single loop, so cognee
    binds its cached async engine once and never trips the "Future attached to a
    different loop" error between stages. Nested use reuses the outer loop. On
    exit the :class:`asyncio.Runner` cancels any leftover tasks and closes the
    loop, mirroring ``asyncio.run`` cleanup.
    """
    global _RUNNER
    if _RUNNER is not None:
        # Already inside a shared-loop context; reuse the outer loop.
        yield
        return
    with asyncio.Runner() as runner:
        _RUNNER = runner
        try:
            yield
        finally:
            _RUNNER = None
