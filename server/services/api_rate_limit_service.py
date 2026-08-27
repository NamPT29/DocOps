from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from server.database import SessionLocal
from server.models import ApiRateLimitBucket
from server.settings import settings


class DatabaseRateLimiter:
    """A fixed-window limiter whose counters are shared through the app DB."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError("Giới hạn API phải là số nguyên dương.")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._session_factory = session_factory
        self._clock = clock

    def _bucket_values(self, scope: str, key: str) -> tuple[str, datetime, float]:
        now = float(self._clock())
        window_number = int(now) // self.window_seconds
        expires_timestamp = (window_number + 1) * self.window_seconds
        raw_key = f"{scope}\0{key}\0{window_number}".encode("utf-8")
        bucket_key = hashlib.sha256(raw_key).hexdigest()
        expires_at = datetime.fromtimestamp(
            expires_timestamp,
            tz=timezone.utc,
        ).replace(tzinfo=None)
        return bucket_key, expires_at, now

    def consume(self, scope: str, key: str, *, cost: int = 1) -> int:
        if cost <= 0:
            raise ValueError("Chi phí giới hạn API phải là số nguyên dương.")

        bucket_key, expires_at, now = self._bucket_values(scope, key)
        now_utc = datetime.fromtimestamp(now, tz=timezone.utc).replace(tzinfo=None)
        table = ApiRateLimitBucket.__table__

        with self._session_factory() as db:
            dialect_name = db.get_bind().dialect.name
            if dialect_name == "postgresql":
                insert_statement = postgresql_insert(table)
            elif dialect_name == "sqlite":
                insert_statement = sqlite_insert(table)
            else:
                raise RuntimeError(
                    f"Database '{dialect_name}' chưa hỗ trợ rate limiting dùng chung."
                )

            statement = insert_statement.values(
                bucket_key=bucket_key,
                request_count=cost,
                expires_at=expires_at,
            ).on_conflict_do_update(
                index_elements=[table.c.bucket_key],
                set_={
                    "request_count": table.c.request_count + cost,
                    "expires_at": expires_at,
                },
            ).returning(table.c.request_count)
            request_count = int(db.execute(statement).scalar_one())
            db.execute(delete(table).where(table.c.expires_at <= now_utc))
            db.commit()

        if request_count <= self.max_requests:
            return 0
        return max(
            1,
            math.ceil(expires_at.replace(tzinfo=timezone.utc).timestamp() - now),
        )

    def retry_after(self, scope: str, key: str) -> int:
        bucket_key, expires_at, now = self._bucket_values(scope, key)
        table = ApiRateLimitBucket.__table__
        with self._session_factory() as db:
            request_count = db.execute(
                select(table.c.request_count).where(table.c.bucket_key == bucket_key)
            ).scalar_one_or_none()
        if request_count is None or int(request_count) < self.max_requests:
            return 0
        return max(
            1,
            math.ceil(expires_at.replace(tzinfo=timezone.utc).timestamp() - now),
        )

    def reset(self, scope: str, key: str) -> None:
        bucket_key, _expires_at, _now = self._bucket_values(scope, key)
        table = ApiRateLimitBucket.__table__
        with self._session_factory() as db:
            db.execute(delete(table).where(table.c.bucket_key == bucket_key))
            db.commit()


heavy_api_rate_limiter = DatabaseRateLimiter(
    settings.heavy_api_rate_limit,
    settings.heavy_api_rate_window_seconds,
)
project_upload_chunk_rate_limiter = DatabaseRateLimiter(
    settings.project_upload_chunk_rate_limit,
    settings.heavy_api_rate_window_seconds,
)


def enforce_heavy_api_rate_limit(scope: str, user_id: int, *, cost: int = 1) -> None:
    retry_after = heavy_api_rate_limiter.consume(
        scope,
        f"user:{int(user_id)}",
        cost=cost,
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Bạn thao tác quá nhanh. Vui lòng thử lại sau.",
            headers={"Retry-After": str(retry_after)},
        )


def enforce_project_upload_chunk_rate_limit(user_id: int) -> None:
    retry_after = project_upload_chunk_rate_limiter.consume(
        "project-upload-chunk",
        f"user:{int(user_id)}",
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Tốc độ tải PDF đang quá cao. Hệ thống sẽ tự tiếp tục sau ít giây.",
            headers={"Retry-After": str(retry_after)},
        )
