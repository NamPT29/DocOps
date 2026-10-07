import pytest
from fastapi.testclient import TestClient

from server.models import (
    Project, ProjectMember, ProjectStage, ProjectStageMember, User, ProjectCase,
    ArrangementDossier, Submission, Template
)
from server.models_scan import CaseScanPackage
from server.models_workflow import CaseStageState
from server.services import scan_ingestion_service

@pytest.fixture(scope="function")
def sqlite_engine(tmp_path):
    from sqlalchemy import create_engine
    db_path = tmp_path / "test.db"
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

@pytest.fixture(scope="function")
def db_session(sqlite_engine):
    from alembic.config import Config
    from alembic import command
    from server.database import SessionLocal

    alembic_cfg = Config("alembic.ini")
    with sqlite_engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    Session = type(SessionLocal)(bind=sqlite_engine)
    db = Session()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        sqlite_engine.dispose()

@pytest.fixture(scope="function")
def client(db_session, tmp_path, monkeypatch):
    from server.main import app
    from server.database import get_db
    from server.routers.auth import get_current_user, get_admin_user
    
    monkeypatch.setattr(scan_ingestion_service, "process_scan_package_background", lambda *a, **k: None)
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(tmp_path))
    
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def setup_data(db_session):
    admin = User(id=1, username="admin", password="", full_name="Admin", role="admin", account_type="staff")
    staff = User(id=2, username="staff", password="", full_name="Staff", role="user", account_type="staff")
    ctv = User(id=3, username="ctv", password="", full_name="CTV", role="user", account_type="ctv")
    staff_not = User(id=4, username="staff_not", password="", full_name="Staff Not", role="user", account_type="staff")
    db_session.add_all([admin, staff, ctv, staff_not])
    
    t = Template(id=1, name="T", filename="t")
    db_session.add(t)

    # Dự án A: có bước scan và entry_qc, staff là thành viên scan, ctv là thành viên scan (nhưng bị chặn)
    pA = Project(id=1, name="A", root_folder_name="A", template_id=1, template_name_snapshot="T", template_filename_snapshot="t", case_level=1, report_mode="pdf", created_by_user_id=1)
    # Dự án B: có bước scan (nhưng staff ko phải thành viên), staff là reviewer
    pB = Project(id=2, name="B", root_folder_name="B", template_id=1, template_name_snapshot="T", template_filename_snapshot="t", case_level=1, report_mode="pdf", created_by_user_id=1)
    # Dự án C: có bước scan, staff ko phân công
    pC = Project(id=3, name="C", root_folder_name="C", template_id=1, template_name_snapshot="T", template_filename_snapshot="t", case_level=1, report_mode="pdf", created_by_user_id=1)
    # Dự án D: ko có quy trình (chưa bật), staff là reviewer
    pD = Project(id=4, name="D", root_folder_name="D", template_id=1, template_name_snapshot="T", template_filename_snapshot="t", case_level=1, report_mode="pdf", created_by_user_id=1)
    
    db_session.add_all([pA, pB, pC, pD])
    db_session.flush()

    db_session.add(ProjectStage(project_id=pA.id, stage_key="scan", position=1, is_enabled=True))
    db_session.add(ProjectStage(project_id=pA.id, stage_key="data_entry", position=2, is_enabled=True))
    db_session.add(ProjectStage(project_id=pA.id, stage_key="entry_qc", position=3, is_enabled=True))
    db_session.add(ProjectStage(project_id=pB.id, stage_key="scan", position=1, is_enabled=True))
    db_session.add(ProjectStage(project_id=pC.id, stage_key="scan", position=1, is_enabled=True))
    
    db_session.add(ProjectStageMember(project_id=pA.id, stage_key="scan", user_id=staff.id, is_active=True))
    db_session.add(ProjectStageMember(project_id=pA.id, stage_key="scan", user_id=ctv.id, is_active=True))
    
    db_session.add(ProjectMember(project_id=pB.id, user_id=staff.id, member_role="reviewer", is_active=True))
    db_session.add(ProjectMember(project_id=pD.id, user_id=staff.id, member_role="reviewer", is_active=True))

    caseA = ProjectCase(id=1, project_id=pA.id, case_key="boxA", display_name="Box A")
    caseB = ProjectCase(id=2, project_id=pB.id, case_key="boxB", display_name="Box B")
    db_session.add_all([caseA, caseB])
    db_session.commit()

    return {
        "admin": admin, "staff": staff, "ctv": ctv, "staff_not": staff_not,
        "pA": pA, "pB": pB, "pC": pC, "pD": pD,
        "caseA": caseA, "caseB": caseB
    }

