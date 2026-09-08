import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.database import get_utc_now
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    ProjectUploadFile,
    ProjectUploadSession,
    Template,
    User,
)
from server.routers.project_uploads import router
from server.repositories.project_upload_repository import ProjectUploadRepository
from server.services.project_upload_service import (
    cleanup_stale_project_uploads,
    create_or_resume_upload_session,
    finalize_upload_session,
    get_upload_session,
    write_upload_chunk,
)


@pytest.fixture()
def database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-upload.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enforce_sqlite_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setenv("PDF_STORAGE_PATH", str(tmp_path / "uploads"))
    try:
        yield db, tmp_path
    finally:
        db.close()
        engine.dispose()


def seed_project(database, *, report_mode="folder_level"):
    admin = User(username="upload-admin", password="hash", role="admin")
    template = Template(name="Upload form", filename="upload.xlsm")
    database.add_all([admin, template])
    database.flush()
    project = Project(
        name="Upload project",
        root_folder_name="upload-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        case_level=1,
        report_mode=report_mode,
        report_level=2 if report_mode == "folder_level" else None,
        status="ready",
        created_by_user_id=admin.id,
    )
    database.add(project)
    database.commit()
    return admin, project


def raw_item(relative_path, content):
    return {
        "relative_path": relative_path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "last_modified": "1787247000000",
    }


def test_create_session_requests_only_new_or_changed_files_and_is_idempotent(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    existing_content = b"%PDF-existing"
    new_content = b"%PDF-new"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="manifest-1",
        raw_items=[
            raw_item("001/existing.pdf", existing_content),
            raw_item("001/new.pdf", new_content),
        ],
    )
    assert session["requested_files"] == 2

    first_file = session["files"][0]
    first_upload = db.get(ProjectUploadSession, session["id"])
    assert first_upload.status == "created"
    assert first_upload.expires_at is not None
    resumed = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="manifest-1",
        raw_items=[
            raw_item("001/existing.pdf", existing_content),
            raw_item("001/new.pdf", new_content),
        ],
    )
    assert resumed["id"] == session["id"]
    assert resumed["files"][0]["file_id"] == first_file["file_id"]

    with pytest.raises(HTTPException) as conflict:
        create_or_resume_upload_session(
            db,
            project_id=project.id,
            created_by_user_id=admin.id,
            client_session_key="manifest-1",
            raw_items=[raw_item("001/other.pdf", b"%PDF-other")],
        )
    assert conflict.value.status_code == 409


def test_create_session_flush_count_does_not_scale_with_file_count(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    flush_count = 0

    def count_flushes(*_args):
        nonlocal flush_count
        flush_count += 1

    event.listen(db, "before_flush", count_flushes)
    try:
        session = create_or_resume_upload_session(
            db,
            project_id=project.id,
            created_by_user_id=admin.id,
            client_session_key="batch-flush",
            raw_items=[
                raw_item(f"001/report-{index:03d}.pdf", f"%PDF-{index}".encode())
                for index in range(25)
            ],
        )
    finally:
        event.remove(db, "before_flush", count_flushes)

    assert session["requested_files"] == 25
    assert flush_count == 3
    upload_files = (
        db.query(ProjectUploadFile)
        .filter(ProjectUploadFile.session_id == session["id"])
        .all()
    )
    assert len(upload_files) == 25
    assert all(
        item.staging_filename == f"{item.id}-{item.expected_sha256}.part"
        for item in upload_files
    )


def test_chunk_upload_supports_resume_and_idempotent_retry(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-1.7\nchunked-content"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="chunk-session",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    file_id = session["files"][0]["file_id"]
    first = content[:10]
    second = content[10:]

    progress = write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=file_id,
        offset=0,
        chunk=first,
    )
    assert progress["next_offset"] == len(first)
    retry = write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=file_id,
        offset=0,
        chunk=first,
    )
    assert retry["next_offset"] == len(first)

    with pytest.raises(HTTPException) as out_of_order:
        write_upload_chunk(
            db,
            session_id=session["id"],
            file_id=file_id,
            offset=len(first) + 1,
            chunk=second,
        )
    assert out_of_order.value.status_code == 409

    completed = write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=file_id,
        offset=len(first),
        chunk=second,
    )
    assert completed["state"] == "uploaded"
    assert completed["next_offset"] == len(content)


def test_chunk_upload_does_not_lock_or_count_the_shared_session(database, monkeypatch):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-independent-file-lock"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="independent-file-lock",
        raw_items=[raw_item("001/report.pdf", content)],
    )

    def unexpected_shared_session_operation(*_args, **_kwargs):
        raise AssertionError("chunk upload must not lock or count the shared session")

    monkeypatch.setattr(
        ProjectUploadRepository,
        "lock_session",
        unexpected_shared_session_operation,
    )
    monkeypatch.setattr(
        ProjectUploadRepository,
        "count_session_files_by_status",
        unexpected_shared_session_operation,
    )

    result = write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=session["files"][0]["file_id"],
        offset=0,
        chunk=content,
    )

    assert result["state"] == "uploaded"


