from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from kb.retry import (
    is_transient_error,
    retry_after_seconds,
    run_with_retries,
    TRANSIENT_HTTP_STATUSES,
)


def http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
    return HTTPError("https://api.example", code, "error", headers or {}, BytesIO(b""))


class FlakyOperation:
    def __init__(self, failures: list[Exception], result: str = "ok") -> None:
        self.failures = list(failures)
        self.result = result
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.result


def test_transient_errors_cover_connection_timeout_429_and_5xx() -> None:
    assert TRANSIENT_HTTP_STATUSES == {429, 500, 502, 503, 504}
    assert is_transient_error(http_error(429)) is True
    assert is_transient_error(http_error(503)) is True
    assert is_transient_error(URLError("connection refused")) is True
    assert is_transient_error(TimeoutError()) is True
    assert is_transient_error(ConnectionError()) is True
    assert is_transient_error(http_error(401)) is False
    assert is_transient_error(http_error(404)) is False
    assert is_transient_error(ValueError("not network")) is False


def test_retries_transient_failure_then_succeeds() -> None:
    operation = FlakyOperation([http_error(503), URLError("reset")])
    sleeps: list[float] = []

    result = run_with_retries(
        operation,
        operation="test.op",
        max_attempts=3,
        base_delay_seconds=0.5,
        max_delay_seconds=8.0,
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert operation.calls == 3
    assert len(sleeps) == 2
    assert 0.0 <= sleeps[0] <= 0.5
    assert 0.0 <= sleeps[1] <= 1.0


def test_non_transient_errors_are_not_retried() -> None:
    operation = FlakyOperation([http_error(401)])
    sleeps: list[float] = []

    with pytest.raises(HTTPError):
        run_with_retries(operation, operation="test.op", max_attempts=3, sleep=sleeps.append)

    assert operation.calls == 1
    assert sleeps == []


def test_exhausted_attempts_reraise_last_transient_error() -> None:
    operation = FlakyOperation([http_error(503), http_error(503), http_error(503)])
    sleeps: list[float] = []

    with pytest.raises(HTTPError):
        run_with_retries(
            operation,
            operation="test.op",
            max_attempts=3,
            base_delay_seconds=0.1,
            sleep=sleeps.append,
        )

    assert operation.calls == 3
    assert len(sleeps) == 2


def test_retry_after_header_is_honored_and_capped() -> None:
    operation = FlakyOperation([http_error(429, {"Retry-After": "3"})])
    sleeps: list[float] = []

    run_with_retries(
        operation,
        operation="test.op",
        max_attempts=2,
        max_delay_seconds=8.0,
        sleep=sleeps.append,
    )
    assert sleeps == [3.0]

    capped = FlakyOperation([http_error(429, {"Retry-After": "120"})])
    capped_sleeps: list[float] = []
    run_with_retries(
        capped,
        operation="test.op",
        max_attempts=2,
        max_delay_seconds=8.0,
        sleep=capped_sleeps.append,
    )
    assert capped_sleeps == [8.0]


def test_result_based_retry_returns_last_result_after_exhaustion() -> None:
    outcomes = [
        {"ok": False, "retryable": True, "retry_after": 0.25},
        {"ok": False, "retryable": True, "retry_after": None},
        {"ok": False, "retryable": True, "retry_after": None},
    ]
    calls: list[int] = []
    sleeps: list[float] = []

    def attempt() -> dict[str, Any]:
        calls.append(1)
        return outcomes[len(calls) - 1]

    result = run_with_retries(
        attempt,
        operation="test.op",
        max_attempts=3,
        base_delay_seconds=0.1,
        should_retry_result=lambda outcome: bool(outcome.get("retryable")),
        retry_after_from_result=lambda outcome: outcome.get("retry_after"),
        sleep=sleeps.append,
    )

    assert result["ok"] is False
    assert len(calls) == 3
    assert sleeps[0] == 0.25
    assert 0.0 <= sleeps[1] <= 0.2


def test_result_based_retry_stops_on_success() -> None:
    outcomes = [{"ok": False, "retryable": True}, {"ok": True}]
    calls: list[int] = []

    def attempt() -> dict[str, Any]:
        calls.append(1)
        return outcomes[len(calls) - 1]

    result = run_with_retries(
        attempt,
        operation="test.op",
        max_attempts=5,
        should_retry_result=lambda outcome: not outcome.get("ok"),
        sleep=lambda _delay: None,
    )

    assert result == {"ok": True}
    assert len(calls) == 2


def test_retry_after_seconds_parses_delta_and_rejects_garbage() -> None:
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("") is None
    assert retry_after_seconds("2") == 2.0
    assert retry_after_seconds("2.5") == 2.5
    assert retry_after_seconds("-3") == 0.0
    assert retry_after_seconds("not-a-date") is None


def test_retry_after_seconds_parses_http_date_in_the_past_as_zero() -> None:
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_env_knobs_drive_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITADEL_RETRY_MAX_ATTEMPTS", "1")
    operation = FlakyOperation([http_error(503)])

    with pytest.raises(HTTPError):
        run_with_retries(operation, operation="test.op", sleep=lambda _delay: None)

    assert operation.calls == 1