def get_as(client, user, path):
    from server.routers.auth import get_current_user, get_admin_user
    client.app.dependency_overrides[get_current_user] = lambda: {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "session_id": "test"}
    def _admin():
        if user.role != "admin":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Quản trị viên")
        return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "session_id": "test"}
    client.app.dependency_overrides[get_admin_user] = _admin
    return client.get(path)

def post_as(client, user, path, json):
    from server.routers.auth import get_current_user, get_admin_user
    client.app.dependency_overrides[get_current_user] = lambda: {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "session_id": "test"}
    def _admin():
        if user.role != "admin":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Quản trị viên")
        return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "session_id": "test"}
    client.app.dependency_overrides[get_admin_user] = _admin
    return client.post(path, json=json)

def test_a_staff_my_projects(client, db_session, setup_data):
    staff = setup_data["staff"]
    resp = get_as(client, staff, "/api/workflow/my-projects")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2
    
    proj_a = next(p for p in data if p["project_id"] == setup_data["pA"].id)
    assert proj_a["stages"] == ["scan"]
    assert proj_a["is_reviewer"] is False
    
    proj_b = next(p for p in data if p["project_id"] == setup_data["pB"].id)
    assert proj_b["stages"] == []
    assert proj_b["is_reviewer"] is True

def test_b_inactive_member(client, db_session, setup_data):
    staff = setup_data["staff"]
    
    # Disable staff in pA
    m = db_session.query(ProjectStageMember).filter_by(project_id=setup_data["pA"].id, user_id=staff.id).first()
    m.is_active = False
    db_session.commit()
    
    resp = get_as(client, staff, "/api/workflow/my-projects")
    data = resp.json()["data"]
    # Only pB remains
    assert len(data) == 1
    assert data[0]["project_id"] == setup_data["pB"].id

def test_c_ctv_access(client, db_session, setup_data):
    ctv = setup_data["ctv"]
    
    # my-projects
    resp = get_as(client, ctv, "/api/workflow/my-projects")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 0
    
    # scan-packages POST
    resp = post_as(client, ctv, f"/api/projects/{setup_data['pA'].id}/cases/{setup_data['caseA'].id}/scan-packages", {"folder_path": "test"})
    assert resp.status_code == 403
    
    # scan-packages GET
    resp = get_as(client, ctv, f"/api/projects/{setup_data['pA'].id}/cases/{setup_data['caseA'].id}/scan-packages")
    assert resp.status_code == 403
    
    # server-folders GET
    resp = get_as(client, ctv, "/api/documents/server-folders")
    assert resp.status_code == 403

def test_d_post_scan_packages(client, db_session, setup_data, tmp_path):
    staff = setup_data["staff"]
    staff_not = setup_data["staff_not"]
    pA = setup_data["pA"]
    pB = setup_data["pB"]
    caseA = setup_data["caseA"]
    caseB = setup_data["caseB"]
    
    # staff in pA -> 422 or 404 (not 403)
    resp = post_as(client, staff, f"/api/projects/{pA.id}/cases/{caseA.id}/scan-packages", {"folder_path": "test"})
    assert resp.status_code != 403
    
    # staff in pB -> 403
    resp = post_as(client, staff, f"/api/projects/{pB.id}/cases/{caseB.id}/scan-packages", {"folder_path": "test"})
    assert resp.status_code == 403
    
    # staff_not -> 403
    resp = post_as(client, staff_not, f"/api/projects/{pA.id}/cases/{caseA.id}/scan-packages", {"folder_path": "test"})
    assert resp.status_code == 403

