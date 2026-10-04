"""FR-AUT-02/03: account types (Admin, Hành chính, CTV) and CTV expiry."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import Project, ProjectMember, ProjectStageMember, Template, User
from server.routers import auth
from server.services import account_policy_service as account_policy
from server.services.auth_session_service import active_session_counts
from server.services.login_rate_limit_service import LoginRateLimiter
from server.services.project_service import _validate_project_members

TODAY = date(2026, 10, 3)
ADMIN = {"id": 1, "username": "admin", "role": "admin"}


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(auth, "login_rate_limiter", LoginRateLimiter(5, 60))
    monkeypatch.setattr(account_policy, "vietnam_today", lambda: TODAY)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _set_today(monkeypatch, value):
    monkeypatch.setattr(account_policy, "vietnam_today", lambda: value)


def _create(db, username, **fields):
    request = auth.CreateUserRequest(username=username, password="password-123", **fields)
    return auth.api_create_user(request, current_user=ADMIN, db=db)["user"]


def _patch(db, user_id, **fields):
    request = auth.UpdateUserProfileRequest(**fields)
    return auth.api_update_user_profile(user_id, request, current_user=ADMIN, db=db)["user"]


def _login(db, username):
    return auth.api_login(
        auth.LoginRequest(username=username, password="password-123", browser_id="b-1"),
        request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
        response=Response(),
        db=db,
    )


def _status(call):
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code, str(error.value.detail)


def test_account_types_in_user_payload(db):
    staff = _create(db, "staff1")
    ctv = _create(db, "ctv1", account_type="ctv", expires_on=TODAY)
    admin = _create(db, "admin2", role="admin")

    assert (staff["account_type"], staff["expires_on"], staff["is_expired"]) == ("staff", None, False)
    assert (ctv["account_type"], ctv["expires_on"], ctv["is_expired"]) == ("ctv", "2026-10-03", False)
    assert admin["account_type"] == "admin"
    # Staff accounts never keep an expiry date even if one is sent.
    assert _create(db, "staff2", expires_on=TODAY + timedelta(days=9))["expires_on"] is None


def test_ctv_needs_an_expiry_date_that_is_not_in_the_past(db):
    assert _status(lambda: _create(db, "c1", account_type="ctv"))[0] == 400
    code, detail = _status(
        lambda: _create(db, "c2", account_type="ctv", expires_on=TODAY - timedelta(days=1))
    )
    assert code == 400 and "quá khứ" in detail
    assert _status(lambda: _create(db, "a1", role="admin", account_type="ctv"))[0] == 400


def test_ctv_signs_in_through_the_expiry_day_then_is_blocked(db, monkeypatch):
    _create(db, "ctv1", account_type="ctv", expires_on=TODAY)
    assert _login(db, "ctv1")["status"] == "ok"

    _set_today(monkeypatch, TODAY + timedelta(days=1))
    code, detail = _status(lambda: _login(db, "ctv1"))
    assert code == 403
    assert "hết hạn sử dụng từ ngày 03/10/2026" in detail


def test_open_session_of_an_expired_ctv_is_revoked(db, monkeypatch):
    user = _create(db, "ctv1", account_type="ctv", expires_on=TODAY)
    token = _login(db, "ctv1")["token"]
    assert auth.get_current_user(f"Bearer {token}", db=db)["id"] == user["id"]

    _set_today(monkeypatch, TODAY + timedelta(days=1))
    code, detail = _status(lambda: auth.get_current_user(f"Bearer {token}", db=db))
    assert code == 401 and "hết hạn" in detail
    assert active_session_counts(db, {user["id"]})[user["id"]] == 0


def test_patch_rejects_past_dates_but_keeps_an_unchanged_one(db, monkeypatch):
    user = _create(db, "ctv1", account_type="ctv", expires_on=TODAY)
    _set_today(monkeypatch, TODAY + timedelta(days=3))

    # Editing other fields of an expired CTV keeps the stored date.
    assert _patch(db, user["id"], full_name="CTV Một")["expires_on"] == "2026-10-03"
    assert _patch(db, user["id"], full_name="CTV Một", expires_on=TODAY)["is_expired"] is True
    code, detail = _status(
        lambda: _patch(db, user["id"], expires_on=TODAY + timedelta(days=1))
    )
    assert code == 400 and "quá khứ" in detail

    renewed = _patch(db, user["id"], expires_on=TODAY + timedelta(days=30))
    assert (renewed["expires_on"], renewed["is_expired"]) == ("2026-11-02", False)
    assert _login(db, "ctv1")["status"] == "ok"


def test_ctv_back_to_staff_clears_the_expiry(db):
    user = _create(db, "ctv1", account_type="ctv", expires_on=TODAY)
    staff = _patch(db, user["id"], account_type="staff")
    assert (staff["account_type"], staff["expires_on"]) == ("staff", None)


def test_admin_account_type_cannot_change(db):
    admin = _create(db, "admin2", role="admin")
    assert _status(lambda: _patch(db, admin["id"], account_type="staff"))[0] == 400


def _project(db, owner_id):
    template = Template(name="t", filename="t.xlsx", is_active=True)
    db.add(template)
    db.flush()
    project = Project(
        name="Dự án A", root_folder_name="a", template_id=template.id,
        template_name_snapshot="t", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf", created_by_user_id=owner_id,
    )
    db.add(project)
    db.flush()
    return project


def test_switch_to_ctv_is_refused_while_holding_non_ctv_assignments(db):
    staff = _create(db, "staff1")
    project = _project(db, staff["id"])
    reviewer = ProjectMember(
        project_id=project.id, user_id=staff["id"], member_role="reviewer", is_active=True,
    )
    scan = ProjectStageMember(
        project_id=project.id, user_id=staff["id"], stage_key="scan", is_active=True,
    )
    entry = ProjectMember(
        project_id=project.id, user_id=staff["id"], member_role="input", is_active=True,
    )
    db.add_all([reviewer, scan, entry])
    db.commit()

    code, detail = _status(
        lambda: _patch(db, staff["id"], account_type="ctv", expires_on=TODAY)
    )
    assert code == 409
    assert "Người kiểm tra – dự án Dự án A" in detail
    assert "Bước Scan – dự án Dự án A" in detail
    assert db.get(User, staff["id"]).account_type == "staff"  # nothing removed automatically

    reviewer.is_active = False
    scan.is_active = False
    db.commit()
    # Input (nhập liệu) is allowed for CTV, so it does not block the switch.
    assert _patch(db, staff["id"], account_type="ctv", expires_on=TODAY)["account_type"] == "ctv"


def test_ctv_cannot_be_a_project_reviewer(db):
    staff = _create(db, "staff1")
    ctv = _create(db, "ctv1", account_type="ctv", expires_on=TODAY)

    with pytest.raises(HTTPException) as error:
        _validate_project_members(db, [staff["id"]], [ctv["id"]])
    assert error.value.status_code == 400
    assert "CTV không được làm người kiểm tra" in error.value.detail
    assert _validate_project_members(db, [ctv["id"]], [staff["id"]]) == (
        [ctv["id"]], [staff["id"]],
    )


def test_expiry_rule_is_inclusive_and_fails_closed():
    ctv = SimpleNamespace(role="user", account_type="ctv", expires_on=TODAY)
    assert account_policy.is_expired(ctv, today=TODAY) is False
    assert account_policy.is_expired(ctv, today=TODAY + timedelta(days=1)) is True
    # A CTV without a date cannot sign in; staff and admins never expire.
    assert account_policy.is_expired(SimpleNamespace(role="user", account_type="ctv", expires_on=None)) is True
    assert account_policy.is_expired(SimpleNamespace(role="user", account_type="staff", expires_on=None)) is False
    assert account_policy.is_expired(SimpleNamespace(role="admin", account_type="ctv", expires_on=None)) is False
    assert account_policy.CTV_STAGE_KEYS == ("data_entry",)
