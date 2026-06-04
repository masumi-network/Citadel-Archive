from __future__ import annotations

from typing import Any

import tomllib

from scripts import run_railway


def test_railway_toml_uses_testable_dispatcher() -> None:
    with open("railway.toml", "rb") as file:
        config = tomllib.load(file)

    assert config["deploy"]["startCommand"] == "python -m scripts.run_railway"


def test_web_mode_execs_uvicorn(monkeypatch: Any) -> None:
    calls: list[tuple[str, list[str]]] = []

    def execvp(binary: str, args: list[str]) -> None:
        calls.append((binary, args))
        raise RuntimeError("stop")

    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setattr(run_railway.os, "execvp", execvp)

    try:
        run_railway.run("web")
    except RuntimeError as exc:
        assert str(exc) == "stop"

    assert calls == [
        (
            "python",
            [
                "python",
                "-m",
                "uvicorn",
                "kb.server:app",
                "--host",
                "0.0.0.0",
                "--port",
                "9000",
            ],
        )
    ]


def test_learning_agent_mode_runs_github_sync(monkeypatch: Any) -> None:
    from scripts import run_github_sync

    calls: list[str] = []

    def run_sync() -> int:
        calls.append("github-sync")
        return 0

    monkeypatch.setattr(run_github_sync, "run", run_sync)

    assert run_railway.run("learning-agent") == 0
    assert calls == ["github-sync"]


def test_backup_mirror_mode_runs_backup_job(monkeypatch: Any) -> None:
    from scripts import run_backup_mirror

    calls: list[str] = []

    def run_mirror() -> int:
        calls.append("backup-mirror")
        return 0

    monkeypatch.setattr(run_backup_mirror, "run", run_mirror)

    assert run_railway.run("backup-mirror") == 0
    assert calls == ["backup-mirror"]


def test_unknown_mode_fails() -> None:
    assert run_railway.run("not-real") == 1
