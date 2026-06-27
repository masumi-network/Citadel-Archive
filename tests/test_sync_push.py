from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "citadel-proactive-ingest"
    / "scripts"
    / "sync_push.py"
)
_spec = importlib.util.spec_from_file_location("sync_push", _MODULE_PATH)
assert _spec and _spec.loader
sync_push = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_push)


def test_parse_pre_push_lines_skips_deletes() -> None:
    zero = "0" * 40
    text = "\n".join(
        [
            f"refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main {zero}",
            f"refs/heads/del {zero} refs/heads/del abcdef0123456789abcdef0123456789abcdef0",
        ]
    )
    rows = sync_push.parse_pre_push_lines(text)
    assert len(rows) == 1
    assert rows[0]["local_sha"].startswith("abcdef")


def test_format_commit_snapshot_includes_metadata() -> None:
    note = sync_push.format_commit_snapshot(
        commit_hash="a" * 40,
        short_hash="abc1234",
        author="John Doe",
        email="john@example.com",
        committed_at="2026-06-25 10:00:00 +0000",
        subject="feat: add git push sync",
        body="Optional body line.",
        branch="main",
        remote_name="origin",
        remote_ref="refs/heads/main",
        repo_name="Citadel-Archive",
        changed_files=["kb/foo.py", "tests/test_sync_push.py"],
    )
    assert "Git commit snapshot" in note
    assert "abc1234" in note
    assert "John Doe" in note
    assert "feat: add git push sync" in note
    assert "kb/foo.py" in note
    assert "origin (main)" in note


def test_missing_token_no_post(monkeypatch: Any) -> None:
    monkeypatch.delenv("CITADEL_MCP_ACCESS_TOKEN", raising=False)
    recorder: list[Any] = []

    def fake_sync(*args: Any, **kwargs: Any) -> None:
        recorder.append((args, kwargs))

    monkeypatch.setattr(sync_push, "_sync_one", fake_sync)
    stdin = io.StringIO(
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0
    assert recorder == []


def test_post_omits_dataset_field(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setenv("CITADEL_BASE_URL", "https://example.invalid")
    # No allowlist config → original always-capture behavior (hermetic).
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(tmp_path / "absent.json"))

    captured: dict[str, Any] = {}

    class _FakeResp:
        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b""

    def fake_urlopen(request: Any, timeout: int | None = None) -> _FakeResp:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        return _FakeResp()

    monkeypatch.setattr(sync_push.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        sync_push,
        "build_commit_snapshot",
        lambda *args, **kwargs: "# Git commit snapshot\n\n**test**",
    )
    monkeypatch.setattr(sync_push, "git_toplevel", lambda cwd="": "/tmp/repo")
    monkeypatch.setattr(sync_push, "build_tags", lambda cwd, branch="": ["git-push"])

    stdin = io.StringIO(
        "refs/heads/feature abcdef0123456789abcdef0123456789abcdef0 "
        "refs/heads/feature "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0
    body = captured["body"]
    assert "dataset" not in body
    assert body["tags"] == ["git-push"]
    assert captured["headers"].get("Authorization") == "Bearer ctdl_test_token"


def test_post_refuses_non_https() -> None:
    with pytest.raises(ValueError):
        sync_push.post_ingest("http://example.invalid", "ctdl_x", "note", ["git-push"])


def test_run_swallows_post_errors(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    # Hermetic: no allowlist config so the gate doesn't short-circuit _sync_one.
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(tmp_path / "absent.json"))

    called: list[bool] = []

    def boom(*args: Any, **kwargs: Any) -> None:
        called.append(True)
        raise RuntimeError("network down")

    monkeypatch.setattr(sync_push, "_sync_one", boom)
    stdin = io.StringIO(
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0
    assert called  # proves the swallowed-exception path actually executed


def test_ref_branch_name() -> None:
    assert sync_push.ref_branch_name("refs/heads/feature/foo") == "feature/foo"


def _write_capture_config(path: Path, roots: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"version": 1, "roots": roots}))


def test_load_capture_roots_none_when_absent(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(tmp_path / "absent.json"))
    assert sync_push.load_capture_roots() is None


def test_load_capture_roots_empty_on_corrupt(monkeypatch: Any, tmp_path: Path) -> None:
    config = tmp_path / "capture.json"
    config.write_text("{ not json")
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(config))
    # Fail closed: corrupt config approves nothing (empty list), not None.
    assert sync_push.load_capture_roots() == []


def test_matched_root_containment(tmp_path: Path) -> None:
    roots = [{"path": "/tmp/work", "tags": ["org-work"]}]
    assert sync_push.matched_root("/tmp/work/sub", roots)["tags"] == ["org-work"]
    assert sync_push.matched_root("/tmp/worktree", roots) is None


def test_matched_root_slash_matches_any() -> None:
    roots = [{"path": "/", "tags": ["personal"]}]
    assert sync_push.matched_root("/anywhere/at/all", roots)["tags"] == ["personal"]


def test_matched_root_resolves_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    roots = [{"path": str(link), "tags": ["org-work"]}]
    # git reports the physical path; it must still match the symlinked config root.
    assert sync_push.matched_root(str(real / "sub"), roots)["tags"] == ["org-work"]


def test_run_corrupt_config_fails_closed(monkeypatch: Any, tmp_path: Path) -> None:
    config = tmp_path / "capture.json"
    config.write_text("{ broken")
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(config))
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setattr(sync_push, "git_toplevel", lambda cwd="": "/tmp/some-repo")

    posted: list[Any] = []
    monkeypatch.setattr(sync_push, "_sync_one", lambda *a, **k: posted.append(k))

    stdin = io.StringIO(
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0
    assert posted == []  # corrupt allowlist captures nothing


def test_run_skips_repo_outside_allowlist(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    config = tmp_path / "capture.json"
    _write_capture_config(config, [{"path": "/some/approved", "tags": ["personal"]}])
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(config))
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setattr(sync_push, "git_toplevel", lambda cwd="": "/tmp/other-repo")

    posted: list[Any] = []
    monkeypatch.setattr(sync_push, "_sync_one", lambda *a, **k: posted.append(k))

    stdin = io.StringIO(
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0
    assert posted == []
    assert "not an Approved Capture Root" in capsys.readouterr().err


def test_run_captures_approved_repo_with_root_tags(monkeypatch: Any, tmp_path: Path) -> None:
    config = tmp_path / "capture.json"
    _write_capture_config(config, [{"path": "/tmp/approved", "tags": ["org-work"]}])
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(config))
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setattr(sync_push, "git_toplevel", lambda cwd="": "/tmp/approved")

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sync_push, "_sync_one", lambda *a, **k: calls.append(k))

    stdin = io.StringIO(
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0
    assert len(calls) == 1
    assert calls[0]["capture_tags"] == ["org-work"]
