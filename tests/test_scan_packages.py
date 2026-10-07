import contextlib
import json
import threading
import time
from types import SimpleNamespace

import pypdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import server.main as server_main
from server.main import app, run_startup_maintenance
from server.database import Base, get_db
from server.models import User, Project, ProjectCase, Template, ArrangementDossier
from server.models_workflow import CaseStageEvent, ProjectStage, CaseStageState, ProjectStageMember
from server.models_scan import CaseScanPackage, CaseScanFile
from server.routers.auth import get_admin_user, get_current_user
from server.repositories.workflow_repository import WorkflowRepository
from server.repositories.scan_repository import fail_stuck_processing_packages
from server.services import scan_ingestion_service
from server.services.scan_ingestion_service import process_scan_package_background, _calculate_a4_equivalent

client = TestClient(app)

A4 = (595, 842)
A5 = (420, 595)
A3 = (842, 1190)
A2 = (1190, 1684)


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
    app.dependency_overrides[get_current_user] = lambda: {"id": user_admin.id, "role": "admin"}

    yield {"db": db, "project": project, "case": case, "admin": user_admin, "user": user_normal, "tmp_path": tmp_path}

    app.dependency_overrides.clear()


@pytest.fixture()
def no_sleep(monkeypatch):
    """Skip the 2.5 s copy-in-progress wait (not used by the incomplete-file test)."""
    monkeypatch.setattr(scan_ingestion_service.time, "sleep", lambda _seconds: None)


def _same_session(db):
    @contextlib.contextmanager
    def factory():
        yield db
    return factory


def _enable_scan(test_data):
    db = test_data["db"]
    db.add(ProjectStage(project_id=test_data["project"].id, stage_key="scan", position=1, is_enabled=True))
    db.commit()


def _box_dir(test_data, relative="P1/Hộp 01"):
    path = test_data["tmp_path"] / "samples_local" / relative
    path.mkdir(parents=True, exist_ok=True)
    return path


def _submit(test_data, relative="P1/Hộp 01", case=None, **body):
    case = case or test_data["case"]
    return client.post(
        f"/api/projects/{test_data['project'].id}/cases/{case.id}/scan-packages",
        json={"folder_path": relative, **body},
    )


def _write_pdf(path, pages, *, rotate=None):
    writer = pypdf.PdfWriter()
    for width, height in pages:
        page = writer.add_blank_page(width=width, height=height)
        if rotate:
            page.rotate(rotate)
    with open(path, "wb") as handle:
        writer.write(handle)


def _process(db, package_id):
    process_scan_package_background(package_id, session_factory=_same_session(db))
    db.expire_all()
    return db.get(CaseScanPackage, package_id)


def test_403_and_basic(test_data):
    project = test_data["project"]
    case = test_data["case"]

    # 403: change get_current_user to normal user
    app.dependency_overrides[get_current_user] = lambda: {"id": test_data["user"].id, "role": "user"}
    res = client.post(f"/api/projects/{project.id}/cases/{case.id}/scan-packages", json={"folder_path": "test"})
    assert res.status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {"id": test_data["admin"].id, "role": "admin"}


