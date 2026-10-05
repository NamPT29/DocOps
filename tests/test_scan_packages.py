import pytest
import os
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.main import app
from server.database import Base
from server.models import User, Project, ProjectCase, Template
from server.models_workflow import ProjectStage, CaseStageState, ProjectStageMember
from server.models_scan import CaseScanPackage
from server.routers.auth import get_admin_user, get_current_user
from server.routers.projects import api_create_scan_package, api_list_scan_packages, ScanPackageCreateRequest
from fastapi import BackgroundTasks
from server.repositories.workflow_repository import WorkflowRepository
from server.services.scan_ingestion_service import process_scan_package_background

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


def test_scan_packages_endpoints(database, tmp_path, monkeypatch):
    db = database
    
    # Mock environment variables so resolving paths works off tmp_path
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(tmp_path / "samples_local"))
    
    # Create user
    user = User(username="admin", password="x", full_name="Admin", role="admin")
    db.add(user)
    user2 = User(username="user", password="x", full_name="User", role="user")
    db.add(user2)
    
    t = Template(name="T", filename="t.xlsx")
    db.add(t)
    
    db.commit()
    
    app.dependency_overrides[get_admin_user] = lambda: {"id": user.id, "role": "admin"}
    app.dependency_overrides[get_current_user] = lambda: {"id": user2.id, "role": "user"}
    
    # Setup project
    project = Project(
        name="P1", root_folder_name="P1", template_id=1,
        template_name_snapshot="T", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf",
        created_by_user_id=user.id,
        status="new"
    )
    db.add(project)
    db.commit()
    
    case = ProjectCase(project_id=project.id, case_key="c1", display_name="Hộp 01")
    db.add(case)
    db.commit()
    
    # Let's create actual folders in samples_local for testing
    base_dir = tmp_path / "samples_local" / "P1" / "Người Scan"
    base_dir.mkdir(parents=True, exist_ok=True)
    scan_folder = base_dir / "Hộp 01"
    scan_folder.mkdir(exist_ok=True)
    
    # Write some dummy PDF
    (scan_folder / "1.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
    
    req = ScanPackageCreateRequest(folder_path="P1/Người Scan/Hộp 01", scan_user_name_level=1)
    bg = BackgroundTasks()
    
    # Error: Dự án không bật bước Scan (409)
    with pytest.raises(ValueError, match="Dự án không bật bước Scan"):
        api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)

    db.add(ProjectStage(project_id=project.id, stage_key="scan", position=1, is_enabled=True))
    db.add(CaseStageState(project_id=project.id, case_id=case.id, stage_key="scan", status="pending"))
    db.commit()
    
    # Missing folder
    req.folder_path = "P1/Người Scan/Hộp 02_sai"
    with pytest.raises(Exception):
        api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)
        
    # Folder mismatch (folder doesn't contain Hộp 01)
    req.folder_path = "P1/Người Scan"
    with pytest.raises(ValueError, match="không khớp với hộp"):
        api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)
        
    # Valid submit
    req.folder_path = "P1/Người Scan/Hộp 01"
    res = api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)
    assert res["status"] == "ok"
    
    # Check that case stage is now in_progress
    stage = WorkflowRepository(db).get_state(case.id, "scan")
    assert stage.status == "in_progress"
    assert stage.assigned_user_id is None # Not matched
    
    # Try to submit another processing package -> fails
    with pytest.raises(ValueError, match="đang có một gói scan khác đang xử lý"):
        api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)

    # Run background task
    def session_factory():
        # we can't use db directly as context manager, but we can return a dummy manager that yields db
        import contextlib
        @contextlib.contextmanager
        def _dummy():
            yield db
        return _dummy()

    process_scan_package_background(res["package_id"], session_factory=session_factory)
        
    pkg = db.query(CaseScanPackage).filter_by(id=res["package_id"]).first()
    db.refresh(pkg)
    assert pkg.status == "done"
    
    # Submit again -> OK, in_progress, version=2
    res2 = api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)
    pkg2 = db.query(CaseScanPackage).filter_by(id=res2["package_id"]).first()
    assert pkg2.version == 2
    
    # Test assigned_user_id matching
    db.add(ProjectStageMember(project_id=project.id, stage_key="scan", user_id=user2.id))
    
    # Update user2 name to match the folder "Người Scan"
    user2.full_name = "nguoi scan"
    db.commit()
    
    pkg2.status = "done"
    db.commit()
    
    res3 = api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)
    stage = WorkflowRepository(db).get_state(case.id, "scan")
    db.refresh(stage)
    assert stage.assigned_user_id == user2.id
    
    # List
    pkgs = api_list_scan_packages(project.id, case.id, {"id": user.id, "role": "admin"}, db)
    assert len(pkgs["data"]) == 3
    
    # Check scan already started
    db.add(ProjectStage(project_id=project.id, stage_key="check_scan", position=2, is_enabled=True))
    db.add(CaseStageState(project_id=project.id, case_id=case.id, stage_key="check_scan", status="in_progress"))
    db.commit()
    
    pkg3 = db.query(CaseScanPackage).filter_by(id=res3["package_id"]).first()
    pkg3.status = "done"
    db.commit()
    
    with pytest.raises(ValueError, match="Bước Kiểm tra scan đã bắt đầu"):
        api_create_scan_package(project.id, case.id, req, bg, {"id": user.id, "role": "admin"}, db)

    app.dependency_overrides.clear()
