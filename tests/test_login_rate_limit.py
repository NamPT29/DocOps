from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.routers import auth
from server.services.login_rate_limit_service import (
    DatabaseLoginRateLimiter,
    LoginRateLimiter,
    RateLimitBackendUnavailable,
    RedisLoginRateLimiter,
)
from server.services.api_rate_limit_service import DatabaseRateLimiter


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def incrby(self, name, amount=1):
        self.values[name] = self.values.get(name, 0) + amount
        return self.values[name]

    def expire(self, name, seconds):
        self.expirations[name] = seconds
        return True

    def ttl(self, name):
        return self.expirations.get(name, -2) if name in self.values else -2

    def get(self, name):
        return self.values.get(name)

    def delete(self, *names):
        for name in names:
            self.values.pop(name, None)
            self.expirations.pop(name, None)
        return 1


class MissingUserDb:
    def query(self, model):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return None


class BrokenRedis:
    def get(self, name):
        raise OSError("network unavailable")


def test_login_rate_limiter_expires_failures_after_window():
    now = [100.0]
    limiter = LoginRateLimiter(2, 10, clock=lambda: now[0])

    assert limiter.record_failure('client:user') == 0
    assert limiter.record_failure('client:user') == 10

    now[0] = 105.0
    assert limiter.retry_after('client:user') == 5

    now[0] = 111.0
    assert limiter.retry_after('client:user') == 0


def test_login_rate_limiter_reset_clears_failures():
    limiter = LoginRateLimiter(2, 10, clock=lambda: 100.0)
    limiter.record_failure('client:user')
    limiter.reset('client:user')

    assert limiter.retry_after('client:user') == 0


def test_redis_login_rate_limiter_shares_failure_counter_and_resets():
    redis = FakeRedis()
    limiter = RedisLoginRateLimiter(2, 60, redis_client=redis)
    second_worker = RedisLoginRateLimiter(2, 60, redis_client=redis)

    assert limiter.record_failure('client:user') == 0
    assert second_worker.record_failure('client:user') == 60
    assert limiter.retry_after('client:user') == 60
    limiter.reset('client:user')
    assert limiter.record_failure('client:user') == 0


def test_redis_login_rate_limiter_fails_closed_when_backend_is_unavailable():
    limiter = RedisLoginRateLimiter(2, 60, redis_client=BrokenRedis())

    with pytest.raises(RateLimitBackendUnavailable):
        limiter.retry_after('client:user')


def test_database_login_rate_limiter_shares_counter_between_workers(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from server.database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'login-rate-limit.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = [100.0]
    first = DatabaseLoginRateLimiter(
        2,
        60,
        limiter=DatabaseRateLimiter(2, 60, session_factory=session_factory, clock=lambda: now[0]),
    )
    second = DatabaseLoginRateLimiter(
        2,
        60,
        limiter=DatabaseRateLimiter(2, 60, session_factory=session_factory, clock=lambda: now[0]),
    )

    assert first.record_failure("client:user") == 0
    assert second.record_failure("client:user") == 20
    assert first.retry_after("client:user") == 20
    second.reset("client:user")
    assert first.retry_after("client:user") == 0
    engine.dispose()


def test_auth_defaults_to_shared_database_login_limiter():
    assert auth.settings.redis_url is None
    assert isinstance(auth._create_login_rate_limiter(), DatabaseLoginRateLimiter)


def test_login_endpoint_returns_429_with_existing_error_contract(monkeypatch):
    limiter = LoginRateLimiter(2, 60, clock=lambda: 100.0)
    monkeypatch.setattr(auth, 'login_rate_limiter', limiter)
    request = SimpleNamespace(client=SimpleNamespace(host='192.0.2.10'))
    credentials = auth.LoginRequest(username='member', password='wrong')

    with pytest.raises(HTTPException) as first:
        auth.api_login(credentials, request=request, db=MissingUserDb())
    with pytest.raises(HTTPException) as second:
        auth.api_login(credentials, request=request, db=MissingUserDb())

    assert first.value.status_code == 401
    assert first.value.detail == 'Sai tên đăng nhập hoặc mật khẩu'
    assert second.value.status_code == 429
    assert second.value.headers['Retry-After'] == '60'
    assert second.value.detail == 'Đăng nhập thất bại quá nhiều lần. Vui lòng thử lại sau.'
