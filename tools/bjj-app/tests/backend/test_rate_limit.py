"""Tests for the sliding-window rate limiter.

Time is injected via a `now` callable so we never rely on wall-clock sleeps.
"""
from __future__ import annotations

import pytest

from server.analysis.rate_limit import SlidingWindowLimiter


def test_allows_up_to_max_calls_in_window():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=3, window_seconds=10.0, now=lambda: fake_now[0])

    assert limiter.try_acquire() is None
    assert limiter.try_acquire() is None
    assert limiter.try_acquire() is None


def test_denies_the_next_call_when_window_is_full():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0, now=lambda: fake_now[0])

    limiter.try_acquire()
    limiter.try_acquire()
    retry_after = limiter.try_acquire()

    assert retry_after is not None
    # With both calls at t=0, the oldest frees at t=10 → 10s wait.
    assert retry_after == pytest.approx(10.0, abs=1e-6)


def test_returns_accurate_retry_after_when_time_advances():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0, now=lambda: fake_now[0])

    limiter.try_acquire()  # t=0
    fake_now[0] = 3.0
    limiter.try_acquire()  # t=3
    fake_now[0] = 5.0

    retry_after = limiter.try_acquire()  # oldest expires at t=10 → wait 5s
    assert retry_after == pytest.approx(5.0, abs=1e-6)


def test_allows_again_after_the_oldest_call_ages_out():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0, now=lambda: fake_now[0])

    limiter.try_acquire()
    fake_now[0] = 2.0
    limiter.try_acquire()
    fake_now[0] = 11.0  # first call (t=0) now older than 10s window

    assert limiter.try_acquire() is None


def test_rejects_nonsense_construction():
    with pytest.raises(ValueError):
        SlidingWindowLimiter(max_calls=0, window_seconds=10.0)
    with pytest.raises(ValueError):
        SlidingWindowLimiter(max_calls=10, window_seconds=0)