def test_3a_3b_stage_logic(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    _box_dir(test_data)

    # 3a: không bật bước Scan
    res = _submit(test_data)
    assert res.status_code == 409

    _enable_scan(test_data)

    # Hộp mới chưa có dòng trạng thái (pending ẩn) -> ok
    res = _submit(test_data)
    assert res.status_code == 200

    # 3b: scan_qc in_progress -> 409
    db.add(ProjectStage(project_id=project.id, stage_key="scan_qc", position=2, is_enabled=True))
    db.add(CaseStageState(project_id=project.id, case_id=case.id, stage_key="scan_qc", status="in_progress"))
    db.commit()

    res = _submit(test_data)
    assert res.status_code == 409
    assert "Kiểm tra scan đã bắt đầu" in res.json()["detail"]


def test_3e_box_number_matching(test_data):
    db = test_data["db"]
    project = test_data["project"]
    _enable_scan(test_data)
    for name in ("Hộp 11", "Hộp 0020", "KhongCoSo"):
        _box_dir(test_data, f"P1/{name}")

    # Hộp 1 vs Hộp 11 -> 409
    assert _submit(test_data, "P1/Hộp 11").status_code == 409
    # Thư mục không có số -> 409
    assert _submit(test_data, "P1/KhongCoSo").status_code == 409

    # Hộp 0020 khớp hop-20
    case2 = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-20", display_name="Hộp 20")
    db.add(case2)
    db.commit()
    assert _submit(test_data, "P1/Hộp 0020", case=case2).status_code == 200


def test_hierarchical_case_key_uses_last_component(test_data):
    """case_key 'phong01/0020' → box 20, folder '0020' → 200."""
    db = test_data["db"]
    _enable_scan(test_data)
    case = ProjectCase(project_id=test_data["project"].id, case_key="phong01/0020", display_name="Hộp 20")
    db.add(case)
    db.commit()
    _box_dir(test_data, "P1/0020")
    assert _submit(test_data, "P1/0020", case=case).status_code == 200


def test_hierarchical_case_key_rejects_wrong_folder(test_data):
    """case_key 'phong01/0020' must NOT match folder '01' or '0021'."""
    db = test_data["db"]
    _enable_scan(test_data)
    case = ProjectCase(project_id=test_data["project"].id, case_key="phong01/0020", display_name="Hộp 20")
    db.add(case)
    db.commit()
    _box_dir(test_data, "P1/01")
    _box_dir(test_data, "P1/0021")
    assert _submit(test_data, "P1/01", case=case).status_code == 409
    assert _submit(test_data, "P1/0021", case=case).status_code == 409


def test_placeholder_case_key_accepts_matching_folder(test_data):
    """case_key '::muc-luc/hop-20' still matches folder 'Hộp 0020'."""
    db = test_data["db"]
    _enable_scan(test_data)
    case = ProjectCase(project_id=test_data["project"].id, case_key="::muc-luc/hop-20", display_name="Hộp 20")
    db.add(case)
    db.commit()
    _box_dir(test_data, "P1/Hộp 0020")
    assert _submit(test_data, "P1/Hộp 0020", case=case).status_code == 200


def test_3c_3f_3k_scan_user(test_data):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    _enable_scan(test_data)

    user = test_data["user"]
    # 3k: tên có đ/Đ
    user.full_name = "Đào Văn Đ"
    db.add(ProjectStageMember(project_id=project.id, stage_key="scan", user_id=user.id))
    db.commit()

    _box_dir(test_data, "Dao van d/Hộp 01")
    res = _submit(test_data, "Dao van d/Hộp 01", scan_user_name_level=1)
    assert res.status_code == 200
    stage = WorkflowRepository(db).get_state(case.id, "scan")
    assert stage.assigned_user_id == user.id

    # 3c: level=0 -> NULL
    case2 = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-2", display_name="Hộp 02")
    db.add(case2)
    db.commit()
    _box_dir(test_data, "Dao van d/Hộp 02")
    _submit(test_data, "Dao van d/Hộp 02", case=case2, scan_user_name_level=0)
    db.expire_all()
    assert WorkflowRepository(db).get_state(case2.id, "scan").assigned_user_id is None

    # 3f: cha là thư mục gốc -> missing_scan_user
    case3 = ProjectCase(project_id=project.id, case_key="::muc-luc/hop-3", display_name="Hộp 03")
    db.add(case3)
    db.commit()
    _box_dir(test_data, "Hộp 03")
    res = _submit(test_data, "Hộp 03", case=case3, scan_user_name_level=1)
    pkg = db.get(CaseScanPackage, res.json()["package_id"])
    assert "missing_scan_user" in json.loads(pkg.warning_flags)


def test_full_name_none_does_not_crash(test_data, monkeypatch):
    db = test_data["db"]
    user = test_data["user"]
    _enable_scan(test_data)
    db.add(ProjectStageMember(project_id=test_data["project"].id, stage_key="scan", user_id=user.id))
    db.commit()
    monkeypatch.setattr(
        scan_ingestion_service,
        "get_users_by_ids",
        lambda _db, _ids: [SimpleNamespace(id=user.id, full_name=None, username="dao van d")],
    )
    _box_dir(test_data, "Dao van d/Hộp 01")

    res = _submit(test_data, "Dao van d/Hộp 01", scan_user_name_level=1)

    assert res.status_code == 200
    assert WorkflowRepository(db).get_state(test_data["case"].id, "scan").assigned_user_id == user.id


def test_3g_qc06_total_a4(test_data, no_sleep):
    db = test_data["db"]
    assert _calculate_a4_equivalent(*A4, 0) == (0, 0, 0, 0, 1, 0)
    assert _calculate_a4_equivalent(*A5, 0) == (0, 0, 0, 0, 0, 1)
    assert _calculate_a4_equivalent(*A3, 0) == (0, 0, 0, 1, 0, 0)
    _enable_scan(test_data)
    scan_dir = _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]
    _write_pdf(scan_dir / "1.pdf", [A4, A5, A3])

    pkg = _process(db, pkg_id)

    assert pkg.status == "done"
    assert pkg.total_pages == 3
    # A5 (1) + A4 (1) + A3 (2) = 4
    assert pkg.total_a4_equivalent == 4


