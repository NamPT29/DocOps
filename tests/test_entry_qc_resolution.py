import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server.database import Base
from server.models import Project, User, ProjectCase, ProjectMember, ProjectReportUnit, AssignedDocument, ProjectDocumentAsset, Submission, SubmissionQualityAssessment, ProjectPolicy, Template
from server.models_entry_qc import CaseEntryQcResult
from fastapi.testclient import TestClient
from server.main import app
import os
from server.database import get_db
from server.routers.auth import get_current_user, get_admin_user

def override_get_current_user(user):
    return lambda: user

def override_get_admin_user(user):
    def dep():
        if user["role"] != "admin":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Yêu cầu quyền quản trị")
        return user
    return dep

from sqlalchemy.pool import StaticPool
@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:", 
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    
@pytest.fixture
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def mock_data(test_db):
    admin = User(username="admin", role="admin", password="")
    test_db.add(admin)
    reviewer = User(username="reviewer", role="user", password="")
    test_db.add(reviewer)
    scanner = User(username="scanner", role="user", password="")
    test_db.add(scanner)
    reviewer2 = User(username="reviewer2", role="user", password="")
    test_db.add(reviewer2)
    test_db.commit()
    
    t1 = Template(name="T1", filename="t1")
    test_db.add(t1)
    test_db.commit()
    
    p1 = Project(name="P1", root_folder_name="P1", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    p2 = Project(name="P2", root_folder_name="P2", template_id=t1.id, template_name_snapshot="T1", template_filename_snapshot="t1", case_level=1, report_mode="pdf", created_by_user_id=admin.id)
    test_db.add_all([p1, p2])
    test_db.commit()
    
    test_db.add(ProjectPolicy(project_id=p1.id, error_threshold_percent=5))
    test_db.add(ProjectMember(project_id=p1.id, user_id=reviewer.id, member_role="reviewer", is_active=True))
    test_db.add(ProjectMember(project_id=p2.id, user_id=reviewer2.id, member_role="reviewer", is_active=True))
    test_db.commit()
    
    c1 = ProjectCase(project_id=p1.id, case_key="box1", display_name="box1")
    c2 = ProjectCase(project_id=p2.id, case_key="box2", display_name="box2")
    test_db.add_all([c1, c2])
    test_db.commit()
    
    return {
        "admin": {"id": admin.id, "username": "admin", "role": "admin"},
        "reviewer": {"id": reviewer.id, "username": "reviewer", "role": "user"},
        "reviewer2": {"id": reviewer2.id, "username": "reviewer2", "role": "user"},
        "scanner": {"id": scanner.id, "username": "scanner", "role": "user"},
        "p1": p1,
        "p2": p2,
        "c1": c1,
        "c2": c2
    }

def setup_headers(app_overrides, user):
    app_overrides[get_current_user] = override_get_current_user(user)
    app_overrides[get_admin_user] = override_get_admin_user(user)

def make_submission(test_db, project_id, case_id, user_id, total, errors):
    r = test_db.query(ProjectReportUnit).filter_by(case_id=case_id, report_key="r").first()
    if not r:
        r = ProjectReportUnit(project_id=project_id, case_id=case_id, report_key="r", display_name="R")
        test_db.add(r)
        test_db.flush()
    import uuid
    u = str(uuid.uuid4())
    a = AssignedDocument(original_filename="a", uuid_filename=u)
    test_db.add(a)
    test_db.flush()
    d = ProjectDocumentAsset(project_id=project_id, case_id=case_id, report_unit_id=r.id, assigned_document_id=a.id, status="active", relative_path=u, normalized_relative_path=u, original_filename="a", storage_filename=u, byte_size=1, content_sha256="b")
    test_db.add(d)
    test_db.flush()
    s = Submission(assigned_document_id=a.id, created_by_user_id=user_id, status="completed", data_json="{}")
    test_db.add(s)
    test_db.flush()
    sqa = SubmissionQualityAssessment(submission_id=s.id, input_user_id=user_id, visible_field_count=total, changed_field_count=errors, is_error_report=False, baseline_data_json="{}")
    test_db.add(sqa)
    test_db.commit()

def enable_stages(client, project_id):
    client.put(f"/api/projects/{project_id}/workflow", json={"enabled_stages": ["data_entry", "entry_qc", "normalization", "handover"]})

def test_entry_qc_permissions_and_cross_project(client, test_db, mock_data):
    p1, p2, c1, c2 = mock_data["p1"], mock_data["p2"], mock_data["c1"], mock_data["c2"]
    reviewer2 = mock_data["reviewer2"]
    
    setup_headers(app.dependency_overrides, reviewer2)
    
    # reviewer2 is reviewer of p2, but not p1 -> 403 on p1
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    assert res.status_code == 403
    
    # cross project: case2 belongs to p2, but queried under p1 URL -> 404
    setup_headers(app.dependency_overrides, mock_data["admin"])
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c2.id}/entry-qc")
    assert res.status_code == 404
    
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c2.id}/entry-qc/round1")
    assert res.status_code == 404
    
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c2.id}/entry-qc/resolve", json={"reason": "a"})
    assert res.status_code == 404

