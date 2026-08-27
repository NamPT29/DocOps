import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentPath,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    Submission,
    Template,
    User,
)
from server.repositories.project_reporting_repository import ProjectReportingRepository
from server.routers.projects import router
from server.routers.submissions import api_get_next_review_submission
from server.services import export_job_service
from server.services.project_reporting_service import (
    get_project_submissions,
    list_project_submission_folders,
    resolve_project_template_path,
)


@pytest.fixture()
def reporting_database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-reporting.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    template_root = tmp_path / "templates"
    snapshot_dir = template_root / "project_snapshots"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot.xlsx").write_bytes(b"xlsx")
    monkeypatch.setenv("TEMPLATE_STORAGE_PATH", str(template_root))
    try:
        yield db, tmp_path
    finally:
        db.close()
        engine.dispose()


def seed_reporting_project(db):
    admin = User(username="report-admin", password="hash", role="admin")
    input_user = User(username="report-input", password="hash", role="user")
    template = Template(name="Project form", filename="live.xlsx")
    db.add_all([admin, input_user, template])
    db.flush()
    project = Project(
        name="Reporting project",
        root_folder_name="reporting-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot="project_snapshots/snapshot.xlsx",
        template_config_json_snapshot="{}",
        form_schema_json_snapshot="[]",
        case_level=1,
        report_mode="pdf",
        status="ready",
        created_by_user_id=admin.id,
    )
    other_project = Project(
        name="Other project",
        root_folder_name="other-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot="project_snapshots/snapshot.xlsx",
        template_config_json_snapshot="{}",
        form_schema_json_snapshot="[]",
        case_level=1,
        report_mode="pdf",
        status="ready",
        created_by_user_id=admin.id,
    )
    db.add_all([project, other_project])
    db.flush()

    submissions = {}
    for case_key in ("zeta/02", "Alpha/01"):
        case_row = ProjectCase(
            project_id=project.id,
            case_key=case_key,
            display_name=case_key.rsplit("/", 1)[-1],
            assigned_input_user_id=input_user.id,
        )
        db.add(case_row)
        db.flush()
        report = ProjectReportUnit(
            project_id=project.id,
            case_id=case_row.id,
            report_key=f"{case_key}/report.pdf",
            display_name="report.pdf",
        )
        db.add(report)
        db.flush()
        document = AssignedDocument(
            original_filename="report.pdf",
            uuid_filename=f"{case_row.id}-report.pdf",
            assigned_to_user_id=input_user.id,
            template_id=template.id,
            status="completed",
        )
        db.add(document)
        db.flush()
        relative_path = f"{case_key}/report.pdf"
        db.add_all([
            ProjectDocumentAsset(
                project_id=project.id,
                case_id=case_row.id,
                report_unit_id=report.id,
                assigned_document_id=document.id,
                relative_path=relative_path,
                normalized_relative_path=relative_path.casefold(),
                original_filename="report.pdf",
                storage_filename=document.uuid_filename,
                content_sha256=("a" if case_key.startswith("zeta") else "b") * 64,
                byte_size=10,
                status="active",
            ),
            AssignedDocumentPath(
                document_id=document.id,
                relative_path=relative_path,
                upload_id=f"upload-{case_row.id}",
            ),
        ])
        for status in (
            "draft",
            "pending_review",
            "pending_input_confirmation",
            "completed",
        ):
            submission = Submission(
                data_json=json.dumps({"_pdf_uuid": document.uuid_filename}),
                template_id=template.id,
                created_by_user_id=input_user.id,
                assigned_document_id=document.id,
                status=status,
            )
            db.add(submission)
            db.flush()
            submissions[(case_key, status)] = submission

    other_case = ProjectCase(
        project_id=other_project.id,
        case_key="Alpha/00",
        display_name="00",
        assigned_input_user_id=input_user.id,
    )
    db.add(other_case)
    db.flush()
    other_report = ProjectReportUnit(
        project_id=other_project.id,
        case_id=other_case.id,
        report_key="Alpha/00/report.pdf",
        display_name="report.pdf",
    )
    db.add(other_report)
    db.flush()
    other_document = AssignedDocument(
        original_filename="other.pdf",
        uuid_filename="other-report.pdf",
        assigned_to_user_id=input_user.id,
        template_id=template.id,
        status="completed",
    )
    db.add(other_document)
    db.flush()
    db.add(ProjectDocumentAsset(
        project_id=other_project.id,
        case_id=other_case.id,
        report_unit_id=other_report.id,
        assigned_document_id=other_document.id,
        relative_path="Alpha/00/report.pdf",
        normalized_relative_path="alpha/00/report.pdf",
        original_filename="other.pdf",
        storage_filename=other_document.uuid_filename,
        content_sha256="c" * 64,
        byte_size=10,
        status="active",
    ))
    other_submission = Submission(
        data_json="{}",
        template_id=template.id,
        created_by_user_id=input_user.id,
        assigned_document_id=other_document.id,
        status="completed",
    )
    db.add(other_submission)
    db.commit()
    return project, other_project, submissions, other_submission


