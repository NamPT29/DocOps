from datetime import datetime, timedelta
import json

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentReviewAssignment,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
)
from server.routers import submissions
from server.services.submission_metadata_service import (
    backfill_submission_metadata,
    ensure_submission_metadata_schema,
    folder_path_key,
)


def test_legacy_metadata_migration_preserves_every_submission_value(tmp_path):
    database_path = tmp_path / "legacy-submissions.sqlite3"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    original_json = {
        1: '{  "col_8": "Hồ sơ đang nhập", "_pdf_uuid": "uuid-001.pdf"  }',
        2: '{"col_8":"Hồ sơ đã nhận","custom":{"kept":true}}',
        3: '{"col_8":"PDF cũ","_pdf_filename":"missing.pdf"}',
    }
    original_statuses = {1: "draft", 2: "pending_review", 3: "approved"}

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE assigned_documents (
                id INTEGER PRIMARY KEY,
                original_filename VARCHAR(255),
                uuid_filename VARCHAR(255),
                assigned_to_user_id INTEGER,
                template_id INTEGER,
                status VARCHAR(255),
                created_at DATETIME
            )
        """))
        connection.execute(text("""
            CREATE TABLE assigned_document_folders (
                id INTEGER PRIMARY KEY,
                document_id INTEGER,
                folder_group VARCHAR(1024),
                created_at DATETIME
            )
        """))
        connection.execute(text("""
            CREATE TABLE submissions (
                id INTEGER PRIMARY KEY,
                data_json TEXT,
                template_id INTEGER,
                created_at DATETIME,
                created_by_user_id INTEGER,
                is_checked BOOLEAN,
                status VARCHAR(50)
            )
        """))
        connection.execute(text("""
            INSERT INTO assigned_documents (
                id, original_filename, uuid_filename, assigned_to_user_id,
                status, created_at
            ) VALUES (
                11, '001.pdf', 'uuid-001.pdf', 7,
                'pending', '2026-08-14 01:02:03'
            )
        """))
        connection.execute(text("""
            INSERT INTO assigned_document_folders (
                id, document_id, folder_group, created_at
            ) VALUES (
                21, 11, '00000000/004/0011', '2026-08-14 01:02:03'
            )
        """))
        for submission_id in original_json:
            connection.execute(text("""
                INSERT INTO submissions (
                    id, data_json, created_at, created_by_user_id,
                    is_checked, status
                ) VALUES (
                    :id, :data_json, :created_at, 7, :is_checked, :status
                )
            """), {
                "id": submission_id,
                "data_json": original_json[submission_id],
                "created_at": f"2026-08-14 0{submission_id}:02:03",
                "is_checked": submission_id == 3,
                "status": original_statuses[submission_id],
            })

    ensure_submission_metadata_schema(engine)
    schema = inspect(engine)
    column_names = {column["name"] for column in schema.get_columns("submissions")}
    index_names = {index["name"] for index in schema.get_indexes("submissions")}
    assert {
        "assigned_document_id",
        "folder_path",
        "folder_path_key",
    }.issubset(column_names)
    assert {
        "ix_submissions_assigned_document_id",
        "ix_submissions_folder_path_key",
    }.issubset(index_names)

    db = sessionmaker(bind=engine)()
    try:
        before = {
            row.id: (row.data_json, row.status, row.created_at, row.is_checked)
            for row in db.query(Submission).order_by(Submission.id).all()
        }
        result = backfill_submission_metadata(db, batch_size=1)
        after = {
            row.id: (row.data_json, row.status, row.created_at, row.is_checked)
            for row in db.query(Submission).order_by(Submission.id).all()
        }

        assert before == after
        assert {row_id: values[0] for row_id, values in after.items()} == original_json
        assert {row_id: values[1] for row_id, values in after.items()} == original_statuses
        assert db.query(Submission).count() == 3
        linked = db.get(Submission, 1)
        assert linked.assigned_document_id == 11
        assert linked.folder_path == "00000000/004/0011"
        assert linked.folder_path_key == folder_path_key("00000000/004/0011")
        assert result == {
            "updated": 3,
            "unresolved_documents": 1,
            "invalid_json": 0,
        }
        assert backfill_submission_metadata(db) == {
            "updated": 0,
            "unresolved_documents": 0,
            "invalid_json": 0,
        }
    finally:
        db.close()
        engine.dispose()


def test_folder_listing_and_pagination_have_bounded_sql_queries(tmp_path):
    database_path = tmp_path / "query-count.sqlite3"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        author = User(username="metadata-author", password="hash", role="user")
        template = Template(name="Mẫu metadata", filename="metadata.xlsx")
        db.add_all([author, template])
        db.flush()
        author_id = author.id
        template_id = template.id
        document = AssignedDocument(
            original_filename="001.pdf",
            uuid_filename="uuid-metadata-001.pdf",
            assigned_to_user_id=author_id,
            template_id=template_id,
            status="completed",
        )
        db.add(document)
        db.flush()
        document_id = document.id
        folder = "00000000/004/0011"
        db.add(AssignedDocumentFolder(
            document_id=document_id,
            folder_group=folder,
        ))
        started_at = datetime(2026, 8, 14, 1, 0, 0)
        for index in range(120):
            db.add(Submission(
                data_json=f'{{"col_8":"Hồ sơ {index}","_pdf_uuid":"uuid-metadata-001.pdf"}}',
                template_id=template_id,
                created_by_user_id=author_id,
                assigned_document_id=document_id,
                folder_path=folder,
                folder_path_key=folder_path_key(folder),
                status="approved",
                created_at=started_at + timedelta(seconds=index),
            ))
        db.commit()

        statements = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_statement)
        page = submissions.api_get_submissions(
            template_id=template_id,
            status="approved",
            folder_path=folder,
            page=2,
            page_size=20,
            current_user={"id": 1, "role": "admin"},
            db=db,
        )
        page_statements = list(statements)
        statements.clear()
        completed_folders = submissions.api_get_completed_folders(
            template_id=template_id,
            current_user={"id": 1, "role": "admin"},
            db=db,
        )
        folder_statements = list(statements)
        event.remove(engine, "before_cursor_execute", record_statement)

        assert page["pagination"] == {
            "page": 2,
            "page_size": 20,
            "total": 120,
            "total_pages": 6,
            "from": 21,
            "to": 40,
        }
        assert len(page["data"]) == 20
        assert len(page_statements) <= 8
        assert any(
            " LIMIT " in statement.upper() and " OFFSET " in statement.upper()
            for statement in page_statements
        )
        assert completed_folders["data"][0]["approved_count"] == 120
        assert len(folder_statements) <= 5
    finally:
        db.close()
        engine.dispose()


def test_new_draft_stores_indexed_metadata_and_keeps_dynamic_form_data(tmp_path):
    database_path = tmp_path / "new-draft.sqlite3"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        author = User(username="new-draft-author", password="hash", role="user")
        db.add(author)
        db.flush()
        author_id = author.id
        document = AssignedDocument(
            original_filename="0000130.pdf",
            uuid_filename="uuid-0000130.pdf",
            assigned_to_user_id=author_id,
            status="pending",
        )
        db.add(document)
        db.flush()
        document_id = document.id
        folder = "00000000/004/0011"
        db.add(AssignedDocumentFolder(
            document_id=document_id,
            folder_group=folder,
        ))
        db.commit()

        request_data = {
            "col_8": "Dữ liệu động phải được giữ nguyên",
            "custom_field": {"nested": [1, 2, 3]},
            "_pdf_uuid": "uuid-0000130.pdf",
        }
        result = submissions.api_submit(
            submissions.SubmitRequest(data=request_data, status="draft"),
            current_user={"id": author_id, "role": "user"},
            db=db,
        )

        stored = db.query(Submission).one()
        stored_data = json.loads(stored.data_json)
        assert result == {"status": "ok"}
        assert stored_data["col_8"] == request_data["col_8"]
        assert stored_data["custom_field"] == request_data["custom_field"]
        assert stored.assigned_document_id == document_id
        assert stored.folder_path == folder
        assert stored.folder_path_key == folder_path_key(folder)
        assert stored.status == "draft"
    finally:
        db.close()
        engine.dispose()


def test_review_folder_queries_do_not_grow_with_submission_count(tmp_path):
    database_path = tmp_path / "review-query-count.sqlite3"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        author = User(username="review-author", password="hash", role="user")
        reviewer = User(username="reviewer", password="hash", role="user")
        template = Template(name="Mẫu kiểm tra", filename="review.xlsx")
        db.add_all([author, reviewer, template])
        db.flush()
        author_id = author.id
        reviewer_id = reviewer.id
        template_id = template.id
        folder = "00000000/004/0012"
        document = AssignedDocument(
            original_filename="review.pdf",
            uuid_filename="uuid-review.pdf",
            assigned_to_user_id=author_id,
            template_id=template_id,
            status="completed",
        )
        db.add(document)
        db.flush()
        document_id = document.id
        db.add_all([
            AssignedDocumentFolder(
                document_id=document_id,
                folder_group=folder,
            ),
            AssignedDocumentReviewAssignment(
                document_id=document_id,
                reviewer_user_id=reviewer_id,
            ),
        ])
        started_at = datetime(2026, 8, 14, 2, 0, 0)
        for index in range(80):
            record = Submission(
                data_json=f'{{"col_8":"Chờ kiểm tra {index}","_pdf_uuid":"uuid-review.pdf"}}',
                template_id=template_id,
                created_by_user_id=author_id,
                assigned_document_id=document_id,
                folder_path=folder,
                folder_path_key=folder_path_key(folder),
                status="pending_review",
                created_at=started_at + timedelta(seconds=index),
            )
            db.add(record)
            db.flush()
            db.add(SubmissionReviewAssignment(
                submission_id=record.id,
                reviewer_user_id=reviewer_id,
            ))
        db.commit()

        statements = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_statement)
        folders = submissions.api_get_review_folders(
            template_id=template_id,
            current_user={"id": reviewer_id, "role": "user"},
            db=db,
        )
        folder_statements = list(statements)
        statements.clear()
        queue = submissions.api_get_review_folder_submissions(
            folder_path=folder,
            template_id=template_id,
            current_user={"id": reviewer_id, "role": "user"},
            db=db,
        )
        queue_statements = list(statements)
        event.remove(engine, "before_cursor_execute", record_statement)

        assert folders["data"][0]["submitted_count"] == 80
        assert len(folder_statements) <= 8
        assert len(queue["data"]) == 80
        assert len(queue_statements) <= 11
    finally:
        db.close()
        engine.dispose()