def test_entry_qc_resolve_validations(client, test_db, mock_data):
    p1, c1, admin, reviewer, scanner = mock_data["p1"], mock_data["c1"], mock_data["admin"], mock_data["reviewer"], mock_data["scanner"]
    setup_headers(app.dependency_overrides, admin)
    enable_stages(client, p1.id)
    
    # not finalized -> 409
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "not_finalized"
    
    # make round 1 passed
    make_submission(test_db, p1.id, c1.id, scanner["id"], 100, 2)
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round1")
    
    # passed -> 409 not failed
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "not_failed"
    
def test_entry_qc_resolve_validations_failed_case(client, test_db, mock_data):
    p1, c1, admin, reviewer, scanner = mock_data["p1"], mock_data["c1"], mock_data["admin"], mock_data["reviewer"], mock_data["scanner"]
    enable_stages(client, p1.id)
    
    make_submission(test_db, p1.id, c1.id, scanner["id"], 100, 10)
    setup_headers(app.dependency_overrides, admin)
    client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round1")
    
    # reviewer (non-admin) -> 403
    setup_headers(app.dependency_overrides, reviewer)
    assert client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"}).status_code == 403
    
    make_submission(test_db, p1.id, c1.id, admin["id"], 100, 0)
    setup_headers(app.dependency_overrides, admin)
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "self_review"
    
    # let's remove admin's submission to continue
    test_db.execute(Submission.__table__.delete().where(Submission.created_by_user_id == admin["id"]))
    test_db.commit()
    
    # empty reason -> 422 by pydantic
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": ""})
    assert res.status_code == 422
    
    # whitespace reason -> 409 reason_required
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "   "})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "reason_required"
    
    # 501 chars -> 422 by pydantic
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "a" * 501})
    assert res.status_code == 422
    
    # success resolve
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 200
    
    # already resolved
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "already_resolved"

def test_entry_qc_gate_passed(client, test_db, mock_data):
    p1, c1, admin, scanner = mock_data["p1"], mock_data["c1"], mock_data["admin"], mock_data["scanner"]
    setup_headers(app.dependency_overrides, admin)
    enable_stages(client, p1.id)
    
    # chưa chốt vòng 1
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_not_finalized"
    
    # get entry-qc -> blocked
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    assert res.json()["data"]["gate"]["blocked"] is True
    assert res.json()["data"]["gate"]["code"] == "entry_qc_not_finalized"
    
    # vòng 1 không đạt
    make_submission(test_db, p1.id, c1.id, scanner["id"], 100, 10)
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round1")
    assert res.status_code == 200
    
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_failed"
    assert "10.0%" in res.json()["detail"]["message"]
    assert "5.0%" in res.json()["detail"]["message"]
    
    # get entry-qc -> blocked failed
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    assert res.json()["data"]["gate"]["blocked"] is True
    assert res.json()["data"]["gate"]["code"] == "entry_qc_failed"
    
    # sau resolve -> passed
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 200
    
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"})
    assert res.status_code == 200
    
    # get entry-qc -> not blocked
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    assert res.json()["data"]["gate"]["blocked"] is False
    
def test_entry_qc_gate_skipped_if_not_enabled(client, test_db, mock_data):
    p1, c1, admin = mock_data["p1"], mock_data["c1"], mock_data["admin"]
    setup_headers(app.dependency_overrides, admin)
    
    # dự án KHÔNG bật entry_qc
    client.put(f"/api/projects/{p1.id}/workflow", json={"enabled_stages": ["data_entry", "normalization", "handover"]})
    
    make_submission(test_db, p1.id, c1.id, mock_data["scanner"]["id"], 100, 2)
    
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"})
    assert res.status_code == 200

def test_entry_qc_gate_blocks_next_available_stage(client, test_db, mock_data):
    p1, c1, admin = mock_data["p1"], mock_data["c1"], mock_data["admin"]
    setup_headers(app.dependency_overrides, admin)
    
    # bật [data_entry, entry_qc, handover] (tắt Chuẩn hóa)
    client.put(f"/api/projects/{p1.id}/workflow", json={"enabled_stages": ["data_entry", "entry_qc", "handover"]})
    
    make_submission(test_db, p1.id, c1.id, mock_data["scanner"]["id"], 100, 2)
    
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/stages/handover/transition", json={"action": "start"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_not_finalized"

def test_entry_qc_snapshot(client, test_db, mock_data):
    p1, c1, admin, scanner = mock_data["p1"], mock_data["c1"], mock_data["admin"], mock_data["scanner"]
    setup_headers(app.dependency_overrides, admin)
    enable_stages(client, p1.id)
    
    make_submission(test_db, p1.id, c1.id, scanner["id"], 100, 10)
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/round1")
    assert res.status_code == 200
    res = client.post(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"})
    assert res.status_code == 200
    
    # change policy
    policy = test_db.query(ProjectPolicy).filter_by(project_id=p1.id).first()
    policy.error_threshold_percent = 50
    test_db.commit()
    
    # GET summary
    res = client.get(f"/api/projects/{p1.id}/workflow/cases/{c1.id}/entry-qc")
    data = res.json()["data"]
    assert data["rounds"][0]["threshold_percent"] == 5.0
    assert data["rounds"][0]["rate_percent"] == 10.0
