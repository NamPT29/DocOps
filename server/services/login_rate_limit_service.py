from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock


class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int,
        window_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_failures <= 0 or window_seconds <= 0:
            raise ValueError("Giới hạn đăng nhập phải là số nguyên dương.")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _active_failures(self, key: str, now: float) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
            return deque()
        return failures

    def _retry_after(self, failures: deque[float], now: float) -> int:
        if len(failures) < self.max_failures:
            return 0
        return max(1, math.ceil(failures[0] + self.window_seconds - now))

    def retry_after(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            failures = self._active_failures(key, now)
            return self._retry_after(failures, now)

    def record_failure(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            failures = self._active_failures(key, now)
            if not failures:
                failures = self._failures.setdefault(key, deque())
            failures.append(now)
            return self._retry_after(failures, now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
