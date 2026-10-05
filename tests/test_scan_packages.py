import pytest
import os
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.main import app
from server.database import Base, get_db
from server.models import User, Project, ProjectCase, Template
from server.models_workflow import ProjectStage, CaseStageState, ProjectStageMember
from server.models_scan import CaseScanPackage
from server.routers.auth import get_admin_user, get_current_user
from server.routers.projects import ScanPackageCreateRequest
from server.repositories.workflow_repository import WorkflowRepository
from server.services.scan_ingestion_service import process_scan_package_background, _calculate_a4_equivalent

client = TestClient(app)

@pytest.fixture()
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scan-packages.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def test_data(database, tmp_path, monkeypatch):
    db = database
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(tmp_path / "samples_local"))
    
    user_admin = User(username="admin", password="x", full_name="Admin", role="admin")
    db.add(user_admin)
    user_normal = User(username="user", password="x", full_name="User", role="user")
    db.add(user_normal)
    
    t = Template(name="T", filename="t.xlsx")
    db.add(t)
    db.commit()
    
    project = Project(
        name="P1", root_folder_name="P1", template_id=1,
        template_name_snapshot="T", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf",
        created_by_user_id=user_admin.id,
        status="new"
    )
    db.add(project)
    db.commit()
    
    case = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-1", display_name="Hộp 01")
    db.add(case)
    db.commit()
    
    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", lambda *args, **kwargs: None)
    
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: {"id": user_admin.id, "role": "admin"}
    app.dependency_overrides[get_current_user] = lambda: {"id": user_normal.id, "role": "user"}
    
    yield {"db": db, "project": project, "case": case, "admin": user_admin, "user": user_normal, "tmp_path": tmp_path}
    
    app.dependency_overrides.clear()


def test_auth_and_basic_errors(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    from fastapi import HTTPException
    
    def raise_403():
        raise HTTPException(status_code=403, detail="Forbidden")
        
    app.dependency_overrides[get_admin_user] = raise_403
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "test"})
    assert res.status_code == 403
    app.dependency_overrides[get_admin_user] = lambda: {"id": test_data["admin"].id, "role": "admin"}
    
    # 404 dự án không tồn tại
    res = client.post(f"/api/projects/999/cases/{case.id}/scan-packages", json={"folder_path": "test"})
    assert res.status_code == 404
    
    # 404 hộp không tồn tại
    res = client.post(f"/api/projects/{project.id}/cases/999/scan-packages", json={"folder_path": "test"})
    assert res.status_code == 404
    
    # 400 invalid path
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "../../etc/passwd"})
    assert res.status_code == 400
    
    # 409 dự án không bật bước Scan
    scan_dir = test_data["tmp_path"] / "samples_local" / "P1" / "Hộp 01"
    scan_dir.mkdir(parents=True, exist_ok=True)
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 01"})
    assert res.status_code == 409
    assert "không bật bước Scan" in res.json()["detail"]


def test_box_number_mismatch(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.commit()
    
    base_dir = test_data["tmp_path"] / "samples_local" / "P1" / "Người Scan"
    (base_dir / "Hộp 02").mkdir(parents=True, exist_ok=True)
    
    res = client.post(
        f"/api/projects/{project.id}/cases/{case.id}/scan-packages", 
        json={"folder_path": "P1/Người Scan/Hộp 02"}
    )
    assert res.status_code == 409
    assert "không khớp số hộp" in res.json()["detail"]


def test_qc_06_paper_size():
    # A4 chuẩn
    assert _calculate_a4_equivalent(595, 842, 0) == (0, 0, 0, 0, 1, 0)
    # A5 chuẩn
    assert _calculate_a4_equivalent(420, 595, 0) == (0, 0, 0, 0, 0, 1)
    # Vượt 110% A5 -> thành A4
    assert _calculate_a4_equivalent(420 * 1.06, 595 * 1.06, 0) == (0, 0, 0, 0, 1, 0)
    # Rotate 90
    assert _calculate_a4_equivalent(842, 595, 90) == (0, 0, 0, 0, 1, 0)


def test_submit_and_list_packages(test_data, monkeypatch):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.add(ProjectStageMember(project_id=project.id, stage_key="scan", user_id=test_data["user"].id))
    db.commit()
    
    test_data["user"].full_name = "Người Scan"
    db.commit()
    
    base_dir = test_data["tmp_path"] / "samples_local" / "P1" / "Người Scan"
    scan_folder = base_dir / "Hộp 1" # 1 == 01
    scan_folder.mkdir(parents=True, exist_ok=True)
    
    # Nộp lần 1 -> processing
    res = client.post(
        f"/api/projects/{project.id}/cases/{case.id}/scan-packages", 
        json={"folder_path": "P1/Người Scan/Hộp 1", "scan_user_name_level": 1}
    )
    assert res.status_code == 200
    pkg_id = res.json()["package_id"]
    
    # Kiểm tra assignment (assigned cho user)
    stage = WorkflowRepository(db).get_state(case.id, "scan")
    assert stage.assigned_user_id == test_data["user"].id
    assert stage.status == "in_progress"
    
    # Cố nộp gói nữa khi đang processing -> 409
    res2 = client.post(
        f"/api/projects/{project.id}/cases/{case.id}/scan-packages", 
        json={"folder_path": "P1/Người Scan/Hộp 1"}
    )
    assert res2.status_code == 409
    assert "đang có một gói scan khác" in res2.json()["detail"]
    
    # Giải phóng
    pkg = db.query(CaseScanPackage).get(pkg_id)
    pkg.status = "done"
    db.commit()
    
    # Kiểm tra API list (3l)
    res_list = client.get(f"/api/projects/{project.id}/cases/{case.id}/scan-packages")
    assert res_list.status_code == 200
    assert len(res_list.json()["data"]) == 1
    assert isinstance(res_list.json()["data"][0]["warning_flags"], list)
    
    # Chặn nếu check_scan bắt đầu
    db.add(ProjectStage(project_id=project.id, stage_key="scan_qc", position=2, is_enabled=True))
    db.add(CaseStageState(project_id=project.id, case_id=case.id, stage_key="scan_qc", status="in_progress"))
    db.commit()
    
    res3 = client.post(
        f"/api/projects/{project.id}/cases/{case.id}/scan-packages", 
        json={"folder_path": "P1/Người Scan/Hộp 1"}
    )
    assert res3.status_code == 409
    assert "scan đã bắt đầu" in res3.json()["detail"]
