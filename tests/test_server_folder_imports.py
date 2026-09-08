import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.routers import documents as document_routes
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    ServerFolderImportJob,
    ServerFolderImportReviewer,
    Submission,
    Template,
    User,
)
from server.routers.documents import (
    ServerFolderImportRequest,
    get_my_queue,
    router,
    start_server_folder_import,
)
from server.services.server_folder_service import (
    folder_group_for_level,
    list_server_source_folders,
    process_server_folder_import,
    resolve_server_source_directory,
    scan_server_source_documents,
)


def write_pdf(path, marker=b"test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n" + marker)


def add_job_reviewers(db, job, reviewer_ids):
    db.add(job)
    db.flush()
    db.add_all(
        ServerFolderImportReviewer(job_id=job.id, reviewer_user_id=reviewer_id)
        for reviewer_id in reviewer_ids
    )
    db.commit()


def test_server_folder_routes_are_registered_with_expected_methods():
    registered = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/api/documents/server-folders", "GET") in registered
    assert ("/api/documents/server-folder/scan", "POST") in registered
    assert ("/api/documents/server-folder/import", "POST") in registered
    assert ("/api/documents/server-folder/jobs/{job_id}", "GET") in registered


@pytest.fixture()
def database_factory(tmp_path):
    database_path = tmp_path / "folder-import.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def test_scan_server_folder_reports_available_assignment_levels(monkeypatch, tmp_path):
    source_root = tmp_path / "source"
    write_pdf(source_root / "001" / "0001" / "1.pdf")
    write_pdf(source_root / "001" / "0001" / "n2.pdf")
    write_pdf(source_root / "001" / "0002" / "1.pdf")
    (source_root / "001" / "ignore.txt").write_text("not a document", encoding="utf-8")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))

    summary, documents = scan_server_source_documents("")

    assert summary["total_files"] == 3
    assert summary["max_folder_depth"] == 2
    assert summary["preview"] == [
        "001/0001/1.pdf",
        "001/0001/n2.pdf",
        "001/0002/1.pdf",
    ]
    assert summary["grouping_levels"] == [
        {
            "level": 1,
            "group_count": 1,
            "min_pdf_count": 3,
            "max_pdf_count": 3,
            "average_pdf_count": 3.0,
            "examples": ["001"],
        },
        {
            "level": 2,
            "group_count": 2,
            "min_pdf_count": 1,
            "max_pdf_count": 2,
            "average_pdf_count": 1.5,
            "examples": ["001/0001", "001/0002"],
        },
    ]
    assert folder_group_for_level(documents[0], 1) == "001"
    assert folder_group_for_level(documents[0], 2) == "001/0001"

    nested_summary, _ = scan_server_source_documents("001")
    assert nested_summary["max_folder_depth"] == 1
    assert nested_summary["grouping_levels"] == [
        {
            "level": 1,
            "group_count": 2,
            "min_pdf_count": 1,
            "max_pdf_count": 2,
            "average_pdf_count": 1.5,
            "examples": ["001/0001", "001/0002"],
        }
    ]


def test_my_queue_keeps_pdf_linked_to_draft_and_marks_it_entered(database_factory):
    db = database_factory()
    user = User(username="linked-draft-user", password="hash", role="user")
    template = Template(name="Mẫu nháp", filename="draft.xlsx")
    db.add_all([user, template])
    db.flush()
    document = AssignedDocument(
        original_filename="linked-draft.pdf",
        uuid_filename="uuid-linked-draft.pdf",
        assigned_to_user_id=user.id,
        template_id=template.id,
        status="pending",
    )
    db.add(document)
    db.flush()
    draft = Submission(
        data_json=json.dumps({"_pdf_uuid": document.uuid_filename}),
        created_by_user_id=user.id,
        assigned_document_id=document.id,
        template_id=template.id,
        status="draft",
    )
    db.add(draft)
    db.commit()

    entered_queue = get_my_queue(current_user={"id": user.id}, db=db)
    entered_files = [item for group in entered_queue["data"] for item in group["files"]]
    assert [item["uuid"] for item in entered_files] == [document.uuid_filename]
    assert entered_files[0]["entered"] is True
    assert entered_queue["linked_pdf_uuids"] == [document.uuid_filename]
    assert document.status == "pending"

    db.delete(draft)
    db.commit()
    restored_queue = get_my_queue(current_user={"id": user.id}, db=db)
    restored_files = [item for group in restored_queue["data"] for item in group["files"]]
    assert [item["uuid"] for item in restored_files] == [document.uuid_filename]
    assert restored_files[0]["entered"] is False
    assert restored_queue["linked_pdf_uuids"] == []
    db.close()


