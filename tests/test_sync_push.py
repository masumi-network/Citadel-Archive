from __future__ import annotations

import importlib.util
import io
import json
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


def test_post_omits_dataset_field(monkeypatch: Any) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setenv("CITADEL_BASE_URL", "https://example.invalid")

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


def test_run_swallows_post_errors(monkeypatch: Any) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(sync_push, "_sync_one", boom)
    stdin = io.StringIO(
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef0 refs/heads/main "
        + "0" * 40
        + "\n"
    )
    assert sync_push.run(stdin, remote_name="origin") == 0


def test_ref_branch_name() -> None:
    assert sync_push.ref_branch_name("refs/heads/feature/foo") == "feature/foo"
