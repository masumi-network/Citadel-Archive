"""Headless / agent-facing CLI surface — every teammate command emits clean,
parseable JSON to stdout under `--json`, never prompts, and sets exit codes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from kb.cli import build_parser


def _run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(args.handler(args))


def test_setup_json_emits_pure_config(tmp_path: Path, capsys) -> None:
    cfg = tmp_path / "cap.json"
    rc = _run(
        [
            "setup", "--non-interactive", "--json",
            "--node-url", "https://node.example",
            "--root", f"{tmp_path}=org-work",
            "--config", str(cfg),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)  # pure JSON, no "Saved …" prose
    assert out["node_url"] == "https://node.example"
    assert out["roots"][0]["tags"] == ["org-work"]


def test_capture_json_dry_run_is_clean(tmp_path: Path, capsys) -> None:
    cfg = tmp_path / "cap.json"
    (tmp_path / "README.md").write_text("a summary line\n")
    _run(["setup", "--non-interactive", "--json", "--root", f"{tmp_path}=personal", "--config", str(cfg)])
    capsys.readouterr()

    rc = _run(["capture", "--dry-run", "--json", "--config", str(cfg)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list)
    assert out[0]["tags"] == ["personal", "capture"]


def test_capture_json_real_post_shape(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg = tmp_path / "cap.json"
    _run(["setup", "--non-interactive", "--json", "--node-url", "https://node.example",
          "--root", f"{tmp_path}=personal", "--config", str(cfg)])
    capsys.readouterr()
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_headless_token")
    monkeypatch.setattr("kb.cli.post_capture", lambda *a, **k: {"status": "ok"})

    rc = _run(["capture", "--json", "--config", str(cfg)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["results"][0]["ok"] is True


def test_onboard_json_no_prompts(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path
    (repo / ".git" / "hooks").mkdir(parents=True)
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(tmp_path / "cap.json"))
    # Token from env (not argv) — the secure headless path; never echoed.
    monkeypatch.setenv("CITADEL_MCP_ACCESS_TOKEN", "ctdl_headless_abcdef1234")

    rc = _run(
        [
            "onboard", "--non-interactive", "--json",
            "--repo", str(repo),
            "--shell-rc", str(tmp_path / ".zshrc"),
            "--no-capture",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    names = {s["name"] for s in out["steps"]}
    assert "git pre-push hook" in names and "SessionEnd hook" in names
    assert "…" in out["token_masked"]  # masked, never the raw token
    assert "ctdl_headless_abcdef1234" not in json.dumps(out)
