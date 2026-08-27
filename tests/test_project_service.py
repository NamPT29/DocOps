import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Submission,
    SubmissionQualityAssessment,
    Template,
    User,
)
from server.routers.projects import (
    ProjectCreateRequest,
    ProjectStatusUpdateRequest,
    api_create_project,
    api_update_project_status,
    router,
)
from server.services import project_service
from server.services.project_service import create_project, list_projects, update_project_status
from server.services.project_status_service import ensure_project_status_schema


@pytest.fixture()
def database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-service.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    def fake_snapshot(_db, template):
        snapshot_path = tmp_path / f"snapshot-{template.id}.xlsm"
        snapshot_path.write_bytes(b"snapshot")
        return {
            "filename": snapshot_path.name,
            "absolute_path": snapshot_path,
            "config_json": json.dumps({"path_column": "A"}),
            "schema_json": json.dumps([{"category": "Thông tin"}]),
        }

    monkeypatch.setattr(project_service, "_build_template_snapshot", fake_snapshot)
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def seed_users_and_template(database):
    admin = User(username="project-admin", password="hash", role="admin")
    worker = User(username="project-worker", password="hash", role="user")
    reviewer = User(username="project-reviewer", password="hash", role="user")
    template = Template(
        name="Project form",
        filename="project.xlsm",
        is_active=True,
    )
    database.add_all([admin, worker, reviewer, template])
    database.commit()
    return admin, worker, reviewer, template


def create_ready_project(database, **overrides):
    admin, worker, reviewer, template = seed_users_and_template(database)
    values = {
        "name": "",
        "root_folder_name": r"D:\incoming\Du an A",
        "template_id": template.id,
        "start_date": None,
        "end_date": None,
        "case_level": 1,
        "report_mode": "folder_level",
        "report_level": 2,
        "input_user_ids": [worker.id],
        "reviewer_user_ids": [worker.id, reviewer.id],
        "created_by_user_id": admin.id,
    }
    values.update(overrides)
    project = create_project(database, **values)
    return admin, worker, reviewer, project


def test_create_project_uses_folder_name_and_allows_overlapping_roles(database):
    _, worker, reviewer, project = create_ready_project(database)

    assert project.name == "Du an A"
    assert project.status == "new"
    assert project.root_folder_name == "Du an A"
    assert project.template_filename_snapshot.startswith("snapshot-")
    assert json.loads(project.form_schema_json_snapshot) == [{"category": "Thông tin"}]
    members = {
        (member.user_id, member.member_role)
        for member in database.query(ProjectMember).filter_by(project_id=project.id)
    }
    assert members == {
        (worker.id, "input"),
        (worker.id, "reviewer"),
        (reviewer.id, "reviewer"),
    }


def test_create_project_allows_empty_member_pools(database):
    _, _, _, project = create_ready_project(
        database,
        input_user_ids=[],
        reviewer_user_ids=[],
    )
    assert database.query(ProjectMember).filter_by(project_id=project.id).count() == 0


def test_create_project_rejects_invalid_dates_levels_and_users(database):
    admin, worker, _, template = seed_users_and_template(database)
    common = {
        "name": "Project",
        "root_folder_name": "Project",
        "template_id": template.id,
        "start_date": None,
        "end_date": None,
        "case_level": 1,
        "report_mode": "folder_level",
        "report_level": 2,
        "input_user_ids": [worker.id],
        "reviewer_user_ids": [],
        "created_by_user_id": admin.id,
    }

    with pytest.raises(HTTPException, match="Cấp báo cáo"):
        create_project(database, **{**common, "report_level": 1})
    with pytest.raises(HTTPException, match="Ngày kết thúc"):
        create_project(
            database,
            **{
                **common,
                "start_date": datetime(2026, 8, 2),
                "end_date": datetime(2026, 8, 1),
            },
        )
    with pytest.raises(HTTPException, match="Quản trị viên"):
        create_project(database, **{**common, "input_user_ids": [admin.id]})


