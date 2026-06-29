from __future__ import annotations

import io

import pytest

from kb.hooks import sync_start


def test_no_token_is_silent_noop(monkeypatch, capsys) -> None:
    monkeypatch.delenv(sync_start.TOKEN_ENV, raising=False)
    rc = sync_start.run(io.StringIO("{}"))
    assert rc == 0
    assert capsys.readouterr().out == ""  # nothing injected without a token


def test_empty_recent_is_silent(monkeypatch, capsys) -> None:
    monkeypatch.setenv(sync_start.TOKEN_ENV, "ctdl_x")
    monkeypatch.setattr(sync_start, "fetch_recent", lambda *a, **k: [])
    rc = sync_start.run(io.StringIO("{}"))
    assert rc == 0
    assert capsys.readouterr().out == ""  # quiet when there is no activity


def test_injects_digest_when_recent(monkeypatch, capsys) -> None:
    monkeypatch.setenv(sync_start.TOKEN_ENV, "ctdl_x")
    monkeypatch.setattr(
        sync_start,
        "fetch_recent",
        lambda *a, **k: [{"created_at": "2026-06-29T10:00:00", "title": "Shipped CLI overhaul"}],
    )
    rc = sync_start.run(io.StringIO("{}"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Citadel vault — recent activity" in out
    assert "Shipped CLI overhaul" in out
    assert "ctdl_x" not in out  # token never leaks into the digest


def test_failure_is_swallowed(monkeypatch, capsys) -> None:
    monkeypatch.setenv(sync_start.TOKEN_ENV, "ctdl_x")

    def boom(*a, **k):
        raise RuntimeError("node down")

    monkeypatch.setattr(sync_start, "fetch_recent", boom)
    assert sync_start.run(io.StringIO("{}")) == 0  # fail-silent, exit 0
    assert capsys.readouterr().out == ""


def test_fetch_recent_refuses_non_https() -> None:
    with pytest.raises(ValueError, match="non-HTTPS"):
        sync_start.fetch_recent("http://node.example", "ctdl_x")
