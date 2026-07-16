from __future__ import annotations

from pathlib import Path

from kb.hooks import receipt


def _iso_home(monkeypatch, path: Path) -> None:
    monkeypatch.delenv("CITADEL_CAPTURE_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CITADEL_HOME", str(path))


def test_activity_log_path_honors_citadel_home(monkeypatch, tmp_path: Path) -> None:
    _iso_home(monkeypatch, tmp_path)
    assert receipt.activity_log_path() == tmp_path / "activity.log"


def test_activity_log_path_from_capture_config_override(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "sub" / "capture.json"
    monkeypatch.setenv("CITADEL_CAPTURE_CONFIG_PATH", str(cfg))
    assert receipt.activity_log_path() == cfg.parent / "activity.log"


def test_write_receipt_appends_lines_with_private_perms(monkeypatch, tmp_path: Path) -> None:
    _iso_home(monkeypatch, tmp_path)
    receipt.write_receipt("push", "captured commit abc1234 → your Node")
    receipt.write_receipt("session", "session captured → your Node")

    log = tmp_path / "activity.log"
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "push" in lines[0] and "abc1234" in lines[0]
    assert "session" in lines[1]
    # Receipts are private (mirrors capture.json 0600).
    assert (log.stat().st_mode & 0o777) == 0o600


def test_write_receipt_never_surfaces_a_token(monkeypatch, tmp_path: Path) -> None:
    _iso_home(monkeypatch, tmp_path)
    # write_receipt only ever writes what it is handed — assert the summary is
    # verbatim and nothing token-shaped is invented.
    receipt.write_receipt("push", "captured commit deadbee → your Node")
    body = (tmp_path / "activity.log").read_text(encoding="utf-8")
    assert "ctdl_" not in body
    assert "Bearer" not in body


def test_write_receipt_never_raises_on_unwritable_path(monkeypatch, tmp_path: Path) -> None:
    # Parent of the log dir is a file, so mkdir fails — must be swallowed.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.delenv("CITADEL_CAPTURE_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CITADEL_HOME", str(blocker / "nested"))
    receipt.write_receipt("push", "should not crash")  # no exception = pass


def test_write_receipt_verbose_echoes_to_stderr(monkeypatch, tmp_path, capsys) -> None:
    _iso_home(monkeypatch, tmp_path)
    monkeypatch.setenv("CITADEL_HOOK_VERBOSE", "1")
    receipt.write_receipt("push", "captured X → your Node")
    err = capsys.readouterr().err
    assert "citadel: captured X → your Node" in err


def test_write_receipt_quiet_by_default(monkeypatch, tmp_path, capsys) -> None:
    _iso_home(monkeypatch, tmp_path)
    monkeypatch.delenv("CITADEL_HOOK_VERBOSE", raising=False)
    receipt.write_receipt("push", "captured Y → your Node")
    assert capsys.readouterr().err == ""


def test_roll_trims_oversized_log(monkeypatch, tmp_path: Path) -> None:
    _iso_home(monkeypatch, tmp_path)
    log = tmp_path / "activity.log"
    log.write_text("old line\n" * 100_000, encoding="utf-8")  # > 128 KB
    assert log.stat().st_size > receipt._MAX_BYTES

    receipt.write_receipt("push", "fresh line")

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= receipt._KEEP_LINES + 1
    assert lines[-1].endswith("fresh line")
