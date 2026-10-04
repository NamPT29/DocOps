"""Nhiệm vụ 1c: lock / unlock accounts with an append-only log."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import User
from server.routers import auth
from server.services import account_policy_service as account_policy
from server.services.auth_session_service import active_session_counts
from server.services.login_rate_limit_service import LoginRateLimiter

PASSWORD = "password-123"
LOCKED = "Tài khoản đã bị khóa. Liên hệ quản trị viên."


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(50, 60))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, username, role="user", **fields):
    user = User(username=username, password=auth.hash_password(PASSWORD), role=role, **fields)
    db.add(user)
    db.commit()
    return user


def _as(user):
    return {"id": user.id, "username": user.username, "role": user.role, "session_id": None}


def _login(db, user, browser="b-1"):
    return auth.api_login(
        auth.LoginRequest(username=user.username, password=PASSWORD, browser_id=browser),
        request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
        response=Response(),
        db=db,
    )


def _lock(db, actor, target, reason="Nghỉ việc"):
    return auth.api_lock_user(
        target.id, auth.LockUserRequest(reason=reason), current_user=_as(actor), db=db,
    )


def _unlock(db, actor, target, reason=None):
    return auth.api_unlock_user(
        target.id, auth.UnlockUserRequest(reason=reason), current_user=_as(actor), db=db,
    )


def _error(call):
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code, error.value.detail


def test_lock_revokes_every_session_and_blocks_sign_in_without_the_reason(db):
    admin = _user(db, "pm", role="admin")
    worker = _user(db, "nv1", max_concurrent_sessions=2)
    token = _login(db, worker, "b-1")["token"]
    _login(db, worker, "b-2")
    assert active_session_counts(db, {worker.id})[worker.id] == 2

    result = _lock(db, admin, worker, reason="Vi phạm bảo mật")

    assert result["revoked_sessions"] == 2
    assert result["user"]["is_locked"] is True
    assert active_session_counts(db, {worker.id})[worker.id] == 0
    assert _error(lambda: auth.get_current_user(f"Bearer {token}", db=db))[0] == 401
    # The locked person only learns that the account is locked, never why.
    assert _error(lambda: _login(db, worker)) == (403, LOCKED)


def test_unlock_needs_no_reason_and_restores_sign_in(db):
    admin = _user(db, "pm", role="admin")
    worker = _user(db, "nv1")
    _lock(db, admin, worker, reason="Tạm dừng hợp đồng")

    unlocked = _unlock(db, admin, worker)

    assert unlocked["user"]["is_locked"] is False
    assert _login(db, worker)["status"] == "ok"
    events = auth.api_get_user_lock_events(worker.id, current_user=_as(admin), db=db)["data"]
    assert [(e["action"], e["actor"], e["reason"]) for e in events] == [
        ("unlock", "pm", None),
        ("lock", "pm", "Tạm dừng hợp đồng"),
    ]
    assert events[0]["created_at"].endswith("+00:00")


def test_lock_needs_a_reason(db):
    admin = _user(db, "pm", role="admin")
    worker = _user(db, "nv1")
    assert _error(lambda: _lock(db, admin, worker, reason="   ")) == (
        400, "Cần nêu lý do khóa tài khoản.",
    )
    with pytest.raises(ValidationError):
        auth.LockUserRequest()


def test_admin_cannot_lock_themselves(db):
    admin = _user(db, "pm", role="admin")
    _user(db, "pm2", role="admin")
    assert _error(lambda: _lock(db, admin, admin))[0] == 409


def test_admin_may_lock_another_admin_but_never_the_last_active_one(db):
    first = _user(db, "pm", role="admin")
    second = _user(db, "pm2", role="admin")
    _lock(db, first, second)
    assert db.get(User, second.id).is_locked is True

    # A stale admin session (the first admin locked meanwhile) must not be
    # able to lock the only admin left active.
    first.is_locked = True
    second.is_locked = False
    db.commit()
    status, detail = _error(lambda: _lock(db, first, second))
    assert status == 409 and "Admin cuối cùng" in detail
    assert db.get(User, second.id).is_locked is False


def test_double_lock_and_unlock_of_an_unlocked_account_are_refused(db):
    admin = _user(db, "pm", role="admin")
    worker = _user(db, "nv1")
    assert _error(lambda: _unlock(db, admin, worker))[0] == 409
    _lock(db, admin, worker)
    assert _error(lambda: _lock(db, admin, worker))[0] == 409


def test_lock_wins_over_ctv_expiry_message(db):
    admin = _user(db, "pm", role="admin")
    ctv = _user(db, "ctv1", account_type="ctv", expires_on=date(2020, 1, 1))
    _lock(db, admin, ctv)
    assert _error(lambda: _login(db, ctv)) == (403, LOCKED)
    assert account_policy.access_block_message(
        SimpleNamespace(role="user", account_type="ctv", expires_on=date.today() + timedelta(days=1)),
    ) is None


def test_lock_history_blocks_deleting_the_account(db):
    admin = _user(db, "pm", role="admin")
    worker = _user(db, "nv1")
    _lock(db, admin, worker)
    _unlock(db, admin, worker)
    status, detail = _error(
        lambda: auth.api_delete_user(worker.id, current_user=_as(admin), db=db)
    )
    assert status == 409 and "nhật ký khóa tài khoản" in detail
