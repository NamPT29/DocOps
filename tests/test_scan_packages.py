import pytest
import os
import json
import time
import threading
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.main import app, run_startup_maintenance
from server.database import Base, get_db
from server.models import User, Project, ProjectCase, Template
from server.models_workflow import ProjectStage, CaseStageState, ProjectStageMember
from server.models_scan import CaseScanPackage, CaseScanFile
from server.routers.auth import get_admin_user, get_current_user
from server.repositories.workflow_repository import WorkflowRepository
from server.services.scan_ingestion_service import process_scan_package_background, _calculate_a4_equivalent
from server.repositories.scan_repository import get_scan_package

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


def test_403_and_basic(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    # 403: chỉ ghi đè get_current_user, bỏ override get_admin_user
    app.dependency_overrides.pop(get_admin_user)
    app.dependency_overrides[get_current_user] = lambda: {"id": test_data["user"].id, "role": "user"}
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "test"})
    assert res.status_code == 403
    app.dependency_overrides[get_admin_user] = lambda: {"id": test_data["admin"].id, "role": "admin"}


def test_3a_3b_stage_logic(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    scan_dir = test_data["tmp_path"] / "samples_local" / "P1" / "Hộp 01"
    scan_dir.mkdir(parents=True, exist_ok=True)
    
    # 3a: không bật bước Scan
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 01"})
    assert res.status_code == 409
    
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.commit()
    
    # Hộp mới chưa có dòng trạng thái (pending ẩn) -> ok
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 01"})
    assert res.status_code == 200
    
    # 3b: scan_qc in_progress -> 409
    db.add(ProjectStage(project_id=project.id, stage_key="scan_qc", position=2, is_enabled=True))
    db.add(CaseStageState(project_id=project.id, case_id=case.id, stage_key="scan_qc", status="in_progress"))
    db.commit()
    
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 01"})
    assert res.status_code == 409
    assert "Kiểm tra scan đã bắt đầu" in res.json()["detail"]


def test_3e_box_number_matching(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.commit()
    
    base_dir = test_data["tmp_path"] / "samples_local" / "P1"
    (base_dir / "Hộp 11").mkdir(parents=True, exist_ok=True)
    (base_dir / "Hộp 0020").mkdir(parents=True, exist_ok=True)
    (base_dir / "KhongCoSo").mkdir(parents=True, exist_ok=True)
    
    # Hộp 1 vs Hộp 11 -> 409
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 11"})
    assert res.status_code == 409
    
    # Thư mục không có số -> 409
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/KhongCoSo"})
    assert res.status_code == 409
    
    # Hộp 0020 khớp hop-20
    case2 = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-20", display_name="Hộp 20")
    db.add(case2)
    db.commit()
    res = client.post(f"/api/projects/{project.id}/cases/{case2.id}/scan-packages", json={"folder_path": "P1/Hộp 0020"})
    assert res.status_code == 200


def test_3c_3f_3k_scan_user(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    
    user = test_data["user"]
    # 3k: tên có đ/Đ, full_name None
    user.full_name = "Đào Văn Đ"
    db.add(ProjectStageMember(project_id=project.id, stage_key="scan", user_id=user.id))
    db.commit()
    
    base_dir = test_data["tmp_path"] / "samples_local" / "Dao van d" / "Hộp 01"
    base_dir.mkdir(parents=True, exist_ok=True)
    
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "Dao van d/Hộp 01", "scan_user_name_level": 1})
    assert res.status_code == 200
    stage = WorkflowRepository(db).get_state(case.id, "scan")
    assert stage.assigned_user_id == user.id
    
    # 3c: level=0 -> NULL
    case2 = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-2", display_name="Hộp 02")
    db.add(case2)
    db.commit()
    
    base_dir2 = test_data["tmp_path"] / "samples_local" / "Dao van d" / "Hộp 02"
    base_dir2.mkdir(parents=True, exist_ok=True)
    
    res = client.post(f"/api/projects/{project.id}/cases/{case2.id}/scan-packages", json={"folder_path": "Dao van d/Hộp 02", "scan_user_name_level": 0})
    db.expire_all()
    stage2 = WorkflowRepository(db).get_state(case2.id, "scan")
    assert stage2.assigned_user_id is None
    
    # 3f: cha là thư mục gốc -> missing_scan_user
    case3 = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-3", display_name="Hộp 03")
    db.add(case3)
    db.commit()
    
    base_dir3 = test_data["tmp_path"] / "samples_local" / "Hộp 03"
    base_dir3.mkdir(parents=True, exist_ok=True)
    
    res = client.post(f"/api/projects/{project.id}/cases/{case3.id}/scan-packages", json={"folder_path": "Hộp 03", "scan_user_name_level": 1})
    pkg_id = res.json()["package_id"]
    pkg = db.query(CaseScanPackage).get(pkg_id)
    flags = json.loads(pkg.warning_flags) if pkg.warning_flags else []
    assert "missing_scan_user" in flags


def test_3g_qc06_total_a4(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    # A4+A5+A3 -> 4
    # Bảng khổ (điểm) QC-06
    assert _calculate_a4_equivalent(595, 842, 0) == (0, 0, 0, 0, 1, 0) # A4
    assert _calculate_a4_equivalent(420, 595, 0) == (0, 0, 0, 0, 0, 1) # A5
    assert _calculate_a4_equivalent(842, 1190, 0) == (0, 0, 0, 1, 0, 0) # A3
    
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.commit()
    
    scan_dir = test_data["tmp_path"] / "samples_local" / "P1" / "Hộp 01"
    scan_dir.mkdir(parents=True, exist_ok=True)
    
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 01"})
    pkg_id = res.json()["package_id"]
    
    import pypdf
    pdf = pypdf.PdfWriter()
    pdf.add_blank_page(width=595, height=842) # A4
    pdf.add_blank_page(width=420, height=595) # A5
    pdf.add_blank_page(width=842, height=1190) # A3
    with open(scan_dir / "1.pdf", "wb") as f:
        pdf.write(f)
        
    def session_factory():
        import contextlib
        @contextlib.contextmanager
        def _dummy():
            yield db
        return _dummy()
        
    process_scan_package_background(pkg_id, session_factory=session_factory)
    
    db.expire_all()
    pkg = db.query(CaseScanPackage).get(pkg_id)
    assert pkg.status == "done"
    assert pkg.total_pages == 3
    # A5(1) + A4(1) + A3(2)*2 = 6? wait. 
    # A5=1, A4=1, A3=2 -> a4_eq = 1 + 1 + 2*2 = 6?
    # No, A3 is 1 page. 1*2 = 2.
    # Total A4 eq: 1 (A5) + 1 (A4) + 2 (A3) = 4
    assert pkg.total_a4_equivalent == 4


def test_3l_list_api(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.commit()
    
    res = client.get(f"/api/projects/999/cases/{case.id}/scan-packages")
    assert res.status_code == 404
    
    res = client.get(f"/api/projects/{project.id}/cases/{case.id}/scan-packages")
    assert res.status_code == 200
    assert isinstance(res.json()["data"], list)


def test_3i_3j_background_and_startup(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.commit()
    
    scan_dir = test_data["tmp_path"] / "samples_local" / "P1" / "Hộp 01"
    scan_dir.mkdir(parents=True, exist_ok=True)
    
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "P1/Hộp 01"})
    pkg_id = res.json()["package_id"]
    
    (scan_dir / "not_pdf.txt").write_text("Hello")
    (scan_dir / "encrypted.pdf").write_text("Fake PDF")
    
    incomplete_file = scan_dir / "incomplete.pdf"
    incomplete_file.write_bytes(b"start")
    
    # Simulate writing data while process_scan_package_background is running
    def write_more_data():
        time.sleep(1) # wait for the first sample
        with open(incomplete_file, "ab") as f:
            f.write(b"more data")
            
    t = threading.Thread(target=write_more_data)
    t.start()
    
    def session_factory():
        import contextlib
        @contextlib.contextmanager
        def _dummy():
            yield db
        return _dummy()
        
    process_scan_package_background(pkg_id, session_factory=session_factory)
    t.join()
    
    db.expire_all()
    pkg = db.query(CaseScanPackage).get(pkg_id)
    assert pkg.status == "done"
    assert "non_pdf_files" in pkg.warning_flags
    assert "error_files" in pkg.warning_flags
    assert "incomplete_files" in pkg.warning_flags
    
    # 3j dọn gói kẹt khi khởi động
    pkg2 = CaseScanPackage(case_id=case.id, version=2, source_path="x", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg2)
    db.commit()
    
    from server.repositories.scan_repository import delete_stuck_processing_packages
    delete_stuck_processing_packages(db)
    db.expire_all()
    
    assert pkg2.status == "failed"
    assert "Hệ thống bị tắt đột ngột" in pkg2.error_message