def test_qc06_ten_percent_bound_and_rotation():
    # A4 area 595 x 842; up to 110 % of it stays A4, above it counts as A3.
    assert _calculate_a4_equivalent(654, 842, 0) == (0, 0, 0, 0, 1, 0)
    assert _calculate_a4_equivalent(655, 842, 0) == (0, 0, 0, 1, 0, 0)
    # A rotated (landscape) A4 page is still A4.
    assert _calculate_a4_equivalent(842, 595, 90) == (0, 0, 0, 0, 1, 0)
    assert _calculate_a4_equivalent(3000, 4000, 0) == (1, 0, 0, 0, 0, 0)  # beyond A0 -> A0


def test_mixed_sizes_and_rotated_pages_sum_to_a4_equivalent(test_data, no_sleep):
    db = test_data["db"]
    _enable_scan(test_data)
    scan_dir = _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]
    # A4 1 + A3 2 + A5 1 + 110 %-exceeding A4 -> A3 2 + beyond A0 -> 16
    _write_pdf(scan_dir / "mixed.pdf", [A4, A3, A5, (655, 842), (3000, 4000)])
    # A2 stored landscape and rotated 90 degrees -> A2 4
    _write_pdf(scan_dir / "rotated.pdf", [(A2[1], A2[0])], rotate=90)

    pkg = _process(db, pkg_id)

    assert pkg.status == "done"
    assert pkg.total_pages == 6
    assert pkg.total_a4_equivalent == 1 + 2 + 1 + 2 + 16 + 4
    rotated = db.query(CaseScanFile).filter_by(package_id=pkg_id, relative_path="rotated.pdf").one()
    assert (rotated.a2_pages, rotated.a4_equivalent) == (1, 4)


def test_new_warning_flags_are_merged_with_submission_flags(test_data, no_sleep):
    db = test_data["db"]
    _enable_scan(test_data)
    case3 = ProjectCase(project_id=test_data["project"].id, case_key="::muc-luc/hop-3", display_name="Hộp 03")
    db.add(case3)
    db.commit()
    scan_dir = _box_dir(test_data, "Hộp 03")
    pkg_id = _submit(test_data, "Hộp 03", case=case3, scan_user_name_level=1).json()["package_id"]
    (scan_dir / "ghi_chu.txt").write_text("không phải PDF", encoding="utf-8")

    pkg = _process(db, pkg_id)

    assert pkg.status == "done"
    assert set(json.loads(pkg.warning_flags)) == {"missing_scan_user", "non_pdf_files"}


