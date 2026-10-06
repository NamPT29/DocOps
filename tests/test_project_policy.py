"""FR-PRJ-01/03: per-project policy with QC-01 defaults (QC-01/02/03/07/08/09)."""

from datetime import timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db, get_utc_now
from server.models import Project, ProjectPolicy, Template, User, UserLoginSession
from server.routers import projects
from server.routers.auth import ALGORITHM, SECRET_KEY
from server.services import project_policy_service as policy_service

DEFAULTS = {
    "error_threshold_percent": 5.0,
    "sample_rate_percent": 30.0,
    "box_deadline_days": 2,
    "organ_code": None,
    "file_notation": None,
    "export_profile": "NN-SIP",
    "bad_paper_factor": 1.3,
    "overtime_factor": 1.2,
    "sunday_factor": 1.4,
    "entry_qc_round2_enabled": True,
}


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'policy.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db):
    admin = User(username="pm", password="x", role="admin")
    staff = User(username="nv1", password="x", role="user")
    template = Template(name="t", filename="t.xlsx", is_active=True)
    db.add_all([admin, staff, template])
    db.flush()
    project = Project(
        name="Bộ Y tế", root_folder_name="byt", template_id=template.id,
        template_name_snapshot="t", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf", created_by_user_id=admin.id,
    )
    db.add(project)
    db.commit()
    return {"db": db, "admin": admin, "staff": staff, "project": project}


def _admin(world):
    return {"id": world["admin"].id, "username": "pm", "role": "admin"}


def _get(world):
    return projects.api_get_project_policy(
        world["project"].id, current_user=_admin(world), db=world["db"],
    )["data"]


def _put(world, **values):
    return projects.api_update_project_policy(
        world["project"].id,
        projects.ProjectPolicyRequest(**values),
        current_user=_admin(world),
        db=world["db"],
    )["data"]


def test_unconfigured_project_uses_qc01_defaults(world):
    policy = _get(world)
    assert policy["qc_version"] == "QC-01 v0.1.1"
    assert policy["values"] == DEFAULTS
    assert set(policy["overrides"].values()) == {None}
    assert policy["updated_by"] is None
    labels = {field["key"]: field["label"] for field in policy["fields"]}
    assert labels["error_threshold_percent"] == "Ngưỡng lỗi của hộp (BR-07)"


def test_admin_overrides_some_fields_and_the_rest_follow_qc01(world):
    policy = _put(
        world,
        error_threshold_percent=4.5,
        organ_code="H05.02.02",
        file_notation="HC",
        export_profile="DANG-HD40",
        sunday_factor="1,5",  # Vietnamese decimal comma is accepted
    )
    assert policy["values"] == {
        **DEFAULTS,
        "error_threshold_percent": 4.5,
        "organ_code": "H05.02.02",
        "file_notation": "HC",
        "export_profile": "DANG-HD40",
        "sunday_factor": 1.5,
    }
    assert policy["overrides"]["sample_rate_percent"] is None
    assert policy["updated_by"] == "pm"
    row = world["db"].get(ProjectPolicy, world["project"].id)
    assert row.error_threshold_percent == Decimal("4.5")
    assert row.box_deadline_days is None


def test_empty_values_return_to_the_defaults(world):
    _put(world, box_deadline_days=3, organ_code="H05")
    policy = _put(world, box_deadline_days=None, organ_code="  ")
    assert policy["values"] == DEFAULTS
    assert set(policy["overrides"].values()) == {None}


