from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import pytest

from kb.capture_config import (
    DEFAULT_NODE_URL,
    CaptureConfig,
    CaptureRoot,
    capture_config_path,
    load_capture_config,
    normalize_path,
    normalize_tags,
    save_capture_config,
)
from kb.cli import _parse_root_arg, _setup


def test_normalize_tags_strips_lowercases_dedupes() -> None:
    assert normalize_tags([" Personal ", "personal", "", "Org-Work"]) == (
        "personal",
        "org-work",
    )


def test_normalize_tags_defaults_to_personal() -> None:
    assert normalize_tags([]) == ("personal",)
    assert normalize_tags(["  "]) == ("personal",)


def test_normalize_path_expands_user_and_makes_absolute() -> None:
    assert normalize_path("~/x").startswith(str(Path.home()))
    assert os.path.isabs(normalize_path("rel/path"))


def test_with_root_replaces_same_path() -> None:
    config = CaptureConfig().with_root("/tmp/a", ["personal"])
    config = config.with_root("/tmp/a", ["org-work"])

    assert len(config.roots) == 1
    assert config.roots[0] == CaptureRoot(path="/tmp/a", tags=("org-work",))


def test_capture_config_path_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", "/tmp/custom/capture.json")
    assert capture_config_path() == Path("/tmp/custom/capture.json")


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    config = (
        CaptureConfig(node_url="https://node.example")
        .with_root("/tmp/a", ["personal"])
        .with_root("/tmp/b", ["org-work", "Notes"])
    )
    save_capture_config(config, path=path, updated_at="2026-06-27T00:00:00+00:00")

    assert oct(path.stat().st_mode & 0o777) == "0o600"
    loaded = load_capture_config(path)
    assert loaded.node_url == "https://node.example"
    assert {r.path for r in loaded.roots} == {"/tmp/a", "/tmp/b"}
    assert loaded.roots[1].tags == ("org-work", "notes")
    assert loaded.updated_at == "2026-06-27T00:00:00+00:00"


def test_load_missing_returns_defaults(tmp_path: Path) -> None:
    config = load_capture_config(tmp_path / "absent.json")
    assert config.node_url == DEFAULT_NODE_URL
    assert config.roots == ()


def test_load_corrupt_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_text("{ not valid json")
    with pytest.raises(ValueError, match="corrupt capture config"):
        load_capture_config(path)


def test_load_non_object_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="expected a JSON object"):
        load_capture_config(path)


def test_from_dict_skips_bad_roots_and_version() -> None:
    config = CaptureConfig.from_dict(
        {
            "version": "not-an-int",
            "node_url": "https://node.example",
            "roots": ["bad-string", {"path": ""}, {"path": "/tmp/ok", "tags": ["personal"]}],
        }
    )
    assert config.version == 1
    assert [r.path for r in config.roots] == ["/tmp/ok"]


def test_parse_root_arg() -> None:
    assert _parse_root_arg("/tmp/a") == ("/tmp/a", ())
    assert _parse_root_arg("/tmp/a=personal,org-work") == (
        "/tmp/a",
        ("personal", "org-work"),
    )


def test_setup_non_interactive_writes_roots(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    args = argparse.Namespace(
        config=str(path),
        node_url="https://my-node.example/",
        root=["/tmp/work=org-work", "/tmp/notes"],
        non_interactive=True,
        show=False,
    )
    asyncio.run(_setup(args))

    loaded = load_capture_config(path)
    assert loaded.node_url == "https://my-node.example"
    by_path = {r.path: r.tags for r in loaded.roots}
    assert by_path["/tmp/work"] == ("org-work",)
    assert by_path["/tmp/notes"] == ("personal",)
    assert loaded.updated_at is not None
