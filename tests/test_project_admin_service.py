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
    ProjectUploadFile,
    ProjectUploadSession,
    Submission,
    SubmissionReviewAssignment,
    SubmissionReviewHistory,
    SubmissionViewPresence,
    Template,
    User,
)
from server.routers.projects import router
from server.services import export_job_service
from server.services.project_admin_service import (
    delete_project,
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
        for status in ("draft", "pending_review", "completed")
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
    assert result["submission_reviews_transferred"] == 2
    assert {submission.status for submission in submissions} == {"draft", "pending_review", "completed"}
    assert all(submission.created_by_user_id == old_input.id for submission in submissions)
    reviewer_by_status = {
        submission.status: db.get(
            SubmissionReviewAssignment,
            submission.id,
        ).reviewer_user_id
        for submission in submissions
    }
    assert reviewer_by_status == {
        "draft": new_reviewer.id,
        "pending_review": new_reviewer.id,
        "completed": _old_reviewer.id,
    }
    document = db.get(AssignedDocument, asset.assigned_document_id)
    assert document.assigned_to_user_id == new_input.id
    assert db.get(AssignedDocumentReviewAssignment, document.id).reviewer_user_id == new_reviewer.id
    assert db.query(ProjectAssignmentHistory).count() == 2
    assert not any(
        row.is_active
        for row in db.query(ProjectMember).filter(ProjectMember.user_id == old_input.id)
    )


def test_member_update_keeps_reopened_review_with_first_reviewer(database):
    db, _ = database
    (
        admin,
        _old_input,
        new_input,
        old_reviewer,
        new_reviewer,
        project,
        _case_row,
        _asset,
        submissions,
    ) = seed_admin_project(db)
    reopened = next(row for row in submissions if row.status == "pending_review")
    db.add(SubmissionReviewHistory(
        submission_id=reopened.id,
        event_type="review_confirmed",
        input_user_id=reopened.created_by_user_id,
        reviewer_user_id=old_reviewer.id,
        baseline_data_json="{}",
        reviewer_data_json="{}",
        visible_field_count=0,
        changed_field_count=0,
    ))
    db.commit()

    result = update_project_members(
        db,
        project_id=project.id,
        input_user_ids=[new_input.id],
        reviewer_user_ids=[new_reviewer.id],
        changed_by_user_id=admin.id,
    )

    assert result["submission_reviews_transferred"] == 1
    assert db.get(
        SubmissionReviewAssignment,
        reopened.id,
    ).reviewer_user_id == old_reviewer.id


def test_member_update_rebalances_whole_folders_by_active_pdf_count(database):
    db, _ = database
    (
        admin,
        old_input,
        new_input,
        old_reviewer,
        new_reviewer,
        project,
        _seed_case,
        _seed_asset,
        _submissions,
    ) = seed_admin_project(db)

    for case_number, pdf_count in ((2, 8), (3, 7), (4, 2)):
        case_row = ProjectCase(
            project_id=project.id,
            case_key=f"{case_number:03d}",
            display_name=f"{case_number:03d}",
            assigned_input_user_id=old_input.id,
            assigned_reviewer_user_id=old_reviewer.id,
        )
        db.add(case_row)
        db.flush()
        report = ProjectReportUnit(
            project_id=project.id,
            case_id=case_row.id,
            report_key=f"{case_number:03d}/report",
            display_name="report",
        )
        db.add(report)
        db.flush()
        for pdf_number in range(1, pdf_count + 1):
            relative_path = f"{case_number:03d}/report/{pdf_number}.pdf"
            db.add(ProjectDocumentAsset(
                project_id=project.id,
                case_id=case_row.id,
                report_unit_id=report.id,
                relative_path=relative_path,
                normalized_relative_path=relative_path,
                original_filename=f"{pdf_number}.pdf",
                storage_filename=f"rebalance-{case_number}-{pdf_number}.pdf",
                content_sha256=f"{case_number * 100 + pdf_number:064x}",
                byte_size=pdf_number,
                status="active",
            ))
    db.commit()

    result = update_project_members(
        db,
        project_id=project.id,
        input_user_ids=[old_input.id, new_input.id],
        reviewer_user_ids=[old_reviewer.id, new_reviewer.id],
        changed_by_user_id=admin.id,
    )

    assert result["rebalanced"] is True
    assert sorted(row["pdf_count"] for row in result["input_distribution"]) == [0, 18]
    assert sorted(row["pdf_count"] for row in result["reviewer_distribution"]) == [0, 18]
    assert result["input_cases_transferred"] == 0
    assert result["reviewer_cases_transferred"] == 0
    assert db.query(ProjectAssignmentHistory).count() == 0
    assert all(
        case_row.assigned_input_user_id != case_row.assigned_reviewer_user_id
        for case_row in db.query(ProjectCase).filter_by(project_id=project.id).all()
    )


def test_member_update_splits_two_existing_folders_when_second_user_is_added(database):
    db, _ = database
    (
        admin,
        hoang,
        tuoi,
        first_reviewer,
        second_reviewer,
        project,
        first_case,
        _seed_asset,
        _submissions,
    ) = seed_admin_project(db)
    second_case = ProjectCase(
        project_id=project.id,
        case_key="002",
        display_name="002",
        assigned_input_user_id=hoang.id,
        assigned_reviewer_user_id=first_reviewer.id,
    )
    db.add(second_case)
    db.flush()
    db.add(ProjectReportUnit(
        project_id=project.id,
        case_id=second_case.id,
        report_key="002/report.pdf",
        display_name="report.pdf",
    ))
    db.commit()

    result = update_project_members(
        db,
        project_id=project.id,
        input_user_ids=[hoang.id, tuoi.id],
        reviewer_user_ids=[first_reviewer.id, second_reviewer.id],
        changed_by_user_id=admin.id,
    )

    db.refresh(first_case)
    db.refresh(second_case)
    assert result["rebalanced"] is True
    assert {first_case.assigned_input_user_id, second_case.assigned_input_user_id} == {
        hoang.id,
        tuoi.id,
    }
    assert sorted(row["case_count"] for row in result["input_distribution"]) == [1, 1]
    assert sorted(row["pdf_count"] for row in result["input_distribution"]) == [0, 1]


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


def test_delete_project_removes_database_graph_and_managed_files(database, monkeypatch):
    db, tmp_path = database
    admin, old_input, _new_input, old_reviewer, _new_reviewer, project, case_row, asset, submissions = (
        seed_admin_project(db)
    )

    storage_root = tmp_path / "uploads"
    storage_root.mkdir(exist_ok=True)
    pdf_path = storage_root / asset.storage_filename
    pdf_path.write_bytes(b"%PDF-delete-project")

    template_root = tmp_path / "templates"
    snapshot_path = template_root / "project_snapshots" / "delete-project.xlsx"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_bytes(b"project-template-snapshot")
    monkeypatch.setenv("TEMPLATE_STORAGE_PATH", str(template_root))
    project.template_filename_snapshot = "project_snapshots/delete-project.xlsx"

    upload_session = ProjectUploadSession(
        id="delete-project-session",
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="delete-project-client",
        manifest_digest="b" * 64,
        status="created",
        total_files=1,
        requested_files=1,
    )
    db.add(upload_session)
    db.flush()
    upload_file = ProjectUploadFile(
        session_id=upload_session.id,
        relative_path="001/pending.pdf",
        normalized_relative_path="001/pending.pdf",
        expected_sha256="c" * 64,
        expected_size=10,
        status="uploading",
        next_offset=5,
        staging_filename="pending.part",
    )
    db.add(upload_file)
    staging_path = storage_root / ".project_uploads" / upload_session.id / "pending.part"
    staging_path.parent.mkdir(parents=True)
    staging_path.write_bytes(b"partial")

    db.add(ProjectAssignmentHistory(
        project_id=project.id,
        case_id=case_row.id,
        assignment_role="reviewer",
        from_user_id=old_reviewer.id,
        to_user_id=admin.id,
        changed_by_user_id=admin.id,
        reason="test-delete",
    ))
    db.add(ProjectPdfDeletionAudit(
        project_id=project.id,
        case_id=case_row.id,
        report_unit_id=asset.report_unit_id,
        relative_path="001/deleted.pdf",
        content_sha256="d" * 64,
        deleted_by_user_id=admin.id,
    ))
    db.add_all([
        SubmissionViewPresence(
            submission_id=submission.id,
            viewer_user_id=admin.id,
        )
        for submission in submissions
    ])
    db.commit()

    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    monkeypatch.setattr(export_job_service, "EXPORT_SCRATCH_DIR", scratch_root)
    monkeypatch.setattr(export_job_service, "EXPORT_LOCK_PATH", scratch_root / "export_all.lock")
    job_id = "e" * 32
    export_job_service.write_export_job(job_id, {
        "job_id": job_id,
        "project_id": project.id,
        "state": "completed",
        "extension": ".xlsx",
    })
    export_log = scratch_root / f"export_job_{job_id}.log"
    export_output = scratch_root / f"export_job_{job_id}.xlsx"
    export_log.write_text("completed", encoding="utf-8")
    export_output.write_bytes(b"xlsx")
    export_status = export_job_service.export_job_status_path(job_id)

    result = delete_project(db, project_id=project.id)

    assert result["deleted_project_id"] == project.id
    assert result["deleted"]["submissions"] == 3
    assert result["deleted"]["submission_review_assignments"] == 3
    assert result["deleted"]["submission_view_presence"] == 3
    assert result["file_cleanup_complete"] is True
    for model in (
        Project,
        ProjectMember,
        ProjectCase,
        ProjectReportUnit,
        ProjectDocumentAsset,
        ProjectUploadSession,
        ProjectUploadFile,
        ProjectAssignmentHistory,
        ProjectPdfDeletionAudit,
        AssignedDocument,
        AssignedDocumentPath,
        AssignedDocumentFolder,
        AssignedDocumentReviewAssignment,
        Submission,
        SubmissionReviewAssignment,
        SubmissionViewPresence,
    ):
        assert db.query(model).count() == 0
    assert db.query(User).count() == 5
    assert db.query(Template).count() == 1
    assert not pdf_path.exists()
    assert not snapshot_path.exists()
    assert not staging_path.exists()
    assert not export_status.exists()
    assert not export_log.exists()
    assert not export_output.exists()


def test_delete_project_restores_files_when_database_delete_fails(database, monkeypatch):
    db, tmp_path = database
    _admin, _old_input, _new_input, _old_reviewer, _new_reviewer, project, _case_row, asset, _submissions = (
        seed_admin_project(db)
    )
    storage_root = tmp_path / "uploads"
    storage_root.mkdir(exist_ok=True)
    pdf_path = storage_root / asset.storage_filename
    pdf_path.write_bytes(b"%PDF-restore-on-rollback")

    def fail_delete(_repository, _project, _manifest):
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(
        "server.repositories.project_admin_repository.ProjectAdminRepository.delete_project_graph",
        fail_delete,
    )

    with pytest.raises(RuntimeError, match="forced database failure"):
        delete_project(db, project_id=project.id)

    assert pdf_path.read_bytes() == b"%PDF-restore-on-rollback"
    assert db.get(Project, project.id) is not None
    assert db.get(ProjectDocumentAsset, asset.id) is not None


def test_delete_project_blocks_while_project_export_is_running(database, monkeypatch):
    db, tmp_path = database
    _admin, _old_input, _new_input, _old_reviewer, _new_reviewer, project, _case_row, _asset, _submissions = (
        seed_admin_project(db)
    )
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    monkeypatch.setattr(export_job_service, "EXPORT_SCRATCH_DIR", scratch_root)
    monkeypatch.setattr(export_job_service, "EXPORT_LOCK_PATH", scratch_root / "export_all.lock")
    job_id = "f" * 32
    export_job_service.write_export_job(job_id, {
        "job_id": job_id,
        "project_id": project.id,
        "state": "running",
        "extension": ".xlsx",
    })

    with pytest.raises(HTTPException) as blocked:
        delete_project(db, project_id=project.id)

    assert blocked.value.status_code == 409
    assert db.get(Project, project.id) is not None
    assert export_job_service.export_job_status_path(job_id).exists()


def test_project_admin_routes_are_registered():
    routes = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/api/projects/{project_id}/members", "PUT") in routes
    assert ("/api/projects/{project_id}/assets", "GET") in routes
    assert ("/api/projects/{project_id}/assets/{asset_id}", "DELETE") in routes
    assert ("/api/projects/{project_id}", "DELETE") in routes
