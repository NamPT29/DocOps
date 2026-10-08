"""Bảng tiến độ dự án (lát D1): GET /api/projects/{pid}/dashboard. Dữ liệu dựng tay, giờ cố định."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.main import app
from server.models import (
    ArrangementDossier,
    ArrangementImport,
    AssignedDocument,
    CaseStageState,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    ProjectStage,
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewHistory,
    Template,
    User,
)
from server.models_scan import CaseScanPackage
from server.routers.auth import get_current_user
from server.services.project_dashboard_service import build_dashboard

NOW = datetime(2026, 10, 8, 3, 0)  # 10:00 ngày 08/10/2026 giờ Việt Nam
ADMIN = {"id": 1, "username": "admin", "full_name": "Quản trị", "role": "admin", "session_id": "s"}
STAFF = {"id": 2, "username": "nhap", "full_name": "Nguyễn Nhập", "role": "user", "session_id": "s"}


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'dashboard.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def dossier(project, case_row, number, **extra):
    return ArrangementDossier(
        project_id=project.id, case_id=case_row.id, box_number=1, dossier_number=number, dossier_suffix="",
        fonds_code="P", fonds_name="Phông", catalog_number="01", title=f"Hồ sơ {number}", start_date="01/01/2020",
        end_date="31/12/2020", start_year=2020, maintenance_code="01", sheet_count=10, source_row=number, **extra,
    )


@pytest.fixture()
def world(db):
    users = {
        "admin": User(username="admin", password="x", role="admin", full_name="Quản trị", account_type="staff"),
        "staff": User(username="nhap", password="x", role="user", full_name="Nguyễn Nhập", account_type="staff"),
        "ctv": User(username="ctv", password="x", role="user", full_name="An CTV", account_type="ctv"),
        "reviewer": User(username="duyet", password="x", role="user", full_name="Bùi Duyệt", account_type="staff"),
        "scanner": User(username="scan", password="x", role="user", full_name="", account_type="staff"),
        "idle": User(username="nghi", password="x", role="user", full_name="Không làm", account_type="staff"),
    }
    template = Template(name="T", filename="t.xlsx")
    db.add_all([*users.values(), template])
    db.flush()
    project = Project(
        name="Bộ Y tế", root_folder_name="Goc", template_id=template.id, template_name_snapshot="T",
        template_filename_snapshot="t.xlsx", case_level=1, report_mode="pdf",
        created_by_user_id=users["admin"].id, status="ongoing",
    )
    db.add(project)
    db.flush()
    for position, key in enumerate(("arrangement", "scan", "scan_qc", "data_entry", "entry_qc", "normalization", "handover")):
        db.add(ProjectStage(project_id=project.id, stage_key=key, position=position, is_enabled=key != "normalization"))
    cases = [ProjectCase(project_id=project.id, case_key=f"000{i}", display_name=f"000{i}") for i in range(1, 5)]
    db.add_all(cases)
    db.flush()
    c1, c2, c3, c4 = cases

    def state(case_row, stage_key, status):
        db.add(CaseStageState(project_id=project.id, case_id=case_row.id, stage_key=stage_key, status=status))

    state(c1, "arrangement", "done"); state(c2, "arrangement", "done")
    state(c3, "arrangement", "in_progress"); state(c4, "arrangement", "rejected")
    state(c1, "scan", "done"); state(c2, "scan", "in_progress")
    state(c1, "scan_qc", "done")

    later_import = ArrangementImport(project_id=project.id, file_name="m2.xlsx", file_sha256="1" * 64)
    db.add(later_import)
    db.flush()
    db.add_all([dossier(project, c1, n) for n in (1, 2, 3)])
    db.add(dossier(project, c1, 4, missing_from_import_id=later_import.id))  # đã bị bỏ khỏi mục lục
    db.add_all([dossier(project, c2, n) for n in (5, 6)])
    db.add_all([dossier(project, c3, n) for n in (7, 8, 9, 10, 11)])

    def package(case_row, version, status, a4, finished_at, scanner=users["scanner"]):
        db.add(CaseScanPackage(
            case_id=case_row.id, version=version, submitted_by_user_id=users["admin"].id,
            scanned_by_user_id=scanner.id if scanner else None, source_path="x", total_a4_equivalent=a4,
            status=status, started_at=finished_at, finished_at=finished_at,
        ))

    package(c1, 1, "done", 100, datetime(2026, 9, 28, 2, 0))
    package(c1, 2, "done", 120, datetime(2026, 10, 5, 20, 0))  # 03:00 ngày 06/10 giờ VN
    package(c1, 3, "failed", 999, datetime(2026, 10, 7, 2, 0))
    package(c2, 1, "done", 50, datetime(2026, 10, 8, 0, 0))
    package(c3, 1, "done", 7, datetime(2026, 10, 8, 1, 0), scanner=None)
    db.flush()

    report = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="0001", display_name="0001")
    report2 = ProjectReportUnit(project_id=project.id, case_id=c2.id, report_key="0002", display_name="0002")
    db.add_all([report, report2])
    db.flush()
    submissions = {}

    def asset(case_row, unit, path, status=None, *, created_by=users["staff"], created_at=None, asset_status="active"):
        document = AssignedDocument(original_filename=path, uuid_filename=f"u-{path}-{asset_status}")
        db.add(document)
        db.flush()
        if status:
            submission = Submission(
                template_id=template.id, assigned_document_id=document.id, data_json="{}", status=status,
                created_by_user_id=created_by.id, created_at=created_at or datetime(2026, 9, 1),
            )
            db.add(submission)
            db.flush()
            submissions[path] = submission
        db.add(ProjectDocumentAsset(
            project_id=project.id, case_id=case_row.id, report_unit_id=unit.id, assigned_document_id=document.id,
            relative_path=path, normalized_relative_path=path.casefold(), original_filename=path.rsplit("/", 1)[-1],
            storage_filename=f"s-{path.replace('/', '-')}-{asset_status}", content_sha256="0" * 64, byte_size=1,
            status=asset_status,
        ))

    asset(c1, report, "0001/001/BIA.pdf", "completed")
    asset(c1, report, "0001/001/1.pdf", "completed")
    asset(c1, report, "0001/001/2.pdf", "pending_review")
    asset(c1, report, "0001/001/3.pdf", "draft")
    asset(c1, report, "0001/001/4.pdf")
    asset(c2, report2, "0002/001/1.pdf", "completed", created_by=users["ctv"], created_at=datetime(2026, 10, 1, 5, 0))
    asset(c2, report2, "0002/001/9.pdf", "completed", asset_status="replaced")

    def assessment(path, user, created_at):
        db.add(SubmissionQualityAssessment(
            submission_id=submissions[path].id, input_user_id=user.id, baseline_data_json="{}", created_at=created_at,
        ))

    assessment("0001/001/1.pdf", users["staff"], datetime(2026, 10, 6, 17, 30))  # 00:30 ngày 07/10 giờ VN
    assessment("0001/001/2.pdf", users["ctv"], datetime(2026, 10, 8, 1, 0))
    assessment("0001/001/BIA.pdf", users["staff"], datetime(2026, 10, 8, 1, 0))

    def review(path, created_at):
        db.add(SubmissionReviewHistory(
            submission_id=submissions[path].id, event_type="review_confirmed", input_user_id=users["staff"].id,
            reviewer_user_id=users["reviewer"].id, baseline_data_json="{}", reviewer_data_json="{}", created_at=created_at,
        ))
        db.flush()

    review("0001/001/1.pdf", datetime(2026, 10, 7, 2, 0))
    review("0001/001/1.pdf", datetime(2026, 10, 8, 2, 0))  # duyệt lại lần 2: không tính
    review("0002/001/1.pdf", datetime(2026, 9, 20, 2, 0))
    review("0001/001/BIA.pdf", datetime(2026, 10, 8, 2, 0))
    db.commit()
    return project, users


def test_stages_follow_catalog_and_count_box_states(db, world):
    project, _users = world
    stages = build_dashboard(db, project.id, NOW)["stages"]
    assert [stage["key"] for stage in stages] == ["arrangement", "scan", "scan_qc", "data_entry", "entry_qc", "handover"]
    arrangement = stages[0]
    assert (arrangement["boxes_total"], arrangement["boxes_done"], arrangement["boxes_in_progress"],
            arrangement["boxes_rejected"], arrangement["boxes_pending"], arrangement["percent_done"]) == (4, 2, 1, 1, 0, 50.0)
    scan = stages[1]
    assert (scan["boxes_done"], scan["boxes_in_progress"], scan["boxes_pending"], scan["percent_done"]) == (1, 1, 2, 25.0)
    handover = stages[-1]
    assert (handover["boxes_done"], handover["boxes_pending"], handover["volume_done"]) == (0, 4, 0)


def test_volume_done_per_stage_unit(db, world):
    project, _users = world
    stages = {stage["key"]: stage for stage in build_dashboard(db, project.id, NOW)["stages"]}
    assert (stages["arrangement"]["unit"], stages["arrangement"]["volume_done"]) == ("hồ sơ", 5), "3 + 2 hồ sơ, bỏ hồ sơ đã bị bỏ"
    assert (stages["scan"]["unit"], stages["scan"]["volume_done"]) == ("trang A4", 120), "gói done mới nhất; failed và gói cũ không tính"
    assert stages["scan_qc"]["volume_done"] == 120
    assert (stages["data_entry"]["unit"], stages["data_entry"]["volume_done"]) == ("văn bản", 3)
    assert stages["entry_qc"]["volume_done"] == 2


def test_documents_skip_cover_draft_and_replaced_files(db, world):
    project, _users = world
    assert build_dashboard(db, project.id, NOW)["documents"] == {"total": 5, "entered": 3, "completed": 2, "remaining": 3}


def test_daily_uses_vietnam_days_and_first_review_only(db, world):
    project, _users = world
    daily = build_dashboard(db, project.id, NOW)["daily"]
    assert len(daily) == 14
    assert (daily[0]["date"], daily[-1]["date"]) == ("2026-09-25", "2026-10-08")
    by_date = {item["date"]: item for item in daily}
    assert by_date["2026-10-07"]["entered"] == 1, "nộp 17:30 UTC ngày 06/10 là ngày 07/10 giờ VN"
    assert by_date["2026-10-06"]["entered"] == 0
    assert by_date["2026-10-08"]["entered"] == 1, "bìa không tính"
    assert by_date["2026-10-01"]["entered"] == 1, "không có baseline thì lấy ngày tạo hồ sơ"
    assert by_date["2026-10-07"]["approved"] == 1
    assert by_date["2026-10-08"]["approved"] == 0, "duyệt lại lần 2 và duyệt bìa không tính"
    assert by_date["2026-09-28"]["scan_pages"] == 100
    assert by_date["2026-10-06"]["scan_pages"] == 120
    assert by_date["2026-10-07"]["scan_pages"] == 0, "gói failed không tính"
    assert by_date["2026-10-08"]["scan_pages"] == 57
    assert sum(item["entered"] for item in daily) == 3
    assert by_date["2026-09-30"] == {"date": "2026-09-30", "entered": 0, "approved": 0, "scan_pages": 0}


def test_forecast_and_zero_average(db, world):
    project, _users = world
    forecast = build_dashboard(db, project.id, NOW)["forecast"]
    # 7 ngày gần nhất: nhập 2, duyệt 1; còn 3 văn bản -> ceil(3 / (1/7)) = 21 ngày
    assert forecast == {"avg_entered_per_day_7d": 0.3, "avg_approved_per_day_7d": 0.1, "estimated_finish_date": "2026-10-29"}
    later = build_dashboard(db, project.id, datetime(2026, 10, 20, 3, 0))["forecast"]
    assert later == {"avg_entered_per_day_7d": 0.0, "avg_approved_per_day_7d": 0.0, "estimated_finish_date": None}


def test_people_last_seven_days(db, world):
    project, users = world
    people = build_dashboard(db, project.id, NOW)["people"]
    assert people == [
        {"user_id": users["ctv"].id, "name": "An CTV", "entered": 1, "approved": 0, "scan_pages": 0},
        {"user_id": users["reviewer"].id, "name": "Bùi Duyệt", "entered": 0, "approved": 1, "scan_pages": 0},
        {"user_id": users["staff"].id, "name": "Nguyễn Nhập", "entered": 1, "approved": 0, "scan_pages": 0},
        {"user_id": users["scanner"].id, "name": "scan", "entered": 0, "approved": 0, "scan_pages": 170},
    ]


def test_norms_and_project_info(db, world):
    project, _users = world
    data = build_dashboard(db, project.id, NOW)
    assert data["project"] == {"id": project.id, "name": "Bộ Y tế"}
    norms = {norm["code"]: norm for norm in data["norms"]}
    assert norms["SC-A4-1"] == {"code": "SC-A4-1", "label": "Scan A4 giấy thường", "unit": "trang", "per_8h": 3500, "source": "Mẫu"}
    assert norms["NL-1"]["source"] == "Giả định"


def test_api_requires_admin_and_existing_project(db, world):
    project, _users = world
    client = TestClient(app)
    app.dependency_overrides[get_db] = lambda: db
    try:
        app.dependency_overrides[get_current_user] = lambda: STAFF
        assert client.get(f"/api/projects/{project.id}/dashboard").status_code == 403
        app.dependency_overrides[get_current_user] = lambda: ADMIN
        response = client.get(f"/api/projects/{project.id}/dashboard")
        assert response.status_code == 200
        assert response.json()["data"]["documents"]["total"] == 5
        missing = client.get("/api/projects/999/dashboard")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "project_not_found"
    finally:
        app.dependency_overrides.clear()
