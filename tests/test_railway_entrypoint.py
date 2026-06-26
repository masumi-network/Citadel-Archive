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


def test_cognify_mode_runs_cognify_without_verify(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCitadel:
        async def cognify_dataset(self, *, dataset: Any, verify: bool) -> dict[str, Any]:
            calls.append({"dataset": dataset, "verify": verify})
            return {"ok": True, "dataset": dataset, "graph_grew": True, "verify": verify}

    import kb.service as service

    monkeypatch.setattr(service.Citadel, "from_env", classmethod(lambda cls: FakeCitadel()))
    monkeypatch.delenv("CITADEL_COGNIFY_DATASET", raising=False)

    assert run_railway.run("cognify") == 0
    assert calls == [{"dataset": None, "verify": False}]


def test_cognify_verify_mode_fails_when_verification_fails(monkeypatch: Any) -> None:
    class FakeCitadel:
        async def cognify_dataset(self, *, dataset: Any, verify: bool) -> dict[str, Any]:
            return {
                "ok": True,
                "dataset": dataset,
                "graph_grew": False,
                "verify": verify,
                "verification": {"ok": False, "search_hit": False, "graph_grew": False},
            }

    import kb.service as service

    monkeypatch.setattr(service.Citadel, "from_env", classmethod(lambda cls: FakeCitadel()))
    monkeypatch.delenv("CITADEL_COGNIFY_DATASET", raising=False)

    assert run_railway.run("cognify-verify") == 1


def test_unknown_mode_fails() -> None:
    assert run_railway.run("not-real") == 1


def _patch_stages(
    monkeypatch: Any,
    calls: list[str],
    *,
    github_code: int = 0,
    backup_code: int = 0,
    self_improve_code: int = 0,
    github_raises: bool = False,
    skills_raises: bool = False,
) -> None:
    from scripts import run_backup_mirror, run_github_sync, run_self_improve

    import kb.skills as skills

    def fake_github() -> int:
        calls.append("github_sync")
        if github_raises:
            raise RuntimeError("github exploded")
        return github_code

    def fake_skills_refresh(state_path: Any = None) -> dict[str, Any]:
        calls.append("skills_refresh")
        if skills_raises:
            raise RuntimeError("skills exploded")
        return {"ok": True, "skills": 3, "changed": [], "added": [], "removed": []}

    def fake_self_improve() -> int:
        calls.append("self_improve")
        return self_improve_code

    def fake_backup() -> int:
        calls.append("backup_mirror")
        return backup_code

    def fake_repo_content() -> int:
        calls.append("repo_content_sync")
        return 0

    monkeypatch.setattr(run_github_sync, "run", fake_github)
    monkeypatch.setattr(run_railway, "_repo_content_sync_stage", fake_repo_content)
    monkeypatch.setattr(skills, "refresh_skill_catalog", fake_skills_refresh)
    monkeypatch.setattr(run_self_improve, "run", fake_self_improve)
    monkeypatch.setattr(run_backup_mirror, "run", fake_backup)


def _clear_pipeline_env(monkeypatch: Any) -> None:
    for name in (
        "CITADEL_PIPELINE_GITHUB_SYNC_ENABLED",
        "CITADEL_PIPELINE_REPO_CONTENT_SYNC_ENABLED",
        "CITADEL_PIPELINE_SKILLS_REFRESH_ENABLED",
        "CITADEL_PIPELINE_BACKUP_MIRROR_ENABLED",
        "CITADEL_SELF_IMPROVE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_pipeline_runs_all_enabled_stages_in_order(monkeypatch: Any) -> None:
    _clear_pipeline_env(monkeypatch)
    monkeypatch.setenv("CITADEL_SELF_IMPROVE_ENABLED", "true")
    calls: list[str] = []
    _patch_stages(monkeypatch, calls)

    assert run_railway.run("pipeline") == 0
    assert calls == ["github_sync", "repo_content_sync", "skills_refresh", "self_improve", "backup_mirror"]


def test_pipeline_self_improve_stage_is_off_by_default(monkeypatch: Any) -> None:
    _clear_pipeline_env(monkeypatch)
    calls: list[str] = []
    _patch_stages(monkeypatch, calls)

    assert run_railway.run("pipeline") == 0
    assert calls == ["github_sync", "repo_content_sync", "skills_refresh", "backup_mirror"]


def test_pipeline_stage_toggles_disable_individual_stages(monkeypatch: Any) -> None:
    _clear_pipeline_env(monkeypatch)
    monkeypatch.setenv("CITADEL_PIPELINE_SKILLS_REFRESH_ENABLED", "false")
    monkeypatch.setenv("CITADEL_PIPELINE_BACKUP_MIRROR_ENABLED", "false")
    calls: list[str] = []
    _patch_stages(monkeypatch, calls)

    assert run_railway.run("pipeline") == 0
    assert calls == ["github_sync", "repo_content_sync"]


def test_pipeline_continues_past_a_failed_stage(monkeypatch: Any) -> None:
    _clear_pipeline_env(monkeypatch)
    calls: list[str] = []
    _patch_stages(monkeypatch, calls, github_raises=True)

    assert run_railway.run("pipeline") == 0
    assert calls == ["github_sync", "repo_content_sync", "skills_refresh", "backup_mirror"]


def test_pipeline_exits_nonzero_only_when_all_enabled_stages_fail(monkeypatch: Any) -> None:
    _clear_pipeline_env(monkeypatch)
    monkeypatch.setenv("CITADEL_PIPELINE_SKILLS_REFRESH_ENABLED", "false")
    monkeypatch.setenv("CITADEL_PIPELINE_REPO_CONTENT_SYNC_ENABLED", "false")
    calls: list[str] = []
    _patch_stages(monkeypatch, calls, github_raises=True, backup_code=1)

    assert run_railway.run("pipeline") == 1
    assert calls == ["github_sync", "backup_mirror"]


def test_pipeline_mode_aliases_with_everything_disabled(monkeypatch: Any) -> None:
    _clear_pipeline_env(monkeypatch)
    monkeypatch.setenv("CITADEL_PIPELINE_GITHUB_SYNC_ENABLED", "false")
    monkeypatch.setenv("CITADEL_PIPELINE_REPO_CONTENT_SYNC_ENABLED", "false")
    monkeypatch.setenv("CITADEL_PIPELINE_SKILLS_REFRESH_ENABLED", "false")
    monkeypatch.setenv("CITADEL_PIPELINE_BACKUP_MIRROR_ENABLED", "false")
    calls: list[str] = []
    _patch_stages(monkeypatch, calls)

    assert run_railway.run("all") == 0
    assert run_railway.run("cron") == 0
    assert calls == []


# --- Evolve run-mode (ADR-0005 step 3) -------------------------------------

_EVOLVE_STAGE_ATTRS = [
    ("github_sync", "_github_sync_stage"),
    ("repo_content_sync", "_repo_content_sync_stage"),
    ("self_improve", "_self_improve_stage"),
    ("promotion", "_promotion_stage"),
    ("cognify", "_cognify_stage"),
]


def _patch_evolve_stages(
    monkeypatch: Any,
    calls: list[str],
    *,
    fail_codes: dict[str, int] | None = None,
    raise_stage: str | None = None,
) -> None:
    fail_codes = fail_codes or {}

    def make_stage(stage_name: str) -> Any:
        def stage() -> int:
            calls.append(stage_name)
            if stage_name == raise_stage:
                raise RuntimeError(f"{stage_name} exploded")
            return fail_codes.get(stage_name, 0)

        return stage

    for stage_name, attr in _EVOLVE_STAGE_ATTRS:
        monkeypatch.setattr(run_railway, attr, make_stage(stage_name))


def _clear_evolve_env(monkeypatch: Any) -> None:
    for name in (
        "CITADEL_EVOLVE_GITHUB_SYNC_ENABLED",
        "CITADEL_EVOLVE_REPO_CONTENT_SYNC_ENABLED",
        "CITADEL_EVOLVE_SELF_IMPROVE_ENABLED",
        "CITADEL_EVOLVE_PROMOTION_ENABLED",
        "CITADEL_EVOLVE_COGNIFY_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_evolve_runs_all_stages_in_chain_order(monkeypatch: Any) -> None:
    _clear_evolve_env(monkeypatch)
    calls: list[str] = []
    _patch_evolve_stages(monkeypatch, calls)

    assert run_railway.run("evolve") == 0
    assert calls == [
        "github_sync",
        "repo_content_sync",
        "self_improve",
        "promotion",
        "cognify",
    ]


def test_evolve_stage_toggles_disable_individual_stages(monkeypatch: Any) -> None:
    _clear_evolve_env(monkeypatch)
    monkeypatch.setenv("CITADEL_EVOLVE_SELF_IMPROVE_ENABLED", "false")
    monkeypatch.setenv("CITADEL_EVOLVE_PROMOTION_ENABLED", "false")
    calls: list[str] = []
    _patch_evolve_stages(monkeypatch, calls)

    assert run_railway.run("evolve") == 0
    assert calls == ["github_sync", "repo_content_sync", "cognify"]


def test_evolve_continues_past_a_failed_stage(monkeypatch: Any) -> None:
    _clear_evolve_env(monkeypatch)
    calls: list[str] = []
    _patch_evolve_stages(monkeypatch, calls, raise_stage="github_sync")

    assert run_railway.run("evolve") == 0
    assert calls == [
        "github_sync",
        "repo_content_sync",
        "self_improve",
        "promotion",
        "cognify",
    ]


def test_evolve_exits_nonzero_only_when_all_enabled_stages_fail(monkeypatch: Any) -> None:
    _clear_evolve_env(monkeypatch)
    for name in (
        "CITADEL_EVOLVE_REPO_CONTENT_SYNC_ENABLED",
        "CITADEL_EVOLVE_SELF_IMPROVE_ENABLED",
        "CITADEL_EVOLVE_PROMOTION_ENABLED",
        "CITADEL_EVOLVE_COGNIFY_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    calls: list[str] = []
    _patch_evolve_stages(monkeypatch, calls, raise_stage="github_sync")

    assert run_railway.run("evolve") == 1
    assert calls == ["github_sync"]
