"""Sliding-window rate limiter for Claude CLI calls.

Tracks the timestamps of recent acquires in a deque. A call is allowed when
fewer than `max_calls` timestamps lie inside the last `window_seconds`.
`try_acquire()` returns None on success, or the wait-seconds until the next
slot opens on denial. No blocking — callers translate denial into HTTP 429.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class SlidingWindowLimiter:
    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls <= 0:
            raise ValueError(f"max_calls must be > 0, got {max_calls}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        self._max = max_calls
        self._window = float(window_seconds)
        self._now = now
        self._calls: deque[float] = deque()

    def try_acquire(self) -> float | None:
        now = self._now()
        cutoff = now - self._window
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()

        if len(self._calls) >= self._max:
            oldest = self._calls[0]
            return (oldest + self._window) - now

        self._calls.append(now)
        return None