def test_project_listing_scopes_employee_and_calculates_metrics(database):
    admin, worker, _, project = create_ready_project(database)
    case_assigned = ProjectCase(
        project_id=project.id,
        case_key="001",
        display_name="001",
        assigned_input_user_id=worker.id,
    )
    case_unassigned = ProjectCase(
        project_id=project.id,
        case_key="002",
        display_name="002",
    )
    database.add_all([case_assigned, case_unassigned])
    database.flush()
    entered = ProjectReportUnit(
        project_id=project.id,
        case_id=case_assigned.id,
        report_key="001/r1",
        display_name="r1",
        status="not_entered",
    )
    waiting = ProjectReportUnit(
        project_id=project.id,
        case_id=case_unassigned.id,
        report_key="002/r1",
        display_name="r1",
    )
    database.add_all([entered, waiting])
    database.flush()
    document = AssignedDocument(
        original_filename="a.pdf",
        uuid_filename="metric-a.pdf",
        assigned_to_user_id=worker.id,
        template_id=project.template_id,
        status="pending",
    )
    database.add(document)
    database.flush()
    database.add_all([
        ProjectDocumentAsset(
            project_id=project.id,
            case_id=case_assigned.id,
            report_unit_id=entered.id,
            assigned_document_id=document.id,
            relative_path="001/r1/a.pdf",
            normalized_relative_path="001/r1/a.pdf",
            original_filename="a.pdf",
            storage_filename="metric-a.pdf",
            content_sha256="a" * 64,
            byte_size=10,
        ),
        Submission(
            data_json=json.dumps({"_pdf_uuid": document.uuid_filename}),
            template_id=project.template_id,
            created_by_user_id=worker.id,
            assigned_document_id=document.id,
            status="completed",
        ),
    ])
    database.commit()

    employee_rows = list_projects(
        database,
        current_user={"id": worker.id, "role": "user"},
    )
    assert [row["id"] for row in employee_rows] == [project.id]
    assert employee_rows[0]["metrics"] == {
        "total_cases": 2,
        "input_assigned_cases": 1,
        "input_unassigned_cases": 1,
        "reviewer_assigned_cases": 0,
        "reviewer_unassigned_cases": 2,
        "total_pdfs": 1,
        "error_pdfs": 0,
        "entered_reports": 1,
        "required_reports": 2,
        "approved_reports": 1,
    }
    assert list_projects(database, current_user={"id": admin.id, "role": "admin"})[0]["id"] == project.id


def test_admin_project_listing_includes_quality_stats_by_original_submitter(database):
    admin, worker, reviewer, project = create_ready_project(database)
    case_row = ProjectCase(
        project_id=project.id,
        case_key="quality",
        display_name="quality",
        assigned_input_user_id=reviewer.id,
    )
    database.add(case_row)
    database.flush()
    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case_row.id,
        report_key="quality/report",
        display_name="quality report",
    )
    document = AssignedDocument(
        original_filename="quality.pdf",
        uuid_filename="quality-stats.pdf",
        assigned_to_user_id=reviewer.id,
        template_id=project.template_id,
        status="completed",
    )
    database.add_all([report, document])
    database.flush()
    database.add(ProjectDocumentAsset(
        project_id=project.id,
        case_id=case_row.id,
        report_unit_id=report.id,
        assigned_document_id=document.id,
        relative_path="quality/report/quality.pdf",
        normalized_relative_path="quality/report/quality.pdf",
        original_filename="quality.pdf",
        storage_filename="quality-stats.pdf",
        content_sha256="b" * 64,
        byte_size=10,
    ))
    draft = Submission(
        data_json='{"col_0": "draft"}',
        template_id=project.template_id,
        created_by_user_id=worker.id,
        assigned_document_id=document.id,
        status="draft",
    )
    pending = Submission(
        data_json='{"col_0": "pending"}',
        template_id=project.template_id,
        created_by_user_id=reviewer.id,
        assigned_document_id=document.id,
        status="pending_review",
    )
    approved = Submission(
        data_json='{"col_0": "approved"}',
        template_id=project.template_id,
        created_by_user_id=reviewer.id,
        assigned_document_id=document.id,
        status="completed",
    )
    database.add_all([draft, pending, approved])
    database.flush()
    database.add_all([
        SubmissionQualityAssessment(
            submission_id=pending.id,
            input_user_id=worker.id,
            baseline_data_json=pending.data_json,
            visible_field_count=1,
        ),
        SubmissionQualityAssessment(
            submission_id=approved.id,
            input_user_id=worker.id,
            baseline_data_json=approved.data_json,
            visible_field_count=1,
            changed_field_count=1,
            is_error_report=True,
        ),
    ])
    database.commit()

    admin_project = list_projects(
        database,
        current_user={"id": admin.id, "role": "admin"},
    )[0]
    assert admin_project["member_report_stats"] == [{
        "user_id": worker.id,
        "error_reports": 1,
        "pending_review_reports": 1,
        "total_reports": 3,
    }]
    employee_project = list_projects(
        database,
        current_user={"id": worker.id, "role": "user"},
    )[0]
    assert employee_project["member_report_stats"] == []


