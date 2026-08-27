from __future__ import annotations

import json
import logging
import os
from collections import Counter
from threading import RLock
from typing import Any, Callable

from cachetools import TTLCache

from server.settings import settings


logger = logging.getLogger(__name__)
_CACHE_PREFIX = "scan_to_excel:template_artifacts:v1"
_ALLOWED_NAMESPACES = frozenset(
    {"schema", "maxa_mapping", "don_vi_do_mapping", "address_mappings"}
)


class TemplateArtifactCache:
    """Cache only non-sensitive, file-derived template artifacts."""

    def __init__(self, *, redis_client=None, ttl_seconds: int = 30, maxsize: int = 256):
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self.local_cache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._local_revisions: dict[int, int] = {}
        self._pending_redis_invalidations: set[int] = set()
        self._metrics: Counter[str] = Counter()
        self._lock = RLock()

    @staticmethod
    def _revision_key(template_id: int) -> str:
        return f"{_CACHE_PREFIX}:{template_id}:revision"

    @staticmethod
    def _cache_key(namespace: str, template_id: int, file_version: str, revision: int) -> str:
        return f"{_CACHE_PREFIX}:{template_id}:{namespace}:{file_version}:{revision}"

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if namespace not in _ALLOWED_NAMESPACES:
            raise ValueError(f"Unsupported template cache namespace: {namespace}")

    def _record(self, metric: str) -> None:
        with self._lock:
            self._metrics[metric] += 1

    def _redis_revision(self, template_id: int) -> int:
        with self._lock:
            pending = template_id in self._pending_redis_invalidations
        if pending:
            self._redis.incr(self._revision_key(template_id))
            with self._lock:
                self._pending_redis_invalidations.discard(template_id)
        raw_revision = self._redis.get(self._revision_key(template_id))
        if raw_revision is None:
            return 0
        if isinstance(raw_revision, bytes):
            raw_revision = raw_revision.decode("ascii")
        return int(raw_revision)

    def get(self, namespace: str, template_id: int, file_version: str | None) -> Any | None:
        self._validate_namespace(namespace)
        if not file_version:
            self._record("misses")
            return None
        if self._redis is None:
            with self._lock:
                revision = self._local_revisions.get(template_id, 0)
                value = self.local_cache.get(
                    self._cache_key(namespace, template_id, file_version, revision)
                )
            self._record("hits" if value is not None else "misses")
            return value
        try:
            revision = self._redis_revision(template_id)
            payload = self._redis.get(
                self._cache_key(namespace, template_id, file_version, revision)
            )
            if payload is None:
                self._record("misses")
                return None
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            value = json.loads(payload)
        except Exception:
            self._record("backend_errors")
            self._record("misses")
            logger.warning("Template cache read failed; recomputing artifact", exc_info=True)
            return None
        self._record("hits")
        return value

    def set(self, namespace: str, template_id: int, file_version: str | None, value: Any) -> None:
        self._validate_namespace(namespace)
        if not file_version:
            return
        if self._redis is None:
            with self._lock:
                revision = self._local_revisions.get(template_id, 0)
                self.local_cache[
                    self._cache_key(namespace, template_id, file_version, revision)
                ] = value
            self._record("writes")
            return
        try:
            revision = self._redis_revision(template_id)
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            self._redis.setex(
                self._cache_key(namespace, template_id, file_version, revision),
                self._ttl_seconds,
                payload,
            )
            self._record("writes")
        except Exception:
            self._record("backend_errors")
            logger.warning("Template cache write failed", exc_info=True)

    def get_or_compute(
        self,
        namespace: str,
        template_id: int,
        file_version: str | None,
        loader: Callable[[], Any],
    ) -> Any:
        cached = self.get(namespace, template_id, file_version)
        if cached is not None:
            return cached
        value = loader()
        self.set(namespace, template_id, file_version, value)
        return value

    def invalidate(self, template_id: int) -> None:
        with self._lock:
            self._local_revisions[template_id] = self._local_revisions.get(template_id, 0) + 1
            prefix = f"{_CACHE_PREFIX}:{template_id}:"
            for key in [key for key in self.local_cache if key.startswith(prefix)]:
                self.local_cache.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.incr(self._revision_key(template_id))
                with self._lock:
                    self._pending_redis_invalidations.discard(template_id)
            except Exception:
                with self._lock:
                    self._pending_redis_invalidations.add(template_id)
                self._record("backend_errors")
                logger.warning("Template cache invalidation failed; retry is pending", exc_info=True)
        self._record("invalidations")

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                name: self._metrics[name]
                for name in ("hits", "misses", "writes", "invalidations", "backend_errors")
            }

    def clear_local(self) -> None:
        with self._lock:
            self.local_cache.clear()
            self._local_revisions.clear()
            self._pending_redis_invalidations.clear()
            self._metrics.clear()


def template_file_version(file_path: str | os.PathLike[str]) -> str | None:
    try:
        stat = os.stat(file_path)
    except OSError:
        return None
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def _create_template_artifact_cache() -> TemplateArtifactCache:
    redis_client = None
    if settings.redis_url:
        import redis

        redis_client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            health_check_interval=30,
        )
    return TemplateArtifactCache(
        redis_client=redis_client,
        ttl_seconds=settings.dictionary_cache_ttl_seconds,
    )


template_artifact_cache = _create_template_artifact_cache()


def get_template_cache_metrics() -> dict[str, int]:
    """Return process-local counters without exposing cached values or keys."""
    return template_artifact_cache.metrics()