def test_truncated_and_encrypted_pdfs_are_recorded_as_file_errors(test_data, no_sleep):
    db = test_data["db"]
    _enable_scan(test_data)
    scan_dir = _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]
    _write_pdf(scan_dir / "good.pdf", [A4])
    _write_pdf(scan_dir / "full.pdf", [A4, A4, A4])
    data = (scan_dir / "full.pdf").read_bytes()
    (scan_dir / "full.pdf").unlink()
    (scan_dir / "cut.pdf").write_bytes(data[: len(data) // 2])
    writer = pypdf.PdfWriter()
    writer.add_blank_page(*A4)
    writer.encrypt("pw", algorithm="RC4-128")
    with open(scan_dir / "locked.pdf", "wb") as handle:
        writer.write(handle)

    pkg = _process(db, pkg_id)

    assert pkg.status == "done"
    assert (pkg.processed_files, pkg.failed_files, pkg.total_pages) == (1, 2, 1)
    files = {f.relative_path: f for f in db.query(CaseScanFile).filter_by(package_id=pkg_id)}
    for name in ("cut.pdf", "locked.pdf"):
        assert files[name].status == "error"
        assert files[name].page_count == -1
        assert files[name].error_message.startswith("Lỗi đọc PDF")
    assert "mã hóa" in files["locked.pdf"].error_message
    assert "error_files" in json.loads(pkg.warning_flags)


def test_missing_pypdf_fails_the_package(test_data, no_sleep, monkeypatch):
    db = test_data["db"]
    _enable_scan(test_data)
    _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]
    monkeypatch.setattr(scan_ingestion_service, "pypdf", None)

    pkg = _process(db, pkg_id)

    assert pkg.status == "failed"
    assert "pypdf" in pkg.error_message
    assert pkg.finished_at is not None


def test_unexpected_error_fails_the_package(test_data, no_sleep, monkeypatch):
    db = test_data["db"]
    _enable_scan(test_data)
    _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]

    def boom(_path):
        raise RuntimeError("ổ đĩa mạng mất kết nối")

    monkeypatch.setattr(scan_ingestion_service, "resolve_server_source_directory", boom)

    pkg = _process(db, pkg_id)

    assert pkg.status == "failed"
    assert "ổ đĩa mạng mất kết nối" in pkg.error_message
    assert pkg.finished_at is not None


def test_database_flush_error_never_leaves_the_package_processing(test_data, no_sleep, monkeypatch):
    db = test_data["db"]
    _enable_scan(test_data)
    scan_dir = _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]
    _write_pdf(scan_dir / "1.pdf", [A4])
    real_create = scan_ingestion_service.create_scan_files

    def invalid_status(session, files):
        for scan_file in files:
            scan_file.status = "khong-hop-le"  # violates ck_case_scan_files_status
        real_create(session, files)

    monkeypatch.setattr(scan_ingestion_service, "create_scan_files", invalid_status)

    pkg = _process(db, pkg_id)

    assert pkg.status == "failed"
    assert pkg.error_message.startswith("Lỗi bất ngờ")
    assert db.query(CaseScanFile).filter_by(package_id=pkg_id).count() == 0


def test_total_files_is_saved_before_files_are_read(test_data, monkeypatch):
    db = test_data["db"]
    _enable_scan(test_data)
    scan_dir = _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]
    for name in ("1.pdf", "2.pdf", "3.pdf"):
        _write_pdf(scan_dir / name, [A4])
    seen = []
    other_sessions = sessionmaker(bind=db.get_bind())

    def look_from_another_session(_seconds):
        with other_sessions() as other:
            pkg = other.get(CaseScanPackage, pkg_id)
            seen.append((pkg.status, pkg.total_files, pkg.processed_files))

    monkeypatch.setattr(scan_ingestion_service.time, "sleep", look_from_another_session)

    pkg = _process(db, pkg_id)

    assert seen == [("processing", 3, 0)]
    assert (pkg.status, pkg.total_files, pkg.processed_files) == ("done", 3, 3)


def test_3l_list_api(test_data):
    project = test_data["project"]
    case = test_data["case"]
    _enable_scan(test_data)

    res = client.get(f"/api/projects/999/cases/{case.id}/scan-packages")
    assert res.status_code == 404

    res = client.get(f"/api/projects/{project.id}/cases/{case.id}/scan-packages")
    assert res.status_code == 200
    assert isinstance(res.json()["data"], list)


