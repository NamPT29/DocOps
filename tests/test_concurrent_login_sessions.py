from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import User, UserLoginSession
from server.routers import auth
from server.services import auth_session_service
from server.services.auth_session_service import active_session_counts
from server.services.login_rate_limit_service import LoginRateLimiter


@pytest.fixture()
def auth_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def _login(db, *, browser_id: str):
    return auth.api_login(
        auth.LoginRequest(
            username="employee",
            password="employee-password",
            browser_id=browser_id,
        ),
        request=_request(),
        response=Response(),
        db=db,
    )


def test_login_enforces_admin_configured_browser_limit(auth_db, monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    user = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
        max_concurrent_sessions=2,
    )
    auth_db.add(user)
    auth_db.commit()

    first = _login(auth_db, browser_id="browser-a")
    second = _login(auth_db, browser_id="browser-b")

    assert first["status"] == second["status"] == "ok"
    assert active_session_counts(auth_db, {user.id})[user.id] == 2

    with pytest.raises(HTTPException) as blocked:
        _login(auth_db, browser_id="browser-c")

    assert blocked.value.status_code == 409
    assert "đủ 2 trình duyệt" in blocked.value.detail


def test_relogin_same_browser_replaces_old_token_without_using_new_slot(
    auth_db,
    monkeypatch,
):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    user = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
        max_concurrent_sessions=1,
    )
    auth_db.add(user)
    auth_db.commit()

    first = _login(auth_db, browser_id="browser-a")
    second = _login(auth_db, browser_id="browser-a")
    first_sid = jwt.decode(
        first["token"], auth.SECRET_KEY, algorithms=[auth.ALGORITHM]
    )["sid"]
    second_sid = jwt.decode(
        second["token"], auth.SECRET_KEY, algorithms=[auth.ALGORITHM]
    )["sid"]

    assert first_sid != second_sid
    assert active_session_counts(auth_db, {user.id})[user.id] == 1
    with pytest.raises(HTTPException, match="Phiên đăng nhập không còn hiệu lực"):
        auth.get_current_user(f"Bearer {first['token']}", db=auth_db)
    assert auth.get_current_user(f"Bearer {second['token']}", db=auth_db)["id"] == user.id


def test_admin_can_reduce_limit_and_release_employee_sessions(auth_db, monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    admin = User(
        username="admin-test",
        password=auth.hash_password("admin-password"),
        role="admin",
    )
    employee = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
        max_concurrent_sessions=2,
    )
    auth_db.add_all([admin, employee])
    auth_db.commit()
    _login(auth_db, browser_id="browser-a")
    _login(auth_db, browser_id="browser-b")
    current_admin = {"id": admin.id, "username": admin.username, "role": "admin"}

    updated = auth.api_update_user_profile(
        employee.id,
        auth.UpdateUserProfileRequest(
            full_name="Employee",
            phone_number=None,
            max_concurrent_sessions=1,
        ),
        current_user=current_admin,
        db=auth_db,
    )

    assert updated["revoked_sessions"] == 1
    assert updated["user"]["active_session_count"] == 1
    released = auth.api_revoke_user_sessions(
        employee.id,
        current_user=current_admin,
        db=auth_db,
    )
    assert released == {"status": "ok", "revoked_sessions": 1}
    assert active_session_counts(auth_db, {employee.id})[employee.id] == 0


def test_logout_revokes_only_the_current_browser_session(auth_db, monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    user = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
        max_concurrent_sessions=2,
    )
    auth_db.add(user)
    auth_db.commit()
    first = _login(auth_db, browser_id="browser-a")
    _login(auth_db, browser_id="browser-b")
    current = auth.get_current_user(f"Bearer {first['token']}", db=auth_db)

    assert auth.api_logout(current_user=current, db=auth_db) == {"status": "ok"}
    assert active_session_counts(auth_db, {user.id})[user.id] == 1
    with pytest.raises(HTTPException, match="Phiên đăng nhập không còn hiệu lực"):
        auth.get_current_user(f"Bearer {first['token']}", db=auth_db)


def test_idle_session_is_excluded_and_revoked(auth_db, monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    user = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
    )
    auth_db.add(user)
    auth_db.commit()
    login = _login(auth_db, browser_id="browser-a")
    login_session = auth_db.query(UserLoginSession).one()
    expired_now = login_session.last_activity_at + auth.timedelta(minutes=31)
    monkeypatch.setattr(auth_session_service, "get_utc_now", lambda: expired_now)

    assert active_session_counts(auth_db, {user.id})[user.id] == 0
    with pytest.raises(HTTPException, match="Phiên đăng nhập không còn hiệu lực"):
        auth.get_current_user(f"Bearer {login['token']}", db=auth_db)
    assert auth_db.query(UserLoginSession).count() == 0


def test_close_request_has_grace_and_heartbeat_cancels_it(auth_db, monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    user = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
    )
    auth_db.add(user)
    auth_db.commit()
    login = _login(auth_db, browser_id="browser-a")
    current = auth.get_current_user(f"Bearer {login['token']}", db=auth_db)

    closing = auth.api_mark_session_closing(current_user=current, db=auth_db)
    assert closing["status"] == "closing"
    login_session = auth_db.query(UserLoginSession).one()
    assert login_session.close_requested_at is not None
    assert active_session_counts(auth_db, {user.id})[user.id] == 1

    heartbeat_now = login_session.last_activity_at + auth.timedelta(seconds=61)
    monkeypatch.setattr(auth_session_service, "get_utc_now", lambda: heartbeat_now)
    heartbeat = auth.api_session_heartbeat(
        auth.SessionHeartbeatRequest(user_active=True),
        current_user=current,
        db=auth_db,
    )
    assert heartbeat["status"] == "ok"
    auth_db.refresh(login_session)
    assert login_session.close_requested_at is None
    assert login_session.last_activity_at == heartbeat_now


def test_close_request_revokes_session_after_grace(auth_db, monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    user = User(
        username="employee",
        password=auth.hash_password("employee-password"),
        role="user",
    )
    auth_db.add(user)
    auth_db.commit()
    login = _login(auth_db, browser_id="browser-a")
    current = auth.get_current_user(f"Bearer {login['token']}", db=auth_db)
    auth.api_mark_session_closing(current_user=current, db=auth_db)
    login_session = auth_db.query(UserLoginSession).one()
    after_grace = login_session.close_requested_at + auth.timedelta(seconds=31)
    monkeypatch.setattr(auth_session_service, "get_utc_now", lambda: after_grace)

    assert active_session_counts(auth_db, {user.id})[user.id] == 0
    with pytest.raises(HTTPException, match="Phiên đăng nhập không còn hiệu lực"):
        auth.get_current_user(f"Bearer {login['token']}", db=auth_db)
