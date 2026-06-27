from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from kb.capture import build_capture_payload, summarize_root
from kb.capture_config import CaptureConfig, CaptureRoot, save_capture_config
from kb.cli import _capture


def test_summarize_missing_path() -> None:
    summary = summarize_root(CaptureRoot(path="/no/such/path", tags=("personal",)))
    assert "path not found" in summary
    assert "Capture Root Tags: personal" in summary


def test_summarize_non_git_folder_with_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Title\n\nA local notes folder.\n")
    summary = summarize_root(CaptureRoot(path=str(tmp_path), tags=("personal",)))
    assert "non-git folder" in summary
    assert "A local notes folder." in summary


def test_summarize_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "README.md").write_text("a repo summary line\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init commit"], check=True)

    summary = summarize_root(CaptureRoot(path=str(tmp_path), tags=("org-work",)))
    assert "Latest:" in summary
    assert "init commit" in summary
    assert "a repo summary line" in summary


def test_build_capture_payload_appends_capture_tag_and_dedupes() -> None:
    payload = build_capture_payload(CaptureRoot(path="/x", tags=("org-work", "capture")))
    assert payload["tags"] == ["org-work", "capture"]
    assert payload["data"].startswith("# Capture summary")


def test_capture_dry_run_prints_payloads_without_network(tmp_path: Path, capsys) -> None:
    (tmp_path / "README.md").write_text("dry run notes\n")
    config_path = tmp_path / "capture.json"
    save_capture_config(
        CaptureConfig(node_url="https://node.example").with_root(str(tmp_path), ["personal"]),
        path=config_path,
    )
    args = argparse.Namespace(config=str(config_path), root=None, dry_run=True)
    asyncio.run(_capture(args))

    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1
    assert out[0]["tags"] == ["personal", "capture"]
    assert "dry run notes" in out[0]["preview"]


def test_capture_no_roots_warns(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "empty.json"
    save_capture_config(CaptureConfig(), path=config_path)
    args = argparse.Namespace(config=str(config_path), root=None, dry_run=True)
    asyncio.run(_capture(args))
    assert "Run `citadel setup`" in capsys.readouterr().err