def test_box_of_another_existing_project_is_not_found(test_data):
    db = test_data["db"]
    other = Project(
        name="P2", root_folder_name="P2", template_id=1,
        template_name_snapshot="T", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf", created_by_user_id=test_data["admin"].id, status="new",
    )
    db.add(other)
    db.commit()

    res = client.get(f"/api/projects/{other.id}/cases/{test_data['case'].id}/scan-packages")

    assert res.status_code == 404


def test_scan_stage_gate_and_package_versions(test_data):
    db = test_data["db"]
    case = test_data["case"]
    _enable_scan(test_data)
    _box_dir(test_data)

    def scan_state():
        db.expire_all()
        return WorkflowRepository(db).get_state(case.id, "scan").status

    def scan_events():
        return db.query(CaseStageEvent).filter_by(case_id=case.id, stage_key="scan").count()

    def finish(package_id):
        db.get(CaseScanPackage, package_id).status = "done"
        db.commit()

    # pending -> START, version 1
    first = _submit(test_data)
    assert first.status_code == 200
    assert scan_state() == "in_progress" and scan_events() == 1

    # A package still processing blocks the next one.
    busy = _submit(test_data)
    assert busy.status_code == 409 and "đang xử lý" in busy.json()["detail"]

    # in_progress -> only a new package, no stage transition
    finish(first.json()["package_id"])
    second = _submit(test_data)
    assert second.status_code == 200
    assert scan_state() == "in_progress" and scan_events() == 1

    # rejected -> START again
    finish(second.json()["package_id"])
    WorkflowRepository(db).get_state(case.id, "scan").status = "rejected"
    db.commit()
    third = _submit(test_data)
    assert third.status_code == 200
    assert scan_state() == "in_progress" and scan_events() == 2

    versions = [
        p.version for p in db.query(CaseScanPackage).filter_by(case_id=case.id).order_by(CaseScanPackage.id)
    ]
    assert versions == [1, 2, 3]

    # done -> no more packages
    finish(third.json()["package_id"])
    WorkflowRepository(db).get_state(case.id, "scan").status = "done"
    db.commit()
    assert _submit(test_data).status_code == 409


def test_3i_3j_background_and_startup(test_data):
    db = test_data["db"]
    case = test_data["case"]
    _enable_scan(test_data)
    scan_dir = _box_dir(test_data)
    pkg_id = _submit(test_data).json()["package_id"]

    (scan_dir / "not_pdf.txt").write_text("Hello")
    (scan_dir / "encrypted.pdf").write_text("Fake PDF")
    incomplete_file = scan_dir / "incomplete.pdf"
    incomplete_file.write_bytes(b"start")

    # The file grows while the service waits between its two size samples.
    def write_more_data():
        time.sleep(1)
        with open(incomplete_file, "ab") as f:
            f.write(b"more data")

    t = threading.Thread(target=write_more_data)
    t.start()
    pkg = _process(db, pkg_id)
    t.join()

    assert pkg.status == "done"
    assert "non_pdf_files" in pkg.warning_flags
    assert "error_files" in pkg.warning_flags
    assert "incomplete_files" in pkg.warning_flags

    # 3j: packages left 'processing' by a stopped server become 'failed'
    pkg2 = CaseScanPackage(case_id=case.id, version=2, source_path="x", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg2)
    db.commit()

    fail_stuck_processing_packages(db)
    db.commit()
    db.expire_all()

    assert pkg2.status == "failed"
    assert "Hệ thống bị tắt đột ngột" in pkg2.error_message
    assert pkg2.finished_at is not None


