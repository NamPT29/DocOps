from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock
from typing import Protocol

from server.services.api_rate_limit_service import DatabaseRateLimiter


class RedisCounter(Protocol):
    def incrby(self, name: str, amount: int = 1) -> int: ...

    def expire(self, name: str, time: int) -> bool: ...

    def ttl(self, name: str) -> int: ...

    def get(self, name: str) -> int | bytes | str | None: ...

    def delete(self, *names: str) -> int: ...


class RateLimitBackendUnavailable(RuntimeError):
    """Raised when the configured distributed limiter cannot be reached."""


class DatabaseLoginRateLimiter:
    """Login limiter shared by every worker through the application database."""

    _SCOPE = "login-failure"

    def __init__(
        self,
        max_failures: int,
        window_seconds: int,
        *,
        limiter: DatabaseRateLimiter | None = None,
    ) -> None:
        self._limiter = limiter or DatabaseRateLimiter(max_failures, window_seconds)

    def retry_after(self, key: str) -> int:
        try:
            return self._limiter.retry_after(self._SCOPE, key)
        except Exception as exc:
            raise RateLimitBackendUnavailable(
                "Database rate-limit backend is unavailable"
            ) from exc

    def record_failure(self, key: str) -> int:
        try:
            retry_after = self._limiter.consume(self._SCOPE, key)
            return retry_after or self._limiter.retry_after(self._SCOPE, key)
        except Exception as exc:
            raise RateLimitBackendUnavailable(
                "Database rate-limit backend is unavailable"
            ) from exc

    def reset(self, key: str) -> None:
        try:
            self._limiter.reset(self._SCOPE, key)
        except Exception as exc:
            raise RateLimitBackendUnavailable(
                "Database rate-limit backend is unavailable"
            ) from exc


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


class RedisLoginRateLimiter:
    """Distributed login limiter backed by Redis."""

    def __init__(
        self,
        max_failures: int,
        window_seconds: int,
        *,
        redis_client: RedisCounter,
        key_prefix: str = "scan:login-rate-limit:",
    ) -> None:
        if max_failures <= 0 or window_seconds <= 0:
            raise ValueError("Giới hạn đăng nhập phải là số nguyên dương.")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._redis = redis_client
        self._key_prefix = key_prefix

    def _redis_key(self, key: str) -> str:
        return f"{self._key_prefix}{key}"

    def retry_after(self, key: str) -> int:
        try:
            redis_key = self._redis_key(key)
            failures = self._redis.get(redis_key)
            if failures is None or int(failures) < self.max_failures:
                return 0
            return max(1, int(self._redis.ttl(redis_key)))
        except Exception as exc:
            raise RateLimitBackendUnavailable("Redis rate-limit backend is unavailable") from exc

    def record_failure(self, key: str) -> int:
        try:
            redis_key = self._redis_key(key)
            failures = int(self._redis.incrby(redis_key, 1))
            if failures == 1:
                self._redis.expire(redis_key, self.window_seconds)
            if failures < self.max_failures:
                return 0
            return max(1, int(self._redis.ttl(redis_key)))
        except Exception as exc:
            raise RateLimitBackendUnavailable("Redis rate-limit backend is unavailable") from exc

    def reset(self, key: str) -> None:
        try:
            self._redis.delete(self._redis_key(key))
        except Exception as exc:
            raise RateLimitBackendUnavailable("Redis rate-limit backend is unavailable") from exc
