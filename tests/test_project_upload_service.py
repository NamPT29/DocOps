import hashlib

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
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    ProjectUploadSession,
    Template,
    User,
)
from server.routers.project_uploads import router
from server.services.project_upload_service import (
    create_or_resume_upload_session,
    finalize_upload_session,
    write_upload_chunk,
)


@pytest.fixture()
def database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-upload.sqlite3').as_posix()}",
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
