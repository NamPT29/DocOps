import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewAssignment,
    Template,
    User,
)
from server.services.submission_service import SubmissionService
from server.utils.folder_utils import folder_path_key


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _select_count(engine, action) -> int:
    statements: list[str] = []

    def record_select(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_select)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", record_select)
    return len(statements)


def _seed_bulk(session, count: int, *, document_status: str = "pending"):
    author = User(username=f"author-{count}-{document_status}", password="hash", role="user")
    reviewer = User(username=f"reviewer-{count}-{document_status}", password="hash", role="user")
    template = Template(
        name="Mẫu query count",
        filename=f"query-{count}-{document_status}.xlsx",
        config_json=json.dumps({"required_cols": [1]}),
    )
    session.add_all([author, reviewer, template])
    session.flush()
    documents = []
    submissions = []
    for index in range(count):
        document = AssignedDocument(
            original_filename=f"query-{document_status}-{count}-{index}.pdf",
            uuid_filename=f"uuid-query-{document_status}-{count}-{index}.pdf",
            assigned_to_user_id=author.id,
            template_id=template.id,
            status=document_status,
        )
        session.add(document)
        session.flush()
        folder = f"batch/{index}"
        session.add_all([
            AssignedDocumentPath(
                document_id=document.id,
                relative_path=f"{folder}/document.pdf",
                upload_id=f"upload-{document_status}-{count}-{index}",
            ),
            AssignedDocumentFolder(document_id=document.id, folder_group=folder),
            AssignedDocumentReviewAssignment(
                document_id=document.id,
                reviewer_user_id=reviewer.id,
            ),
        ])
        submission = Submission(
            data_json=json.dumps({
                "col_0": f"value-{index}",
                "_pdf_uuid": document.uuid_filename,
            }),
            template_id=template.id,
            created_by_user_id=author.id,
            assigned_document_id=document.id,
            folder_path=folder,
            folder_path_key=folder_path_key(folder),
            status="draft",
        )
        session.add(submission)
        documents.append(document)
        submissions.append(submission)
    session.commit()
    return (
        {"id": author.id, "username": author.username, "role": author.role},
        [submission.id for submission in submissions],
        [document.id for document in documents],
    )


def _bulk_submit_selects(count: int) -> int:
    engine, session = _session()
    try:
        current_user, submission_ids, _ = _seed_bulk(session, count)
        selects = _select_count(
            engine,
            lambda: SubmissionService.bulk_submission_action(
                session,
                "submit_for_review",
                submission_ids,
                current_user,
            ),
        )
        assert session.query(Submission).filter(
            Submission.id.in_(submission_ids),
            Submission.status == "pending_review",
        ).count() == count
        assert session.query(SubmissionReviewAssignment).filter(
            SubmissionReviewAssignment.submission_id.in_(submission_ids),
        ).count() == count
        assert session.query(SubmissionQualityAssessment).filter(
            SubmissionQualityAssessment.submission_id.in_(submission_ids),
        ).count() == count
        return selects
    finally:
        session.close()
        engine.dispose()


def _bulk_delete_selects(count: int) -> int:
    engine, session = _session()
    try:
        current_user, submission_ids, document_ids = _seed_bulk(
            session,
            count,
            document_status="completed",
        )
        selects = _select_count(
            engine,
            lambda: SubmissionService.bulk_submission_action(
                session,
                "delete",
                submission_ids,
                current_user,
            ),
        )
        assert session.query(Submission).filter(
            Submission.id.in_(submission_ids)
        ).count() == 0
        assert {
            status
            for (status,) in session.query(AssignedDocument.status).filter(
                AssignedDocument.id.in_(document_ids)
            ).all()
        } == {"pending"}
        return selects
    finally:
        session.close()
        engine.dispose()


def _duplicate_selects(candidate_count: int) -> int:
    engine, session = _session()
    try:
        template = Template(
            name="Mẫu duplicate query count",
            filename=f"duplicate-query-{candidate_count}.xlsx",
            config_json=json.dumps({
                "linked_pdf_path": {"enabled": True, "col": 1},
            }),
        )
        session.add(template)
        session.flush()
        folder = "duplicate/scope"
        draft = Submission(
            data_json=json.dumps({"col_0": "duplicate/report.pdf"}),
            template_id=template.id,
            folder_path=folder,
            folder_path_key=folder_path_key(folder),
            status="draft",
        )
        session.add(draft)
        session.add_all([
            Submission(
                data_json=json.dumps({"col_0": "duplicate/report.pdf"}),
                template_id=template.id,
                folder_path=folder,
                folder_path_key=folder_path_key(folder),
                status="pending_review",
            )
            for _ in range(candidate_count)
        ])
        session.commit()
        data = json.loads(draft.data_json)
        result: list[int] = []
        selects = _select_count(
            engine,
            lambda: result.append(
                SubmissionService.exact_duplicate_count(draft, data, session)
            ),
        )
        assert result == [candidate_count]
        return selects
    finally:
        session.close()
        engine.dispose()


def test_bulk_submit_select_count_is_bounded():
    one = _bulk_submit_selects(1)
    ten = _bulk_submit_selects(10)
    assert ten <= one + 2
    assert ten <= 15


def test_bulk_delete_select_count_is_bounded():
    one = _bulk_delete_selects(1)
    ten = _bulk_delete_selects(10)
    assert ten <= one + 1
    assert ten <= 6


def test_duplicate_candidate_scan_does_not_query_per_candidate():
    one = _duplicate_selects(1)
    ten = _duplicate_selects(10)
    assert ten == one
    assert ten <= 2


def test_bulk_submit_duplicate_conflict_remains_atomic():
    engine, session = _session()
    try:
        current_user, submission_ids, _ = _seed_bulk(session, 10)
        conflict = session.get(Submission, submission_ids[-1])
        conflict_data = json.loads(conflict.data_json)
        conflict_data["_pdf_relative_path"] = "batch/9/document.pdf"
        existing = Submission(
            data_json=json.dumps(conflict_data),
            template_id=conflict.template_id,
            folder_path=conflict.folder_path,
            folder_path_key=conflict.folder_path_key,
            status="pending_review",
        )
        session.add(existing)
        session.commit()

        with pytest.raises(HTTPException) as error:
            SubmissionService.bulk_submission_action(
                session,
                "submit_for_review",
                submission_ids,
                current_user,
            )
        session.rollback()

        assert error.value.status_code == 409
        assert error.value.detail["code"] == "duplicate_submission"
        assert {
            status
            for (status,) in session.query(Submission.status).filter(
                Submission.id.in_(submission_ids)
            ).all()
        } == {"draft"}
        assert session.query(SubmissionReviewAssignment).filter(
            SubmissionReviewAssignment.submission_id.in_(submission_ids),
        ).count() == 0
    finally:
        session.close()
        engine.dispose()
