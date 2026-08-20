import json

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
    Template,
    User,
)
from server.services.project_workspace_service import get_project_workspace


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-workspace.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_workspace_uses_pinned_schema_and_only_assigned_cases(database):
    admin = User(username="workspace-admin", password="hash", role="admin")
    input_user = User(username="workspace-input", password="hash", role="user")
    other_user = User(username="workspace-other", password="hash", role="user")
    template = Template(name="Current template", filename="current.xlsm")
    database.add_all([admin, input_user, other_user, template])
    database.flush()
    project = Project(
        name="Pinned project",
        root_folder_name="pinned",
        template_id=template.id,
        template_name_snapshot="Pinned template",
        template_filename_snapshot="project_snapshots/pinned.xlsm",
        template_config_json_snapshot=json.dumps({"required_cols": [1]}),
        form_schema_json_snapshot=json.dumps([{"name": "Pinned section", "fields": []}]),
        case_level=1,
        report_mode="pdf",
        status="ready",
        created_by_user_id=admin.id,
    )
    database.add(project)
    database.flush()
    database.add(ProjectMember(
        project_id=project.id,
        user_id=input_user.id,
        member_role="input",
    ))
    owned_case = ProjectCase(
        project_id=project.id,
        case_key="001",
        display_name="001",
        assigned_input_user_id=input_user.id,
    )
    other_case = ProjectCase(
        project_id=project.id,
        case_key="002",
        display_name="002",
        assigned_input_user_id=other_user.id,
    )
    database.add_all([owned_case, other_case])
    database.flush()
    owned_report = ProjectReportUnit(
        project_id=project.id,
        case_id=owned_case.id,
        report_key="001/report.pdf",
        display_name="report.pdf",
    )
    other_report = ProjectReportUnit(
        project_id=project.id,
        case_id=other_case.id,
        report_key="002/report.pdf",
        display_name="report.pdf",
    )
    database.add_all([owned_report, other_report])
    database.flush()
    owned_document = AssignedDocument(
        original_filename="report.pdf",
        uuid_filename="owned.pdf",
        assigned_to_user_id=input_user.id,
        template_id=template.id,
        status="pending",
    )
    database.add(owned_document)
    database.flush()
    database.add_all([
        ProjectDocumentAsset(
            project_id=project.id,
            case_id=owned_case.id,
            report_unit_id=owned_report.id,
            assigned_document_id=owned_document.id,
            relative_path="001/report.pdf",
            normalized_relative_path="001/report.pdf",
            original_filename="report.pdf",
            storage_filename="owned.pdf",
            content_sha256="a" * 64,
            byte_size=10,
            status="active",
        ),
        ProjectDocumentAsset(
            project_id=project.id,
            case_id=other_case.id,
            report_unit_id=other_report.id,
            relative_path="002/report.pdf",
            normalized_relative_path="002/report.pdf",
            original_filename="report.pdf",
            storage_filename="other.pdf",
            content_sha256="b" * 64,
            byte_size=10,
            status="active",
        ),
    ])
    database.add(Submission(
        data_json=json.dumps({"_pdf_uuid": owned_document.uuid_filename}),
        template_id=template.id,
        created_by_user_id=input_user.id,
        assigned_document_id=owned_document.id,
        status="draft",
    ))
    database.commit()

    payload = get_project_workspace(
        database,
        project_id=project.id,
        current_user={"id": input_user.id, "role": "user"},
    )

    assert payload["project"]["template_name"] == "Pinned template"
    assert payload["schema"] == [{"name": "Pinned section", "fields": []}]
    assert payload["config"] == {"required_cols": [1]}
    assert [item["relative_path"] for item in payload["files"]] == ["001/report.pdf"]
    assert payload["files"][0]["entered"] is True

    with pytest.raises(HTTPException) as forbidden:
        get_project_workspace(
            database,
            project_id=project.id,
            current_user={"id": other_user.id, "role": "user"},
        )
    assert forbidden.value.status_code == 403
