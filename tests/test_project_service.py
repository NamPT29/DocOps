import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Template,
    User,
)
from server.routers.projects import ProjectCreateRequest, api_create_project, router
from server.services import project_service
from server.services.project_service import create_project, list_projects


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
        status="approved",
    )
    waiting = ProjectReportUnit(
        project_id=project.id,
        case_id=case_unassigned.id,
        report_key="002/r1",
        display_name="r1",
    )
    database.add_all([entered, waiting])
    database.flush()
    database.add(
        ProjectDocumentAsset(
            project_id=project.id,
            case_id=case_assigned.id,
            report_unit_id=entered.id,
            relative_path="001/r1/a.pdf",
            normalized_relative_path="001/r1/a.pdf",
            original_filename="a.pdf",
            storage_filename="metric-a.pdf",
            content_sha256="a" * 64,
            byte_size=10,
        )
    )
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
    assert database.get(Project, response["project_id"]).report_level is None