def test_my_queue_keeps_documents_linked_to_any_user_submission(database_factory):
    db = database_factory()
    assigned_user = User(username="queue-assigned-user", password="hash", role="user")
    other_user = User(username="queue-other-user", password="hash", role="user")
    template = Template(name="Mẫu hàng đợi", filename="queue.xlsx")
    db.add_all([assigned_user, other_user, template])
    db.flush()
    document = AssignedDocument(
        original_filename="already-entered.pdf",
        uuid_filename="uuid-already-entered.pdf",
        assigned_to_user_id=assigned_user.id,
        template_id=template.id,
        status="pending",
    )
    db.add(document)
    db.flush()
    db.add(Submission(
        data_json=json.dumps({"_pdf_filename": document.original_filename}),
        created_by_user_id=other_user.id,
        template_id=template.id,
        assigned_document_id=document.id,
        status="completed",
    ))
    db.commit()

    queue = get_my_queue(current_user={"id": assigned_user.id}, db=db)

    queue_files = [item for group in queue["data"] for item in group["files"]]
    assert [item["uuid"] for item in queue_files] == [document.uuid_filename]
    assert queue_files[0]["entered"] is True
    assert queue["linked_pdf_uuids"] == [document.uuid_filename]
    db.close()


def test_scan_excludes_managed_storage_when_it_is_nested_in_source(monkeypatch, tmp_path):
    source_root = tmp_path / "source"
    storage_root = source_root / "managed-uploads"
    write_pdf(source_root / "001" / "0001" / "1.pdf")
    write_pdf(storage_root / "already-imported.pdf")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("PDF_STORAGE_PATH", str(storage_root))

    summary, _ = scan_server_source_documents("")

    assert summary["total_files"] == 1
    assert summary["preview"] == ["001/0001/1.pdf"]


def test_server_folder_browser_stays_inside_configured_root(monkeypatch, tmp_path):
    source_root = tmp_path / "source"
    (source_root / "001" / "0001").mkdir(parents=True)
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))

    listing = list_server_source_folders("001")

    assert listing["current_relative_path"] == "001"
    assert listing["parent_relative_path"] == ""
    assert listing["directories"] == [
        {"name": "0001", "relative_path": "001/0001"}
    ]
    with pytest.raises(HTTPException) as error:
        resolve_server_source_directory("../outside")
    assert error.value.status_code == 400


def test_assignment_request_rejects_admin_as_reviewer_and_self_only_pool(
    monkeypatch, tmp_path, database_factory
):
    source_root = tmp_path / "source"
    write_pdf(source_root / "001" / "1.pdf")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))

    db = database_factory()
    admin = User(username="admin", password="hash", role="admin")
    employee = User(username="employee", password="hash", role="user")
    template = Template(name="NHOM TL", filename="nhom.xlsx")
    db.add_all([admin, employee, template])
    db.commit()

    with pytest.raises(HTTPException) as admin_reviewer_error:
        start_server_folder_import(
            ServerFolderImportRequest(
                template_id=template.id,
                input_user_ids=[employee.id],
                reviewer_user_ids=[admin.id],
                relative_path="",
                grouping_level=1,
            ),
            BackgroundTasks(),
            current_user={"id": admin.id, "role": "admin"},
            db=db,
        )
    assert admin_reviewer_error.value.status_code == 400
    assert db.query(ServerFolderImportReviewer).count() == 0

    with pytest.raises(HTTPException) as error:
        start_server_folder_import(
            ServerFolderImportRequest(
                template_id=template.id,
                input_user_ids=[employee.id],
                reviewer_user_ids=[employee.id],
                relative_path="",
                grouping_level=1,
            ),
            BackgroundTasks(),
            current_user={"id": admin.id, "role": "admin"},
            db=db,
        )
    assert error.value.status_code == 400
    db.close()


