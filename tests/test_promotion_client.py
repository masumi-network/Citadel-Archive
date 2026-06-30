from __future__ import annotations

import pytest

import kb.promotion_client as pc
from kb.promotion_client import PromotionClientError, _request


def test_request_converts_read_timeout_to_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # #39: a read-phase timeout is a bare TimeoutError (not a URLError) and must be
    # converted to PromotionClientError so the CLI prints a clean line, not a traceback.
    def boom(req, timeout):  # noqa: ANN001, ARG001
        raise TimeoutError("the read operation timed out")

    monkeypatch.setattr(pc._OPENER, "open", boom)

    with pytest.raises(PromotionClientError) as exc_info:
        _request("GET", "/api/session", base_url="https://node.example", token="ctdl_t")

    assert not isinstance(exc_info.value, TimeoutError)
    assert "timed out" in str(exc_info.value).lower()


def test_request_converts_oserror_to_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(req, timeout):  # noqa: ANN001, ARG001
        raise OSError("connection reset by peer")

    monkeypatch.setattr(pc._OPENER, "open", boom)

    with pytest.raises(PromotionClientError) as exc_info:
        _request("GET", "/api/session", base_url="https://node.example", token="ctdl_t")

    assert "connection reset by peer" in str(exc_info.value)