def test_a_new_qc01_version_reaches_only_fields_left_empty(world, monkeypatch):
    _put(world, error_threshold_percent=4)
    monkeypatch.setitem(policy_service.QC01_DEFAULTS, "error_threshold_percent", Decimal("3"))
    monkeypatch.setitem(policy_service.QC01_DEFAULTS, "sample_rate_percent", Decimal("25"))

    values = _get(world)["values"]
    assert values["error_threshold_percent"] == 4.0  # set by the admin, kept
    assert values["sample_rate_percent"] == 25.0  # empty, follows QC-01

    effective = policy_service.get_effective_policy(world["db"], project_id=world["project"].id)
    assert effective["sample_rate_percent"] == Decimal("25")
    assert effective["box_deadline_days"] == 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("error_threshold_percent", 100.5, "từ 0 đến 100"),
        ("sample_rate_percent", -1, "từ 0 đến 100"),
        ("error_threshold_percent", 1.234, "tối đa 2 chữ số thập phân"),
        ("error_threshold_percent", "abc", "phải là số"),
        ("box_deadline_days", 0, "từ 1 đến 365"),
        ("box_deadline_days", 366, "từ 1 đến 365"),
        ("box_deadline_days", 2.5, "số ngày nguyên"),
        ("bad_paper_factor", 0, "lớn hơn 0"),
        ("overtime_factor", 13, "không quá 10"),
        ("organ_code", "H05 02", "không khoảng trắng"),
        ("organ_code", "Hà Nội", "chữ không dấu"),
        ("file_notation", "H.C", "_ -"),
        ("export_profile", "ABC", "NN-SIP hoặc DANG-HD40"),
    ],
)
def test_limits_are_checked_field_by_field(world, field, value, message):
    with pytest.raises(HTTPException) as error:
        _put(world, **{field: value})
    assert error.value.status_code == 400
    assert message in error.value.detail
    assert world["db"].get(ProjectPolicy, world["project"].id) is None


def test_range_bounds_are_inclusive(world):
    policy = _put(
        world,
        error_threshold_percent=0,
        sample_rate_percent=100,
        box_deadline_days=365,
        bad_paper_factor=10,
        overtime_factor=0.01,
    )
    assert policy["values"]["sample_rate_percent"] == 100.0
    assert policy["values"]["box_deadline_days"] == 365
    assert policy["values"]["overtime_factor"] == 0.01


def test_unknown_project_and_unknown_fields_are_rejected(world):
    with pytest.raises(HTTPException) as error:
        projects.api_get_project_policy(9999, current_user=_admin(world), db=world["db"])
    assert error.value.status_code == 404
    with pytest.raises(ValueError):
        projects.ProjectPolicyRequest(error_rate=5)


def test_entry_qc_round2_enabled_values(world):
    # true -> true
    policy = _put(world, entry_qc_round2_enabled=True)
    assert policy["values"]["entry_qc_round2_enabled"] is True
    # false -> false
    policy = _put(world, entry_qc_round2_enabled=False)
    assert policy["values"]["entry_qc_round2_enabled"] is False
    # null -> follows QC-01 (True)
    policy = _put(world, entry_qc_round2_enabled=None)
    assert policy["values"]["entry_qc_round2_enabled"] is True
    assert policy["overrides"]["entry_qc_round2_enabled"] is None


def test_full_payload_can_be_saved(world):
    # Send all fields as they would be from the form
    payload = {
        "error_threshold_percent": 3.0,
        "sample_rate_percent": 15.0,
        "box_deadline_days": 1,
        "organ_code": "T123",
        "file_notation": "LT",
        "export_profile": "NN-SIP",
        "bad_paper_factor": 1.1,
        "overtime_factor": 1.5,
        "sunday_factor": 1.2,
        "entry_qc_round2_enabled": False,
    }
    policy = _put(world, **payload)
    assert policy["values"] == payload
    
    with pytest.raises(HTTPException) as error:
        _put(world, entry_qc_round2_enabled="abc")
    assert error.value.status_code == 400
    assert "đúng/sai" in error.value.detail or "đúng/sai (true/false)" in error.value.detail


def test_policy_keys_match_request_model():
    assert set(policy_service.POLICY_KEYS) == set(projects.ProjectPolicyRequest.model_fields.keys())


def test_only_admins_reach_the_policy_api(world):
    db = world["db"]
    app = FastAPI()
    app.include_router(projects.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    def headers(user):
        login = UserLoginSession(
            session_id=f"s-{user.id}", user_id=user.id, browser_id=f"b-{user.id}",
            expires_at=get_utc_now() + timedelta(minutes=10),
        )
        db.add(login)
        db.commit()
        token = jwt.encode({"sub": str(user.id), "sid": login.session_id}, SECRET_KEY, algorithm=ALGORITHM)
        return {"Authorization": f"Bearer {token}"}

    url = f"/api/projects/{world['project'].id}/policy"
    assert client.get(url, headers=headers(world["staff"])).status_code == 403
    admin_headers = headers(world["admin"])
    assert client.put(url, json={"box_deadline_days": 3}, headers=admin_headers).status_code == 200
    assert client.get(url, headers=admin_headers).json()["data"]["values"]["box_deadline_days"] == 3