def test_startup_maintenance_fails_stuck_packages(test_data, monkeypatch):
    db = test_data["db"]
    stuck = CaseScanPackage(
        case_id=test_data["case"].id, version=1, source_path="x", status="processing",
        submitted_by_user_id=test_data["user"].id,
    )
    db.add(stuck)
    db.commit()
    nothing = {"cleaned": 0, "skipped": 0, "errors": 0}
    monkeypatch.setattr(server_main, "migration_state", lambda _engine: SimpleNamespace(ready=True))
    monkeypatch.setattr(server_main, "SessionLocal", sessionmaker(bind=db.get_bind()))
    # Keep the other startup jobs away from the real storage and database.
    monkeypatch.setattr(server_main, "cleanup_stale_export_jobs", lambda: nothing)
    monkeypatch.setattr(server_main, "cleanup_stale_project_uploads", lambda _db: nothing)

    run_startup_maintenance()

    db.expire_all()
    assert stuck.status == "failed"
    assert stuck.finished_at is not None

def test_scan_package_match_perfect_and_get(test_data, tmp_path):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    dossier = ArrangementDossier(
        project_id=project.id, case_id=case.id, box_number=1, dossier_number=12, dossier_suffix="",
        fonds_code="F1", fonds_name="F1", catalog_number="1", title="T1", start_date="01/01/2000",
        end_date="31/12/2000", start_year=2000, maintenance_code="V", sheet_count=10, source_row=1
    )
    db.add(dossier)
    db.commit()

    folder1 = _box_dir(test_data, "PKG1/12")
    _write_pdf(folder1 / "file.pdf", [(210, 297)])
    
    pkg1 = CaseScanPackage(case_id=case.id, version=1, source_path="PKG1", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg1)
    db.commit()
    
    process_scan_package_background(pkg1.id, session_factory=sessionmaker(bind=db.get_bind()))
    db.refresh(pkg1)
    
    assert pkg1.status == "done"
    assert pkg1.match_status == "matched"
    assert "catalog_match_error" not in (pkg1.warning_flags or "")
    
    res = client.get(f"/api/projects/{project.id}/cases/{case.id}/scan-packages")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data[0]["id"] == pkg1.id
    assert data[0]["match_status"] == "matched"
    assert data[0]["match_summary"]["matched"] == ["12"]

def test_scan_package_match_mismatch(test_data, tmp_path):
    db = test_data["db"]
    project = test_data["project"]
    case = test_data["case"]
    
    dossier = ArrangementDossier(
        project_id=project.id, case_id=case.id, box_number=1, dossier_number=12, dossier_suffix="",
        fonds_code="F1", fonds_name="F1", catalog_number="1", title="T1", start_date="01/01/2000",
        end_date="31/12/2000", start_year=2000, maintenance_code="V", sheet_count=10, source_row=1
    )
    removed = ArrangementDossier(
        project_id=project.id, case_id=case.id, box_number=1, dossier_number=99, dossier_suffix="",
        fonds_code="F1", fonds_name="F1", catalog_number="1", title="T1", start_date="01/01/2000",
        end_date="31/12/2000", start_year=2000, maintenance_code="V", sheet_count=10, source_row=2,
        missing_from_import_id=1
    )
    db.add_all([dossier, removed])
    db.commit()

    folder2 = _box_dir(test_data, "PKG2/99")
    _write_pdf(folder2 / "file.pdf", [(210, 297)])
    
    pkg2 = CaseScanPackage(case_id=case.id, version=2, source_path="PKG2", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg2)
    db.commit()
    
    process_scan_package_background(pkg2.id, session_factory=sessionmaker(bind=db.get_bind()))
    db.refresh(pkg2)
    
    assert pkg2.match_status == "mismatch"
    summary = json.loads(pkg2.match_summary)
    assert summary["missing"] == ["12"]
    assert summary["removed_from_catalog"] == ["99"]

def test_scan_package_match_no_catalog(test_data, tmp_path):
    db = test_data["db"]
    case = test_data["case"]
    
    pkg3 = CaseScanPackage(case_id=case.id, version=3, source_path="PKG3", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg3)
    db.commit()
    
    folder = _box_dir(test_data, "PKG3/1")
    _write_pdf(folder / "file.pdf", [(210, 297)])
    
    process_scan_package_background(pkg3.id, session_factory=sessionmaker(bind=db.get_bind()))
    db.refresh(pkg3)
    assert pkg3.match_status == "no_catalog"