def test_direct_document_assignment_rejects_admin_as_reviewer(database_factory):
    db = database_factory()
    admin = User(username="admin-direct", password="hash", role="admin")
    employee = User(username="employee-direct", password="hash", role="user")
    template = Template(name="Direct assignment", filename="direct.xlsx")
    db.add_all([admin, employee, template])
    db.commit()

    with pytest.raises(HTTPException) as error:
        document_routes._upload_and_assign_documents_sync(
            template.id,
            [employee.id],
            [admin.id],
            [],
            db,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Danh sách người kiểm tra không hợp lệ"
    db.close()


def test_direct_document_assignment_uses_existing_pending_load(
    monkeypatch, tmp_path, database_factory
):
    db = database_factory()
    first = User(username="direct-first", password="hash", role="user")
    second = User(username="direct-second", password="hash", role="user")
    reviewer = User(username="direct-reviewer", password="hash", role="user")
    template = Template(name="Direct weighted assignment", filename="direct.xlsx")
    db.add_all([first, second, reviewer, template])
    db.flush()
    db.add_all(
        AssignedDocument(
            original_filename=f"existing-{index}.pdf",
            uuid_filename=f"existing-{index}.pdf",
            assigned_to_user_id=first.id,
            template_id=template.id,
            status="pending",
        )
        for index in range(3)
    )
    db.commit()
    monkeypatch.setattr(
        document_routes,
        "settings",
        SimpleNamespace(pdf_storage_path=tmp_path),
    )

    result = document_routes._upload_and_assign_documents_sync(
        template.id,
        [first.id, second.id],
        [first.id, second.id, reviewer.id],
        [
            UploadFile(filename="new-1.pdf", file=BytesIO(b"%PDF-1.4\nfirst")),
            UploadFile(filename="new-2.pdf", file=BytesIO(b"%PDF-1.4\nsecond")),
        ],
        db,
    )

    new_documents = db.query(AssignedDocument).filter(
        AssignedDocument.original_filename.in_(["new-1.pdf", "new-2.pdf"])
    ).all()
    assert result["status"] == "ok"
    assert {document.assigned_to_user_id for document in new_documents} == {second.id}
    db.close()


def test_import_assigns_all_documents_in_selected_folder_level_to_same_user(
    monkeypatch, tmp_path, database_factory
):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "managed-uploads"
    write_pdf(source_root / "001" / "0001" / "1.pdf", b"a")
    write_pdf(source_root / "001" / "0001" / "n2.pdf", b"b")
    write_pdf(source_root / "001" / "0002" / "1.pdf", b"c")
    write_pdf(source_root / "002" / "0001" / "a.pdf", b"d")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("PDF_STORAGE_PATH", str(storage_root))

    db = database_factory()
    user_1 = User(username="employee-1", password="hash", role="user")
    user_2 = User(username="employee-2", password="hash", role="user")
    template = Template(name="Trường thông tin văn bản (NHOM TL)", filename="nhom.xlsx")
    db.add_all([user_1, user_2, template])
    db.commit()
    job = ServerFolderImportJob(
        created_by_user_id=user_1.id,
        template_id=template.id,
        source_relative_path="",
        grouping_level=2,
        user_ids_json=json.dumps([user_1.id, user_2.id]),
        status="queued",
    )
    add_job_reviewers(db, job, [user_1.id, user_2.id])
    job_id = job.id
    user_1_id = user_1.id
    user_2_id = user_2.id
    db.close()

    process_server_folder_import(job_id, session_factory=database_factory)

    db = database_factory()
    finished_job = db.query(ServerFolderImportJob).filter_by(id=job_id).one()
    rows = db.query(
        AssignedDocument,
        AssignedDocumentPath,
        AssignedDocumentFolder,
    ).join(
        AssignedDocumentPath,
        AssignedDocumentPath.document_id == AssignedDocument.id,
    ).join(
        AssignedDocumentFolder,
        AssignedDocumentFolder.document_id == AssignedDocument.id,
    ).all()
    assignments = {
        metadata.relative_path: (document.assigned_to_user_id, folder.folder_group)
        for document, metadata, folder in rows
    }
    review_assignments = {
        document.assigned_to_user_id: review.reviewer_user_id
        for document, review in db.query(
            AssignedDocument,
            AssignedDocumentReviewAssignment,
        ).join(
            AssignedDocumentReviewAssignment,
            AssignedDocumentReviewAssignment.document_id == AssignedDocument.id,
        ).all()
    }

    assert finished_job.status == "completed"
    assert finished_job.processed_files == 4
    assert finished_job.imported_files == 4
    assert assignments["001/0001/1.pdf"] == (user_1_id, "001/0001")
    assert assignments["001/0001/n2.pdf"] == (user_1_id, "001/0001")
    assert assignments["001/0002/1.pdf"] == (user_2_id, "001/0002")
    assert assignments["002/0001/a.pdf"] == (user_2_id, "002/0001")
    assert review_assignments == {user_1_id: user_2_id, user_2_id: user_1_id}
    assert len(list(storage_root.iterdir())) == 4
    assert all(path.is_file() for path in storage_root.iterdir())

    queue = get_my_queue(current_user={"id": user_1_id}, db=db)
    queue_files = [item for group in queue["data"] for item in group["files"]]
    assert {item["folder_group"] for item in queue_files} == {"001/0001"}
    assert {item["relative_path"] for item in queue_files} == {
        "001/0001/1.pdf",
        "001/0001/n2.pdf",
    }
    db.close()


def test_reimport_redistributes_pending_files_without_creating_duplicates(
    monkeypatch, tmp_path, database_factory
):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "managed-uploads"
    write_pdf(source_root / "001" / "0001" / "1.pdf")
    write_pdf(source_root / "001" / "0002" / "1.pdf")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("PDF_STORAGE_PATH", str(storage_root))

    db = database_factory()
    user = User(username="employee-1", password="hash", role="user")
    new_user = User(username="employee-2", password="hash", role="user")
    template = Template(name="NHOM TL", filename="nhom.xlsx")
    db.add_all([user, new_user, template])
    db.commit()
    user_id = user.id
    new_user_id = new_user.id
    job_ids = []
    for user_ids, reviewer_ids in (
        ([user_id], [new_user_id]),
        ([user_id, new_user_id], [user_id, new_user_id]),
    ):
        job = ServerFolderImportJob(
            created_by_user_id=user_id,
            template_id=template.id,
            source_relative_path="",
            grouping_level=2,
            user_ids_json=json.dumps(user_ids),
            status="queued",
        )
        add_job_reviewers(db, job, reviewer_ids)
        job_ids.append(job.id)
    db.close()

    process_server_folder_import(job_ids[0], session_factory=database_factory)
    process_server_folder_import(job_ids[1], session_factory=database_factory)

    db = database_factory()
    second_job = db.query(ServerFolderImportJob).filter_by(id=job_ids[1]).one()
    assignments = {
        metadata.relative_path: (
            document.assigned_to_user_id,
            review.reviewer_user_id,
        )
        for document, metadata, review in db.query(
            AssignedDocument,
            AssignedDocumentPath,
            AssignedDocumentReviewAssignment,
        ).join(
            AssignedDocumentPath,
            AssignedDocumentPath.document_id == AssignedDocument.id,
        ).join(
            AssignedDocumentReviewAssignment,
            AssignedDocumentReviewAssignment.document_id == AssignedDocument.id,
        ).all()
    }
    assert second_job.status == "completed"
    assert second_job.imported_files == 0
    assert second_job.skipped_files == 2
    assert assignments == {
        "001/0001/1.pdf": (user_id, new_user_id),
        "001/0002/1.pdf": (new_user_id, user_id),
    }
    assert db.query(AssignedDocument).count() == 2
    assert len(list(storage_root.iterdir())) == 2
    db.close()


def test_reimport_keeps_completed_file_with_original_user(
    monkeypatch, tmp_path, database_factory
):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "managed-uploads"
    write_pdf(source_root / "001" / "0001" / "1.pdf")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("PDF_STORAGE_PATH", str(storage_root))

    db = database_factory()
    original_user = User(username="employee-1", password="hash", role="user")
    new_user = User(username="employee-2", password="hash", role="user")
    template = Template(name="NHOM TL", filename="nhom.xlsx")
    db.add_all([original_user, new_user, template])
    db.commit()
    original_user_id = original_user.id
    new_user_id = new_user.id
    job_ids = []
    for user_ids, reviewer_ids in (
        ([original_user_id], [new_user_id]),
        ([new_user_id], [original_user_id]),
    ):
        job = ServerFolderImportJob(
            created_by_user_id=original_user_id,
            template_id=template.id,
            source_relative_path="",
            grouping_level=1,
            user_ids_json=json.dumps(user_ids),
            status="queued",
        )
        add_job_reviewers(db, job, reviewer_ids)
        job_ids.append(job.id)
    db.close()
    process_server_folder_import(job_ids[0], session_factory=database_factory)
    db = database_factory()
    document = db.query(AssignedDocument).one()
    document.status = "completed"
    db.commit()
    db.close()

    process_server_folder_import(job_ids[1], session_factory=database_factory)

    db = database_factory()
    document = db.query(AssignedDocument).one()
    review_assignment = db.query(AssignedDocumentReviewAssignment).one()
    assert document.status == "completed"
    assert document.assigned_to_user_id == original_user_id
    assert review_assignment.reviewer_user_id == new_user_id
    assert db.query(AssignedDocument).count() == 1
    assert len(list(storage_root.iterdir())) == 1
    db.close()


def test_import_records_storage_error_when_every_document_fails(
    monkeypatch, tmp_path, database_factory
):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "managed-uploads"
    write_pdf(source_root / "001" / "0001" / "1.pdf")
    monkeypatch.setenv("DOCUMENT_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("PDF_STORAGE_PATH", str(storage_root))

    db = database_factory()
    input_user = User(username="input-storage-error", password="hash", role="user")
    reviewer = User(username="reviewer-storage-error", password="hash", role="user")
    template = Template(name="Mẫu lỗi lưu trữ", filename="storage-error.xlsx")
    db.add_all([input_user, reviewer, template])
    db.commit()
    job = ServerFolderImportJob(
        created_by_user_id=input_user.id,
        template_id=template.id,
        source_relative_path="",
        grouping_level=2,
        user_ids_json=json.dumps([input_user.id]),
        status="queued",
    )
    add_job_reviewers(db, job, [reviewer.id])
    job_id = job.id
    db.close()

    def deny_storage_write(*_args, **_kwargs):
        raise PermissionError("Access is denied: managed storage")

    monkeypatch.setattr(
        "server.services.server_folder_service.save_validated_upload",
        deny_storage_write,
    )
    process_server_folder_import(job_id, session_factory=database_factory)

    db = database_factory()
    finished_job = db.query(ServerFolderImportJob).filter_by(id=job_id).one()
    assert finished_job.status == "failed"
    assert finished_job.processed_files == 1
    assert finished_job.imported_files == 0
    assert finished_job.failed_files == 1
    assert "001/0001/1.pdf" in finished_job.error_message
    assert "Access is denied: managed storage" in finished_job.error_message
    assert db.query(AssignedDocument).count() == 0
    db.close()