def test_project_views_are_scoped_filtered_and_sorted(reporting_database):
    db, _tmp_path = reporting_database
    project, _other_project, submissions, _other_submission = seed_reporting_project(db)

    review_folders = list_project_submission_folders(
        db,
        project_id=project.id,
        view="review",
    )["folders"]
    assert [folder["folder_path"] for folder in review_folders] == ["Alpha/01", "zeta/02"]
    assert [folder["submission_count"] for folder in review_folders] == [1, 1]

    review_page = get_project_submissions(
        db,
        project_id=project.id,
        view="review",
        folder_path="Alpha/01",
        page=1,
        page_size=20,
    )
    assert {item["status"] for item in review_page["data"]} == {"pending_review"}
    assert {item["folder_path"] for item in review_page["data"]} == {"Alpha/01"}
    assert {item["id"] for item in review_page["data"]} == {
        submissions[("Alpha/01", "pending_review")].id,
    }

    completed_page = get_project_submissions(
        db,
        project_id=project.id,
        view="completed",
        folder_path=None,
        page=1,
        page_size=20,
    )
    assert len(completed_page["data"]) == 2
    assert {item["status"] for item in completed_page["data"]} == {"completed"}


def test_project_export_scope_and_snapshot(reporting_database):
    db, _tmp_path = reporting_database
    project, _other_project, _submissions, other_submission = seed_reporting_project(db)
    repository = ProjectReportingRepository(db)

    completed = repository.submissions_for_export(project.id, include_pending_review=False)
    all_exportable = repository.submissions_for_export(project.id, include_pending_review=True)

    assert [submission.status for submission in completed] == ["completed", "completed"]
    assert {submission.status for submission in all_exportable} == {
        "pending_review",
        "pending_input_confirmation",
        "completed",
    }
    assert len(all_exportable) == 6
    assert other_submission.id not in {submission.id for submission in all_exportable}
    assert resolve_project_template_path(project).name == "snapshot.xlsx"


def test_project_review_next_stays_in_the_selected_project_and_folder(reporting_database):
    db, _tmp_path = reporting_database
    project, other_project, submissions, _other_submission = seed_reporting_project(db)
    admin = db.query(User).filter(User.role == "admin").one()
    current = submissions[("Alpha/01", "pending_input_confirmation")]

    result = api_get_next_review_submission(
        current_id=current.id,
        folder_path="Alpha/01",
        project_id=project.id,
        current_user={"id": admin.id, "role": "admin"},
        db=db,
    )

    assert result["data"]["id"] == submissions[("Alpha/01", "pending_review")].id
    with pytest.raises(HTTPException) as outside_project:
        api_get_next_review_submission(
            current_id=current.id,
            folder_path="Alpha/01",
            project_id=other_project.id,
            current_user={"id": admin.id, "role": "admin"},
            db=db,
        )
    assert outside_project.value.status_code == 404


def test_project_reporting_routes_are_registered():
    routes = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/api/projects/{project_id}/submission-folders", "GET") in routes
    assert ("/api/projects/{project_id}/submissions", "GET") in routes
    assert ("/api/projects/{project_id}/export-jobs", "POST") in routes


def test_project_export_job_passes_project_to_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(export_job_service, "EXPORT_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(export_job_service, "EXPORT_LOCK_PATH", tmp_path / "export_all.lock")
    calls = []
    monkeypatch.setattr(
        export_job_service.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    job = export_job_service.start_export_job(
        template_id=3,
        extension=".xlsx",
        include_pending_review=False,
        folder_path=None,
        start_date=None,
        end_date=None,
        requested_by_user_id=1,
        project_id=9,
    )
    command = calls[0][0]
    assert command[command.index("--project-id") + 1] == "9"
    assert job["project_id"] == 9
    assert job["filename"].startswith("DuAn_HoanChinh_9_")
    assert export_job_service.public_export_job(job)["project_id"] == 9
    export_job_service.update_export_job(job["job_id"], state="completed")
    export_job_service.release_export_lock(job["job_id"])
    export_job_service.cleanup_export_job(job["job_id"])
