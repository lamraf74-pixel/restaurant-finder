"""Tests du helper générique de retry avec backoff (`utils/retry.py`)."""

from __future__ import annotations

import pytest

from restaurant_finder.utils.retry import call_with_retry


class _FlakyError(Exception):
    pass


class _OtherError(Exception):
    pass


def test_call_with_retry_returns_result_on_first_success() -> None:
    calls = []

    def func() -> str:
        calls.append(1)
        return "ok"

    result = call_with_retry(func, operation="test", attempts=3, sleep=lambda _: None)

    assert result == "ok"
    assert len(calls) == 1


def test_call_with_retry_retries_then_succeeds() -> None:
    attempts_made = []

    def func() -> str:
        attempts_made.append(1)
        if len(attempts_made) < 3:
            raise _FlakyError("échec transitoire")
        return "ok"

    sleeps: list[float] = []
    result = call_with_retry(
        func,
        operation="test",
        attempts=3,
        base_delay=1.0,
        backoff_factor=2.0,
        retry_on=(_FlakyError,),
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert len(attempts_made) == 3
    # Backoff exponentiel : 1.0, puis 2.0 (base_delay * backoff_factor**(n-1)).
    assert sleeps == [1.0, 2.0]


def test_call_with_retry_raises_last_exception_after_exhausting_attempts() -> None:
    def func() -> str:
        raise _FlakyError("toujours en échec")

    with pytest.raises(_FlakyError):
        call_with_retry(
            func,
            operation="test",
            attempts=3,
            retry_on=(_FlakyError,),
            sleep=lambda _: None,
        )


def test_call_with_retry_does_not_retry_on_unlisted_exception() -> None:
    calls = []

    def func() -> str:
        calls.append(1)
        raise _OtherError("pas transitoire")

    with pytest.raises(_OtherError):
        call_with_retry(
            func,
            operation="test",
            attempts=3,
            retry_on=(_FlakyError,),
            sleep=lambda _: None,
        )

    assert len(calls) == 1


def test_call_with_retry_treats_zero_attempts_as_one() -> None:
    calls = []

    def func() -> str:
        calls.append(1)
        return "ok"

    result = call_with_retry(func, operation="test", attempts=0, sleep=lambda _: None)

    assert result == "ok"
    assert len(calls) == 1
