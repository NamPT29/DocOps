import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Project,
    ProjectAssignmentHistory,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectPdfDeletionAudit,
    ProjectReportUnit,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
)
from server.routers.projects import router
from server.services.project_admin_service import (
    hard_delete_project_pdf,
    update_project_members,
)


@pytest.fixture()
def database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-admin.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setenv("PDF_STORAGE_PATH", str(tmp_path / "uploads"))
    try:
        yield db, tmp_path
    finally:
        db.close()
        engine.dispose()


def seed_admin_project(database):
    admin = User(username="project-admin", password="hash", role="admin")
    old_input = User(username="old-input", password="hash", role="user")
    new_input = User(username="new-input", password="hash", role="user")
    old_reviewer = User(username="old-reviewer", password="hash", role="user")
    new_reviewer = User(username="new-reviewer", password="hash", role="user")
    template = Template(name="Admin form", filename="admin.xlsm")
    database.add_all([admin, old_input, new_input, old_reviewer, new_reviewer, template])
    database.flush()
    project = Project(
        name="Admin project",
        root_folder_name="admin-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        template_config_json_snapshot="{}",
        form_schema_json_snapshot="[]",
        case_level=1,
        report_mode="pdf",
        status="ready",
        created_by_user_id=admin.id,
    )
    database.add(project)
    database.flush()
    database.add_all([
        ProjectMember(project_id=project.id, user_id=old_input.id, member_role="input"),
        ProjectMember(project_id=project.id, user_id=old_reviewer.id, member_role="reviewer"),
    ])
    case_row = ProjectCase(
        project_id=project.id,
        case_key="001",
        display_name="001",
        assigned_input_user_id=old_input.id,
        assigned_reviewer_user_id=old_reviewer.id,
    )
    database.add(case_row)
    database.flush()
    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case_row.id,
        report_key="001/report.pdf",
        display_name="report.pdf",
    )
    database.add(report)
    database.flush()
    document = AssignedDocument(
        original_filename="report.pdf",
        uuid_filename="project-report.pdf",
        assigned_to_user_id=old_input.id,
        template_id=template.id,
        status="completed",
    )
    database.add(document)
    database.flush()
    asset = ProjectDocumentAsset(
        project_id=project.id,
        case_id=case_row.id,
        report_unit_id=report.id,
        assigned_document_id=document.id,
        relative_path="001/report.pdf",
        normalized_relative_path="001/report.pdf",
        original_filename="report.pdf",
        storage_filename=document.uuid_filename,
        content_sha256="a" * 64,
        byte_size=20,
        status="active",
    )
    database.add(asset)
    database.add_all([
        AssignedDocumentPath(
            document_id=document.id,
            relative_path=asset.relative_path,
            upload_id="project-asset-seed",
        ),
        AssignedDocumentFolder(
            document_id=document.id,
            folder_group=f"project/{project.id}/001",
        ),
        AssignedDocumentReviewAssignment(
            document_id=document.id,
            reviewer_user_id=old_reviewer.id,
        ),
    ])
    database.flush()
    submissions = [
        Submission(
            data_json=json.dumps({"_pdf_uuid": document.uuid_filename}),
            template_id=template.id,
            created_by_user_id=old_input.id,
            assigned_document_id=document.id,
            status=status,
        )
        for status in ("draft", "pending_review", "approved")
    ]
    database.add_all(submissions)
    database.flush()
    database.add_all([
        SubmissionReviewAssignment(
            submission_id=submission.id,
            reviewer_user_id=old_reviewer.id,
        )
        for submission in submissions
    ])
    database.commit()
    return admin, old_input, new_input, old_reviewer, new_reviewer, project, case_row, asset, submissions


def test_member_update_transfers_whole_case_drafts_and_reviews(database):
    db, _ = database
    admin, old_input, new_input, _old_reviewer, new_reviewer, project, case_row, asset, submissions = seed_admin_project(db)

    result = update_project_members(
        db,
        project_id=project.id,
        input_user_ids=[new_input.id],
        reviewer_user_ids=[new_reviewer.id],
        changed_by_user_id=admin.id,
    )

    db.refresh(case_row)
    assert case_row.assigned_input_user_id == new_input.id
    assert case_row.assigned_reviewer_user_id == new_reviewer.id
    assert result["submissions_transferred"] == 3
    assert {submission.status for submission in submissions} == {"draft", "pending_review", "approved"}
    assert all(submission.created_by_user_id == new_input.id for submission in submissions)
    assert all(
        db.get(SubmissionReviewAssignment, submission.id).reviewer_user_id == new_reviewer.id
        for submission in submissions
    )
    document = db.get(AssignedDocument, asset.assigned_document_id)
    assert document.assigned_to_user_id == new_input.id
    assert db.get(AssignedDocumentReviewAssignment, document.id).reviewer_user_id == new_reviewer.id
    assert db.query(ProjectAssignmentHistory).count() == 2
    assert not any(
        row.is_active
        for row in db.query(ProjectMember).filter(ProjectMember.user_id == old_input.id)
    )


def test_hard_delete_unentered_pdf_keeps_audit_and_removes_file(database):
    db, tmp_path = database
    admin, _old_input, _new_input, _old_reviewer, _new_reviewer, project, _case_row, asset, submissions = seed_admin_project(db)
    db.query(SubmissionReviewAssignment).delete()
    db.query(Submission).delete()
    db.commit()
    storage_root = tmp_path / "uploads"
    storage_root.mkdir()
    pdf_path = storage_root / asset.storage_filename
    pdf_path.write_bytes(b"%PDF-delete-me")
    asset_id = asset.id
    document_id = asset.assigned_document_id

    result = hard_delete_project_pdf(
        db,
        project_id=project.id,
        asset_id=asset_id,
        deleted_by_user_id=admin.id,
    )

    assert result["file_removed"] is True
    assert not pdf_path.exists()
    assert db.get(ProjectDocumentAsset, asset_id) is None
    assert db.get(AssignedDocument, document_id) is None
    audit = db.query(ProjectPdfDeletionAudit).one()
    assert audit.relative_path == "001/report.pdf"
    assert audit.content_sha256 == "a" * 64


def test_hard_delete_blocks_pdf_with_entered_data(database):
    db, tmp_path = database
    admin, _old_input, _new_input, _old_reviewer, _new_reviewer, project, _case_row, asset, _submissions = seed_admin_project(db)
    storage_root = tmp_path / "uploads"
    storage_root.mkdir()
    pdf_path = storage_root / asset.storage_filename
    pdf_path.write_bytes(b"%PDF-keep-me")

    with pytest.raises(HTTPException) as blocked:
        hard_delete_project_pdf(
            db,
            project_id=project.id,
            asset_id=asset.id,
            deleted_by_user_id=admin.id,
        )

    assert blocked.value.status_code == 409
    assert pdf_path.exists()
    assert db.get(ProjectDocumentAsset, asset.id) is not None
    assert db.query(ProjectPdfDeletionAudit).count() == 0


def test_project_admin_routes_are_registered():
    routes = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/api/projects/{project_id}/members", "PUT") in routes
    assert ("/api/projects/{project_id}/assets", "GET") in routes
    assert ("/api/projects/{project_id}/assets/{asset_id}", "DELETE") in routes
