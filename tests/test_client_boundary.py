"""Guard the lightweight-client boundary.

The base `citadel-archive` install (no `[server]` extra) must be able to import
and run the client commands (onboard/status/capture/setup) without the heavy
server stack. This runs in a clean subprocess so it is not polluted by other
tests that import fastapi/cognee.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys

from kb.cli import _needs_server

_SERVER_THIRD_PARTY = ("cognee", "fastapi", "uvicorn", "mcp", "pydantic", "requests", "google")
_SERVER_LOCAL = ("kb.service", "kb.config", "kb.github_sync", "kb.learning_agent", "kb.models")


def test_importing_cli_pulls_no_server_modules() -> None:
    names = list(_SERVER_THIRD_PARTY) + list(_SERVER_LOCAL)
    code = (
        "import sys, kb.cli\n"
        f"leaked = [m for m in {names!r} if m in sys.modules]\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"client import leaked server modules: {result.stdout.strip()}"


def test_status_command_importable_without_server() -> None:
    # The client handlers must be reachable from the parser without server deps.
    code = (
        "import kb.cli\n"
        "p = kb.cli.build_parser()\n"
        "args = p.parse_args(['status', '--json', '--no-search', '--no-recent', "
        "'--node-url', 'https://x.invalid', '--repo', '/tmp', '--config', '/tmp/none.json'])\n"
        "assert args.handler.__name__ == '_status'"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_needs_server_decorator_gives_friendly_hint(capsys) -> None:
    @_needs_server
    async def boom(args: argparse.Namespace) -> int:
        raise ModuleNotFoundError("No module named 'cognee'", name="cognee")

    rc = asyncio.run(boom(argparse.Namespace(command="search")))
    assert rc == 2
    err = capsys.readouterr().err
    assert "citadel-archive[server]" in err
    assert "cognee" in err
