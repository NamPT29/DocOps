from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import ApiRateLimitBucket
from server.services.api_rate_limit_service import DatabaseRateLimiter


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
