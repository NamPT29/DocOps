import json
from types import SimpleNamespace

from server.routers import auth
from server.services.login_rate_limit_service import LoginRateLimiter


class MissingUserDb:
    def query(self, model):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return None


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


def test_login_endpoint_returns_429_with_existing_error_contract(monkeypatch):
    limiter = LoginRateLimiter(2, 60, clock=lambda: 100.0)
    monkeypatch.setattr(auth, 'login_rate_limiter', limiter)
    request = SimpleNamespace(client=SimpleNamespace(host='192.0.2.10'))
    credentials = auth.LoginRequest(username='member', password='wrong')

    first = auth.api_login(credentials, request=request, db=MissingUserDb())
    second = auth.api_login(credentials, request=request, db=MissingUserDb())

    assert first == {'status': 'error', 'message': 'Sai tên đăng nhập hoặc mật khẩu'}
    assert second.status_code == 429
    assert second.headers['retry-after'] == '60'
    assert json.loads(second.body) == {
        'status': 'error',
        'message': 'Đăng nhập thất bại quá nhiều lần. Vui lòng thử lại sau.',
    }