def test_scan_package_match_error_does_not_fail_package(test_data, tmp_path, monkeypatch):
    db = test_data["db"]
    case = test_data["case"]
    
    pkg4 = CaseScanPackage(case_id=case.id, version=4, source_path="PKG4", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg4)
    db.commit()
    
    folder = _box_dir(test_data, "PKG4/1")
    _write_pdf(folder / "file.pdf", [(210, 297)])
    
    def raise_error(*args, **kwargs):
        raise ValueError("Match error")
        
    monkeypatch.setattr(scan_ingestion_service, "match_scan_files_to_catalog", raise_error)
    process_scan_package_background(pkg4.id, session_factory=sessionmaker(bind=db.get_bind()))
    db.refresh(pkg4)
    
    assert pkg4.status == "done"
    assert pkg4.match_status is None
    assert "catalog_match_error" in (pkg4.warning_flags or "")

def test_scan_package_failed_no_match(test_data, tmp_path, monkeypatch):
    db = test_data["db"]
    case = test_data["case"]
    
    pkg5 = CaseScanPackage(case_id=case.id, version=5, source_path="PKG5", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg5)
    db.commit()
    
    def raise_error(*args, **kwargs):
        raise ValueError("Simulated logic error")
        
    monkeypatch.setattr(scan_ingestion_service, "resolve_server_source_directory", raise_error)
    
    folder = _box_dir(test_data, "PKG5/1")
    _write_pdf(folder / "file.pdf", [(210, 297)])
    
    process_scan_package_background(pkg5.id, session_factory=sessionmaker(bind=db.get_bind()))
    db.refresh(pkg5)
    
    assert pkg5.status == "failed"
    assert pkg5.match_status is None
    assert "Simulated logic error" in pkg5.error_message

def test_scan_package_no_status_gap_during_match(test_data, monkeypatch):
    db = test_data["db"]
    case = test_data["case"]
    
    pkg = CaseScanPackage(case_id=case.id, version=6, source_path="PKG6", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg)
    db.commit()
    
    folder = _box_dir(test_data, "PKG6/1")
    _write_pdf(folder / "file.pdf", [(210, 297)])
    
    SessionFactory = sessionmaker(bind=db.get_bind())
    
    def patched_match(*args, **kwargs):
        with SessionFactory() as db2:
            current_pkg = db2.query(CaseScanPackage).filter_by(id=pkg.id).first()
            assert current_pkg.status == "processing", "Package should still be processing during match calculation"
        return {"match_status": "matched", "summary": json.dumps({"matched": ["1"]})}
        
    monkeypatch.setattr(scan_ingestion_service, "match_scan_files_to_catalog", patched_match)
    process_scan_package_background(pkg.id, session_factory=SessionFactory)
    
    db.refresh(pkg)
    assert pkg.status == "done"
    assert pkg.match_status == "matched"

def test_scan_package_rollback_preserves_files(test_data, monkeypatch):
    db = test_data["db"]
    case = test_data["case"]
    
    pkg = CaseScanPackage(case_id=case.id, version=7, source_path="PKG7", status="processing", submitted_by_user_id=test_data["user"].id)
    db.add(pkg)
    db.commit()
    
    folder = _box_dir(test_data, "PKG7/1")
    _write_pdf(folder / "file.pdf", [(210, 297)])
    for i in range(8):
        (folder / f"file_{i}.txt").write_text("hello")
    
    def raise_error(*args, **kwargs):
        raise ValueError("Match error")
        
    monkeypatch.setattr(scan_ingestion_service, "match_scan_files_to_catalog", raise_error)
    process_scan_package_background(pkg.id, session_factory=sessionmaker(bind=db.get_bind()))
    
    db.refresh(pkg)
    assert pkg.status == "done"
    assert pkg.match_status is None
    assert "catalog_match_error" in (pkg.warning_flags or "")
    
    files = db.query(CaseScanFile).filter_by(package_id=pkg.id).all()
    assert len(files) == 9
    assert pkg.total_files == 9