def test_upload_status_derives_progress_without_writing_session_counters(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    first = b"%PDF-first-progress"
    second = b"%PDF-second-progress"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="derived-progress",
        raw_items=[
            raw_item("001/first.pdf", first),
            raw_item("001/second.pdf", second),
        ],
    )

    write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=session["files"][0]["file_id"],
        offset=0,
        chunk=first,
    )
    persisted = db.get(ProjectUploadSession, session["id"])
    status = get_upload_session(db, session_id=session["id"])

    assert persisted.status == "created"
    assert persisted.completed_files == 0
    assert status["state"] == "uploading"
    assert status["completed_files"] == 1
    assert status["failed_files"] == 0


def test_file_fsync_policy_skips_nonfinal_chunk(database, monkeypatch):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-fsync-at-file-completion"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="file-fsync-policy",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    fsync_calls = []
    monkeypatch.setenv("PROJECT_UPLOAD_FSYNC_POLICY", "file")
    monkeypatch.setattr(
        "server.services.project_upload_service.os.fsync",
        lambda file_descriptor: fsync_calls.append(file_descriptor),
    )
    first = content[:10]

    write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=session["files"][0]["file_id"],
        offset=0,
        chunk=first,
    )
    assert fsync_calls == []

    write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=session["files"][0]["file_id"],
        offset=len(first),
        chunk=content[len(first) :],
    )
    assert len(fsync_calls) == 1


def test_chunk_upload_records_backend_timing_milestones(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-timing"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="timing-session",
        raw_items=[raw_item("001/timing.pdf", content)],
    )
    timing_marks = {}

    result = write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=session["files"][0]["file_id"],
        offset=0,
        chunk=content,
        timing_marks=timing_marks,
    )

    assert result["state"] == "uploaded"
    milestone_names = [
        "backend_started",
        "file_lock_started",
        "file_lock_acquired",
        "file_write_started",
        "file_written",
        "flush_completed",
        "fsync_started",
        "fsync_completed",
        "sha256_started",
        "sha256_completed",
        "database_update_started",
        "database_commit_started",
        "database_committed",
    ]
    assert all(name in timing_marks for name in milestone_names)
    assert [timing_marks[name] for name in milestone_names] == sorted(
        timing_marks[name] for name in milestone_names
    )


def test_hash_mismatch_resets_file_without_finalizing(database):
    db, tmp_path = database
    admin, project = seed_project(db, report_mode="pdf")
    declared = b"%PDF-declared"
    actual = b"%PDF-tampered"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="bad-hash",
        raw_items=[
            {
                **raw_item("001/report.pdf", declared),
                "size": len(actual),
            }
        ],
    )
    with pytest.raises(HTTPException) as mismatch:
        write_upload_chunk(
            db,
            session_id=session["id"],
            file_id=session["files"][0]["file_id"],
            offset=0,
            chunk=actual,
        )
    assert mismatch.value.status_code == 422
    assert not list((tmp_path / "uploads" / ".project_uploads").rglob("*.part"))


def test_cleanup_stale_project_uploads_expires_abandoned_session(database):
    db, tmp_path = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-abandoned-upload"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="abandoned-upload",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    upload_file = db.get(ProjectUploadFile, session["files"][0]["file_id"])
    staging_path = (
        tmp_path
        / "uploads"
        / ".project_uploads"
        / session["id"]
        / upload_file.staging_filename
    )
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_bytes(content[:8])
    old = get_utc_now() - timedelta(hours=25)
    persisted_session = db.get(ProjectUploadSession, session["id"])
    persisted_session.updated_at = old
    persisted_session.created_at = old
    upload_file.updated_at = old
    upload_file.status = "uploading"
    upload_file.next_offset = 8
    db.commit()

    result = cleanup_stale_project_uploads(db, max_age_hours=24)

    db.refresh(persisted_session)
    db.refresh(upload_file)
    assert result == {"cleaned": 1, "skipped": 0, "errors": 0}
    assert persisted_session.status == "cancelled"
    assert upload_file.status == "failed"
    assert upload_file.next_offset == 0
    assert not staging_path.exists()


def test_cleanup_stale_project_uploads_keeps_recent_file_activity(database):
    db, tmp_path = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-active-upload"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="active-upload",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    upload_file = db.get(ProjectUploadFile, session["files"][0]["file_id"])
    old = get_utc_now() - timedelta(hours=25)
    persisted_session = db.get(ProjectUploadSession, session["id"])
    persisted_session.updated_at = old
    persisted_session.created_at = old
    upload_file.updated_at = get_utc_now()
    db.commit()

    result = cleanup_stale_project_uploads(db, max_age_hours=24)

    assert result == {"cleaned": 0, "skipped": 1, "errors": 0}
    assert db.get(ProjectUploadSession, session["id"]).status == "created"
    assert not list((tmp_path / "uploads" / ".project_uploads").rglob("*.part"))