def test_project_routes_and_direct_create_endpoint(database):
    admin, worker, _, template = seed_users_and_template(database)
    routes = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/api/projects", "POST") in routes
    assert ("/api/projects", "GET") in routes
    assert ("/api/projects/mine", "GET") in routes
    assert ("/api/projects/{project_id}/status", "PUT") in routes

    response = api_create_project(
        ProjectCreateRequest(
            root_folder_name="Folder B",
            template_id=template.id,
            case_level=1,
            report_mode="pdf",
            input_user_ids=[worker.id],
        ),
        current_user={"id": admin.id, "role": "admin"},
        db=database,
    )
    assert response["status"] == "ok"
    created = database.get(Project, response["project_id"])
    assert created.report_level is None
    assert created.status == "new"


def test_project_status_update_validates_and_persists(database):
    admin, _, _, project = create_ready_project(database)

    response = api_update_project_status(
        project.id,
        ProjectStatusUpdateRequest(status="in_progress"),
        current_user={"id": admin.id, "role": "admin"},
        db=database,
    )
    assert response == {"status": "ok", "data": {"id": project.id, "status": "in_progress"}}
    assert database.get(Project, project.id).status == "in_progress"

    with pytest.raises(ValueError):
        ProjectStatusUpdateRequest(status="ready")
    with pytest.raises(HTTPException, match="không hợp lệ"):
        update_project_status(database, project_id=project.id, status="ready")


def test_project_cannot_complete_until_all_required_reports_are_completed(database):
    _, worker, _, project = create_ready_project(database)
    case_row = ProjectCase(
        project_id=project.id,
        case_key="completion-gate",
        display_name="completion-gate",
        assigned_input_user_id=worker.id,
    )
    database.add(case_row)
    database.flush()
    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case_row.id,
        report_key="completion-gate/report",
        display_name="report",
    )
    document = AssignedDocument(
        original_filename="completion-gate.pdf",
        uuid_filename="completion-gate.pdf",
        assigned_to_user_id=worker.id,
        template_id=project.template_id,
        status="completed",
    )
    database.add_all([report, document])
    database.flush()
    database.add(ProjectDocumentAsset(
        project_id=project.id,
        case_id=case_row.id,
        report_unit_id=report.id,
        assigned_document_id=document.id,
        relative_path="completion-gate/report/document.pdf",
        normalized_relative_path="completion-gate/report/document.pdf",
        original_filename="completion-gate.pdf",
        storage_filename="completion-gate-storage.pdf",
        content_sha256="c" * 64,
        byte_size=10,
    ))
    submission = Submission(
        data_json=json.dumps({"_pdf_uuid": document.uuid_filename}),
        template_id=project.template_id,
        created_by_user_id=worker.id,
        assigned_document_id=document.id,
        status="pending_input_confirmation",
    )
    database.add(submission)
    database.commit()

    with pytest.raises(HTTPException) as incomplete:
        update_project_status(database, project_id=project.id, status="completed")

    assert incomplete.value.status_code == 409
    assert incomplete.value.detail == {
        "code": "project_reports_not_completed",
        "message": "Chỉ được hoàn thành dự án khi tất cả báo cáo bắt buộc đã hoàn thành",
        "completed_reports": 0,
        "required_reports": 1,
    }
    assert database.get(Project, project.id).status == "new"

    submission.status = "completed"
    database.commit()
    result = update_project_status(database, project_id=project.id, status="completed")

    assert result == {"id": project.id, "status": "completed"}


def test_project_status_migration_normalizes_legacy_values(database):
    _, _, _, project = create_ready_project(database)
    database.query(Project).filter(Project.id == project.id).update({"status": "ready"})
    database.commit()

    ensure_project_status_schema(database.get_bind())

    assert database.get(Project, project.id).status == "in_progress"
