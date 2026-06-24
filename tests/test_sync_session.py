from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest

# sync_session lives under a skill dir (not an importable package), so load it
# by file path.
_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "citadel-proactive-ingest"
    / "scripts"
    / "sync_session.py"
)
_spec = importlib.util.spec_from_file_location("sync_session", _MODULE_PATH)
assert _spec and _spec.loader
sync_session = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_session)


def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"content": text}}


def _assistant_text(text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }


def _assistant_edit(file_path: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": file_path}}
            ]
        },
    }


def _sample_entries() -> list[dict[str, Any]]:
    return [
        _user("Build the autonomous personal-KB sync hook for org devs."),
        _assistant_text("I chose urllib so the script stays stdlib-only."),
        _assistant_edit("skills/citadel-proactive-ingest/scripts/sync_session.py"),
        _assistant_edit("tests/test_sync_session.py"),
        _assistant_text("Done. The hook is non-blocking and personal-by-default."),
    ]


def _write_transcript(tmp_path: Path, entries: list[Any]) -> Path:
    path = tmp_path / "transcript.jsonl"
    lines = [json.dumps(e) if not isinstance(e, str) else e for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class _RecordingPost:
    """Capture post_ingest calls instead of hitting the network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, base_url: str, token: str, data: str, tags: list[str]) -> None:
        self.calls.append(
            {"base_url": base_url, "token": token, "data": data, "tags": tags}
        )


# --- distillation -----------------------------------------------------------


def test_distill_produces_nonempty_short_note() -> None:
    note = sync_session.distill_transcript(_sample_entries())
    assert note.strip()
    assert "Dev session note" in note
    assert "Task:" in note
    # Decision marker ("chose") was captured.
    assert "urllib" in note
    # Files changed section present.
    assert "sync_session.py" in note


def test_distill_empty_transcript_is_safe() -> None:
    note = sync_session.distill_transcript([])
    assert isinstance(note, str)
    assert note.strip()  # still a valid (placeholder) note, never crashes


# --- size cap ---------------------------------------------------------------


def test_size_cap_truncates(monkeypatch: Any) -> None:
    monkeypatch.setenv("CITADEL_MCP_MAX_INGEST_BYTES", "50")
    assert sync_session._max_ingest_bytes() == 50
    big = "x" * 1000
    out = sync_session._truncate_utf8(big, 50)
    assert len(out.encode("utf-8")) <= 50


def test_truncate_never_splits_multibyte() -> None:
    # 10 emoji = 40 UTF-8 bytes; cap at 7 bytes must not yield a partial char.
    text = "😀" * 10
    out = sync_session._truncate_utf8(text, 7)
    assert len(out.encode("utf-8")) <= 7
    # Decodes cleanly (no replacement char from a split).
    assert out == "😀"


# --- defensive transcript parsing -------------------------------------------


def test_malformed_lines_skipped_without_crash(tmp_path: Path) -> None:
    entries: list[Any] = [
        _user("Real prompt here."),
        "{ this is not valid json",
        "",
        _assistant_edit("a.py"),
        "still : not json :::",
        _assistant_text("We decided to ship it."),
    ]
    path = _write_transcript(tmp_path, entries)
    parsed = sync_session._iter_transcript(str(path))
    # 3 valid dict entries; 2 malformed + 1 blank skipped.
    assert len(parsed) == 3
    note = sync_session.distill_transcript(parsed)
    assert "Real prompt here." in note
    assert "a.py" in note


def test_iter_transcript_missing_file_returns_empty() -> None:
    assert sync_session._iter_transcript("/nonexistent/path/to/transcript.jsonl") == []


# --- run(): missing token -> no POST + clean exit ---------------------------


def test_missing_token_no_post_clean_exit(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.delenv("CITADEL_MCP_ACCESS_TOKEN", raising=False)
    recorder = _RecordingPost()
    monkeypatch.setattr(sync_session, "post_ingest", recorder)

    path = _write_transcript(tmp_path, _sample_entries())
    payload = json.dumps(
        {
            "transcript_path": str(path),
            "cwd": str(tmp_path),
            "session_id": "s1",
            "hook_event_name": "SessionEnd",
        }
    )
    code = sync_session.run(io.StringIO(payload))
    assert code == 0
    assert recorder.calls == []  # no POST without a token


# --- run(): personal-by-default (no dataset field on POST) -------------------


def test_post_omits_dataset_field(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setenv("CITADEL_BASE_URL", "https://example.invalid")
    # Avoid invoking real git in build_tags.
    monkeypatch.setattr(sync_session, "build_tags", lambda cwd: ["dev-session"])

    captured: dict[str, Any] = {}

    class _FakeResp:
        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b""

    def fake_urlopen(request: Any, timeout: int | None = None) -> _FakeResp:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp()

    monkeypatch.setattr(sync_session.urllib.request, "urlopen", fake_urlopen)

    path = _write_transcript(tmp_path, _sample_entries())
    payload = json.dumps(
        {
            "transcript_path": str(path),
            "cwd": str(tmp_path),
            "session_id": "s1",
            "hook_event_name": "SessionEnd",
        }
    )
    code = sync_session.run(io.StringIO(payload))
    assert code == 0

    # POST happened, over HTTPS, with the token in the Authorization header.
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.invalid/ingest"
    auth = captured["headers"].get("Authorization")
    assert auth == "Bearer ctdl_test_token"

    # Personal-by-default: NO dataset field on the body.
    body = captured["body"]
    assert "dataset" not in body
    assert set(body.keys()) == {"data", "tags"}
    assert body["data"].strip()
    assert body["tags"] == ["dev-session"]


# --- HTTPS-only invariant ----------------------------------------------------


def test_post_refuses_non_https() -> None:
    with pytest.raises(ValueError):
        sync_session.post_ingest(
            "http://example.invalid", "ctdl_x", "note", ["dev-session"]
        )


def test_redirects_are_not_followed() -> None:
    # A 3xx (esp. an https->http downgrade) must not re-send the Authorization
    # header. The handler refuses to follow any redirect.
    handler = sync_session._NoRedirectHandler()
    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "http://evil.invalid")
        is None
    )


def test_run_swallows_post_errors(monkeypatch: Any, tmp_path: Path) -> None:
    """A failing POST must never raise out of the hook; run() returns 0."""
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_test_token")
    monkeypatch.setattr(sync_session, "build_tags", lambda cwd: ["dev-session"])

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(sync_session, "post_ingest", boom)

    path = _write_transcript(tmp_path, _sample_entries())
    payload = json.dumps({"transcript_path": str(path), "cwd": str(tmp_path)})
    assert sync_session.run(io.StringIO(payload)) == 0


def test_run_handles_garbage_stdin() -> None:
    # Non-JSON STDIN must not crash; clean exit.
    assert sync_session.run(io.StringIO("not json at all {{{")) == 0
