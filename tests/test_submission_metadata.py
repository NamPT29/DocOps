from datetime import datetime, timedelta
import json

from sqlalchemy import create_engine, event
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
from server.utils.folder_utils import folder_path_key


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
                status="completed",
                created_at=started_at + timedelta(seconds=index),
            ))
        db.commit()

        statements = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_statement)
        page = submissions.api_get_submissions(
            template_id=template_id,
            status="completed",
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
        # One fixed query loads quality metadata for the whole page; this must
        # remain bounded rather than growing with the number of submissions.
        assert len(page_statements) <= 9
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
            page_size=100,
            current_user={"id": reviewer_id, "role": "user"},
            db=db,
        )
        queue_statements = list(statements)
        event.remove(engine, "before_cursor_execute", record_statement)

        assert folders["data"][0]["submitted_count"] == 80
        assert len(folder_statements) <= 8
        assert len(queue["data"]) == 80
        assert queue["pagination"]["total"] == 80
        assert len(queue_statements) <= 15
    finally:
        db.close()
        engine.dispose()