def test_cleanup_stale_project_uploads_retries_locked_file_on_next_startup(
    database,
    monkeypatch,
):
    db, tmp_path = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-locked-upload"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="locked-upload",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    persisted_session = db.get(ProjectUploadSession, session["id"])
    upload_file = db.get(ProjectUploadFile, session["files"][0]["file_id"])
    staging_path = (
        tmp_path
        / "uploads"
        / ".project_uploads"
        / session["id"]
        / upload_file.staging_filename
    )
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_bytes(content)
    old = get_utc_now() - timedelta(hours=25)
    persisted_session.created_at = old
    persisted_session.updated_at = old
    upload_file.updated_at = old
    db.commit()
    real_unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path == staging_path:
            raise PermissionError(13, "file is being used", str(path))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    monkeypatch.setattr("server.services.project_upload_service.time.sleep", lambda _seconds: None)

    result = cleanup_stale_project_uploads(db, max_age_hours=24)

    assert result == {"cleaned": 0, "skipped": 0, "errors": 1}
    assert db.get(ProjectUploadSession, session["id"]).status == "created"
    assert staging_path.is_file()


def test_expired_upload_session_can_restart_with_same_client_key(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    content = b"%PDF-restart-expired"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="restart-expired",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    persisted_session = db.get(ProjectUploadSession, session["id"])
    upload_file = db.get(ProjectUploadFile, session["files"][0]["file_id"])
    persisted_session.status = "cancelled"
    upload_file.status = "failed"
    upload_file.next_offset = 0
    db.commit()

    resumed = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="restart-expired",
        raw_items=[raw_item("001/report.pdf", content)],
    )

    assert resumed["id"] == session["id"]
    assert resumed["state"] == "created"
    assert resumed["files"][0]["state"] == "pending"


def test_finalize_atomically_groups_multiple_pdfs_into_one_report(database):
    db, tmp_path = database
    admin, project = seed_project(db)
    first = b"%PDF-first"
    second = b"%PDF-second"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="finalize-session",
        raw_items=[
            raw_item("001/report-a/page-1.pdf", first),
            raw_item("001/report-a/page-2.pdf", second),
        ],
    )
    content_by_path = {
        "001/report-a/page-1.pdf": first,
        "001/report-a/page-2.pdf": second,
    }
    for item in session["files"]:
        content = content_by_path[item["relative_path"]]
        write_upload_chunk(
            db,
            session_id=session["id"],
            file_id=item["file_id"],
            offset=0,
            chunk=content,
        )

    finalized = finalize_upload_session(db, session_id=session["id"])

    assert finalized["state"] == "completed"
    assert finalized["imported_files"] == 2
    assert db.query(ProjectReportUnit).count() == 1
    assets = db.query(ProjectDocumentAsset).all()
    assert len(assets) == 2
    assert len({asset.report_unit_id for asset in assets}) == 1
    assert all((tmp_path / "uploads" / asset.storage_filename).is_file() for asset in assets)
    assert not list((tmp_path / "uploads" / ".project_uploads").rglob("*.part"))


def test_finalize_materializes_project_assets_for_existing_employee_queue(database):
    db, _ = database
    admin, project = seed_project(db, report_mode="pdf")
    input_user = User(username="project-input", password="hash", role="user")
    reviewer = User(username="project-reviewer", password="hash", role="user")
    db.add_all([input_user, reviewer])
    db.flush()
    db.add_all([
        ProjectMember(project_id=project.id, user_id=input_user.id, member_role="input"),
        ProjectMember(project_id=project.id, user_id=reviewer.id, member_role="reviewer"),
    ])
    db.commit()

    content = b"%PDF-project-workspace"
    session = create_or_resume_upload_session(
        db,
        project_id=project.id,
        created_by_user_id=admin.id,
        client_session_key="workspace-materialization",
        raw_items=[raw_item("001/report.pdf", content)],
    )
    upload_file = session["files"][0]
    write_upload_chunk(
        db,
        session_id=session["id"],
        file_id=upload_file["file_id"],
        offset=0,
        chunk=content,
    )

    result = finalize_upload_session(db, session_id=session["id"])

    asset = db.query(ProjectDocumentAsset).one()
    case_row = db.query(ProjectCase).one()
    document = db.get(AssignedDocument, asset.assigned_document_id)
    assert result["workspace_counts"] == {
        "created_documents": 1,
        "updated_documents": 1,
    }
    assert document.assigned_to_user_id == case_row.assigned_input_user_id == input_user.id
    assert document.template_id == project.template_id
    assert document.uuid_filename == asset.storage_filename
    assert db.query(AssignedDocumentPath).filter_by(document_id=document.id).one().relative_path == "001/report.pdf"
    assert db.query(AssignedDocumentFolder).filter_by(document_id=document.id).one().folder_group == f"project/{project.id}/001"
    assert db.query(AssignedDocumentReviewAssignment).filter_by(document_id=document.id).one().reviewer_user_id == reviewer.id


def test_project_upload_routes_are_registered():
    routes = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/api/projects/{project_id}/upload-sessions", "POST") in routes
    assert ("/api/project-upload-sessions/{session_id}", "GET") in routes
    assert ("/api/project-upload-sessions/{session_id}/files/{file_id}", "PUT") in routes
    assert ("/api/project-upload-sessions/{session_id}/finalize", "POST") in routes