def test_e_get_scan_packages(client, db_session, setup_data):
    # Add staff to scan_qc for pA
    staff = setup_data["staff"]
    db_session.add(ProjectStageMember(project_id=setup_data["pA"].id, stage_key="scan_qc", user_id=staff.id, is_active=True))
    db_session.commit()
    
    resp = get_as(client, staff, f"/api/projects/{setup_data['pA'].id}/cases/{setup_data['caseA'].id}/scan-packages")
    assert resp.status_code == 200
    
    staff_not = setup_data["staff_not"]
    resp = get_as(client, staff_not, f"/api/projects/{setup_data['pA'].id}/cases/{setup_data['caseA'].id}/scan-packages")
    assert resp.status_code == 403

def test_f_my_work_entry_qc(client, db_session, setup_data):
    staff = setup_data["staff"]
    pA = setup_data["pA"]
    caseA = setup_data["caseA"]
    
    # Staff is reviewer in pA
    db_session.add(ProjectMember(project_id=pA.id, user_id=staff.id, member_role="reviewer", is_active=True))
    db_session.commit()
    
    # Mock workflow repository progress so data_entry is DONE
    from unittest import mock
    with mock.patch("server.repositories.workflow_repository.WorkflowRepository.entry_progress_by_case") as mock_progress:
        mock_progress.return_value = {
            caseA.id: {
                "report_total": 1,
                "reports_entered": 1,
                "submissions_total": 1,
                "submissions_under_review": 1,
                "submissions_completed": 0
            }
        }
        
        # Gọi /api/projects/1/workflow/my-work
        resp = get_as(client, staff, f"/api/projects/{pA.id}/workflow/my-work")
        assert resp.status_code == 200
        
        data = resp.json()["data"]
        entry_qc_item = next((c for c in data if c["stage_key"] == "entry_qc"), None)
        assert entry_qc_item is not None
        assert entry_qc_item["gate_code"] == "entry_qc_not_finalized"
        
        # Thêm CaseEntryQcResult vòng 1 đạt -> gate_code == "entry_qc_round2_required"
        from server.models import CaseEntryQcResult
        db_session.add(CaseEntryQcResult(project_id=pA.id, case_id=caseA.id, round=1, passed=True, threshold_percent=20.0, resolution='approved'))
        db_session.commit()
        
        resp = get_as(client, staff, f"/api/projects/{pA.id}/workflow/my-work")
        data = resp.json()["data"]
        entry_qc_item = next((c for c in data if c["stage_key"] == "entry_qc"), None)
        assert entry_qc_item is not None
        assert entry_qc_item["gate_code"] == "entry_qc_round2_required"
        
        # Thêm ProjectPolicy tắt vòng 2 -> không còn mục entry_qc
        from server.models import ProjectPolicy
        db_session.add(ProjectPolicy(project_id=pA.id, entry_qc_round2_enabled=False))
        db_session.commit()
        
        resp = get_as(client, staff, f"/api/projects/{pA.id}/workflow/my-work")
        data = resp.json()["data"]
        entry_qc_item = next((c for c in data if c["stage_key"] == "entry_qc"), None)
        assert entry_qc_item is None
        
        # staff_not gọi my-work -> không có mục entry_qc
        staff_not = setup_data["staff_not"]
        resp = get_as(client, staff_not, f"/api/projects/{pA.id}/workflow/my-work")
        data = resp.json()["data"]
        entry_qc_item = next((c for c in data if c["stage_key"] == "entry_qc"), None)
        assert entry_qc_item is None


def test_g_admin_access(client, db_session, setup_data):
    admin = setup_data["admin"]
    pA = setup_data["pA"]
    caseA = setup_data["caseA"]
    
    assert get_as(client, admin, "/api/workflow/my-projects").status_code == 200
    assert get_as(client, admin, "/api/documents/server-folders").status_code == 200
    assert get_as(client, admin, f"/api/projects/{pA.id}/cases/{caseA.id}/scan-packages").status_code == 200
    assert post_as(client, admin, f"/api/projects/{pA.id}/cases/{caseA.id}/scan-packages", {"folder_path": "test"}).status_code != 403
