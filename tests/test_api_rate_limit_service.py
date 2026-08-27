import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import ApiRateLimitBucket
from server.routers import submissions
from server.services.api_rate_limit_service import DatabaseRateLimiter, InMemoryRateLimiter


def test_database_rate_limiter_shares_counters_between_workers():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = [100.0]

    first_worker = DatabaseRateLimiter(
        3,
        10,
        session_factory=session_factory,
        clock=lambda: now[0],
    )
    second_worker = DatabaseRateLimiter(
        3,
        10,
        session_factory=session_factory,
        clock=lambda: now[0],
    )

    assert first_worker.consume("project-upload", "user:7") == 0
    assert second_worker.consume("project-upload", "user:7", cost=2) == 0
    assert first_worker.consume("project-upload", "user:7") == 10

    now[0] = 111.0
    assert second_worker.consume("project-upload", "user:7") == 0
    with session_factory() as db:
        assert db.query(ApiRateLimitBucket).count() == 1

    engine.dispose()


def test_database_rate_limiter_keeps_scopes_independent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    limiter = DatabaseRateLimiter(1, 60, session_factory=session_factory, clock=lambda: 30.2)

    assert limiter.consume("upload", "user:9") == 0
    assert limiter.consume("export", "user:9") == 0
    assert limiter.consume("upload", "user:9") == 30

    engine.dispose()


def test_in_memory_rate_limiter_avoids_database_and_resets_each_window():
    now = [100.0]
    limiter = InMemoryRateLimiter(2, 10, clock=lambda: now[0])

    assert limiter.consume("project-upload", "user:7") == 0
    assert limiter.consume("project-upload", "user:7") == 0
    assert limiter.consume("project-upload", "user:7") == 10

    now[0] = 111.0
    assert limiter.consume("project-upload", "user:7") == 0


def test_submission_export_consumes_heavy_rate_limit_before_work(monkeypatch):
    calls = []

    def reject_export(scope, user_id, *, cost):
        calls.append((scope, user_id, cost))
        raise HTTPException(status_code=429, detail="rate limited")

    monkeypatch.setattr(submissions, "enforce_heavy_api_rate_limit", reject_export)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            submissions.api_export(
                template_id=1,
                background_tasks=None,
                current_user={"id": 17, "role": "admin"},
                db=None,
            )
        )

    assert error.value.status_code == 429
    assert calls == [("submission-export", 17, 30)]
