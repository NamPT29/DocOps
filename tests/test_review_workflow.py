from datetime import datetime, timedelta, timezone

import asyncio
import json

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
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
from server.routers import auth, submissions
from server.routers.documents import (
    RedistributeFolderReviewersRequest,
    RevokeAssignmentsRequest,
    get_user_assignment_folders,
    get_reviewer_folder_assignments,
    get_document_stats,
    redistribute_folder_reviewers,
    revoke_user_assignments,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'review.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_user(db, username, *, role="user"):
    user = User(username=username, password="hash", role=role)
    db.add(user)
    db.commit()
    return user


def assign_document(db, input_user, reviewer=None, *, filename="document.pdf"):
    document = AssignedDocument(
        original_filename=filename,
        uuid_filename=f"uuid-{filename}",
        assigned_to_user_id=input_user.id,
        status="pending",
    )
    db.add(document)
    db.flush()
    if reviewer:
        db.add(
            AssignedDocumentReviewAssignment(
                document_id=document.id,
                reviewer_user_id=reviewer.id,
            )
        )
    db.commit()
    return document


def current_user(user):
    return {"id": user.id, "username": user.username, "role": user.role}


def test_excel_export_includes_only_approved_submissions(db, mocker):
    template = Template(name="Mẫu xuất duyệt", filename="approved-export.xlsx")
    db.add(template)
    db.flush()
    records = []
    for status in ("draft", "pending_review", "rejected", "approved"):
        record = Submission(
            template_id=template.id,
            data_json=f'{{"col_0": "{status}"}}',
            status=status,
        )
        db.add(record)
        records.append(record)
    db.commit()

    export_call = mocker.patch(
        "server.routers.submissions.run_in_threadpool",
        new=mocker.AsyncMock(return_value=None),
    )
    mocker.patch(
        "server.routers.submissions.FileResponse",
        return_value={"status": "file-ready"},
    )

    result = asyncio.run(submissions.api_export(
        template.id,
        BackgroundTasks(),
        current_user={"id": 1, "role": "admin"},
        db=db,
    ))

    assert result == {"status": "file-ready"}
    exported_submissions = export_call.await_args.args[2]
    assert [submission.id for submission in exported_submissions] == [records[-1].id]
    assert {submission.status for submission in exported_submissions} == {"approved"}


def test_excel_export_rejects_template_without_approved_submissions(db, mocker):
    template = Template(name="Mẫu chưa duyệt", filename="not-approved.xlsx")
    db.add(template)
    db.flush()
    db.add(Submission(
        template_id=template.id,
        data_json='{"col_0": "pending"}',
        status="pending_review",
    ))
    db.commit()
    export_call = mocker.patch(
        "server.routers.submissions.run_in_threadpool",
        new=mocker.AsyncMock(return_value=None),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(submissions.api_export(
            template.id,
            BackgroundTasks(),
            current_user={"id": 1, "role": "admin"},
            db=db,
        ))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Không có hồ sơ đã duyệt để xuất báo cáo cho biểu mẫu này."
    export_call.assert_not_awaited()


def test_completed_folders_filter_approved_submissions_and_excel_by_folder(db, mocker):
    author = add_user(db, "completed-author")
    template = Template(name="Mẫu hồ sơ folder", filename="completed-folder.xlsx")
    db.add(template)
    db.flush()

    first_document = assign_document(db, author, filename="first-approved.pdf")
    second_document = assign_document(db, author, filename="second-approved.pdf")
    pending_document = assign_document(db, author, filename="pending.pdf")
    first_document.template_id = template.id
    second_document.template_id = template.id
    pending_document.template_id = template.id
    db.add_all([
        AssignedDocumentFolder(
            document_id=first_document.id,
            folder_group="00000000/004/0011",
        ),
        AssignedDocumentFolder(
            document_id=second_document.id,
            folder_group="00000000/004/0012",
        ),
        AssignedDocumentFolder(
            document_id=pending_document.id,
            folder_group="00000000/004/0011",
        ),
    ])
    first_approved = Submission(
        template_id=template.id,
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{first_document.uuid_filename}"}}',
        status="approved",
    )
    second_approved = Submission(
        template_id=template.id,
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{second_document.uuid_filename}"}}',
        status="approved",
    )
    pending = Submission(
        template_id=template.id,
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{pending_document.uuid_filename}"}}',
        status="pending_review",
    )
    db.add_all([first_approved, second_approved, pending])
    db.commit()

    folders = submissions.api_get_completed_folders(
        template_id=template.id,
        current_user={"id": 1, "role": "admin"},
        db=db,
    )
    rows = {item["folder_path"]: item for item in folders["data"]}
    selected = submissions.api_get_submissions(
        template_id=template.id,
        status="approved",
        folder_path="00000000/004/0011",
        page=1,
        page_size=20,
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert rows["00000000/004/0011"]["approved_count"] == 1
    assert rows["00000000/004/0012"]["approved_count"] == 1
    assert selected["pagination"]["total"] == 1
    assert [item["id"] for item in selected["data"]] == [first_approved.id]

    export_call = mocker.patch(
        "server.routers.submissions.run_in_threadpool",
        new=mocker.AsyncMock(return_value=None),
    )
    mocker.patch(
        "server.routers.submissions.FileResponse",
        return_value={"status": "file-ready"},
    )
    result = asyncio.run(submissions.api_export(
        template.id,
        BackgroundTasks(),
        folder_path="00000000/004/0011",
        current_user={"id": 1, "role": "admin"},
        db=db,
    ))

    assert result == {"status": "file-ready"}
    assert [item.id for item in export_call.await_args.args[2]] == [first_approved.id]


def test_completed_folders_keep_approved_legacy_records_without_folder(db):
    author = add_user(db, "legacy-completed-author")
    legacy = Submission(
        created_by_user_id=author.id,
        data_json='{"col_8": "Hồ sơ cũ"}',
        status="approved",
    )
    db.add(legacy)
    db.commit()

    folders = submissions.api_get_completed_folders(
        current_user={"id": 1, "role": "admin"},
        db=db,
    )
    selected = submissions.api_get_submissions(
        status="approved",
        folder_path=submissions.COMPLETED_WITHOUT_FOLDER,
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert folders["data"][0]["folder_path"] == submissions.COMPLETED_WITHOUT_FOLDER
    assert folders["data"][0]["folder_name"] == "Chưa xác định folder"
    assert folders["data"][0]["approved_count"] == 1
    assert [item["id"] for item in selected["data"]] == [legacy.id]


def test_completed_root_folder_keeps_root_folder_metadata(db):
    author = add_user(db, "root-completed-author")
    document = assign_document(db, author, filename="root-approved.pdf")
    db.add(AssignedDocumentFolder(
        document_id=document.id,
        folder_group="__ROOT__",
    ))
    approved = Submission(
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{document.uuid_filename}"}}',
        status="approved",
    )
    db.add(approved)
    db.commit()

    selected = submissions.api_get_submissions(
        status="approved",
        folder_path="__ROOT__",
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert selected["pagination"]["total"] == 1
    assert selected["data"][0]["folder_path"] == "__ROOT__"
    assert selected["data"][0]["folder_name"] == "Thư mục gốc"


def test_entered_submissions_are_paginated_newest_first_with_continuous_numbers(db):
    author = add_user(db, "author")
    other_author = add_user(db, "other-author")
    created_ids = []
    created_at = datetime(2026, 8, 13, 8, 0, 0)

    for offset in range(5):
        submission = Submission(
            data_json=f'{{"col_8": "Hồ sơ {offset + 1}"}}',
            created_by_user_id=author.id,
            status="draft",
            created_at=created_at + timedelta(minutes=offset),
        )
        db.add(submission)
        db.flush()
        created_ids.append(submission.id)

    db.add(Submission(
        data_json='{"col_8": "Không thuộc người nhập"}',
        created_by_user_id=other_author.id,
        status="draft",
        created_at=created_at + timedelta(hours=1),
    ))
    db.commit()

    first_page = submissions.api_get_submissions(
        page=1,
        page_size=2,
        current_user=current_user(author),
        db=db,
    )
    second_page = submissions.api_get_submissions(
        page=2,
        page_size=2,
        current_user=current_user(author),
        db=db,
    )
    last_page = submissions.api_get_submissions(
        page=3,
        page_size=2,
        current_user=current_user(author),
        db=db,
    )

    assert first_page["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 5,
        "total_pages": 3,
        "from": 1,
        "to": 2,
    }
    assert [item["id"] for item in first_page["data"]] == created_ids[4:2:-1]
    assert [item["serial_number"] for item in first_page["data"]] == [1, 2]
    assert [item["id"] for item in second_page["data"]] == created_ids[2:0:-1]
    assert [item["serial_number"] for item in second_page["data"]] == [3, 4]
    assert [item["id"] for item in last_page["data"]] == [created_ids[0]]
    assert [item["serial_number"] for item in last_page["data"]] == [5]


def test_copied_submission_uses_current_utc_time(db):
    author = add_user(db, "copy-author")
    original = Submission(
        data_json='{"col_8": "Hồ sơ gốc"}',
        created_by_user_id=author.id,
        status="draft",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    db.add(original)
    db.commit()

    before_copy = datetime.now(timezone.utc).replace(tzinfo=None)
    result = submissions.api_copy_submission(
        original.id,
        current_user=current_user(author),
        db=db,
    )
    after_copy = datetime.now(timezone.utc).replace(tzinfo=None)
    copied = db.query(Submission).filter(Submission.id == result["new_id"]).one()

    assert result["status"] == "ok"
    assert copied.created_at > original.created_at
    assert before_copy <= copied.created_at <= after_copy


def test_saving_copied_draft_refreshes_its_current_utc_time(db):
    author = add_user(db, "save-copy-author")
    copied_draft = Submission(
        data_json='{"col_8": "Dữ liệu bản sao"}',
        created_by_user_id=author.id,
        status="draft",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    db.add(copied_draft)
    db.commit()

    before_save = datetime.now(timezone.utc).replace(tzinfo=None)
    result = submissions.api_update_submission(
        copied_draft.id,
        submissions.SubmitRequest(
            data={"col_8": "Dữ liệu vừa nhập"},
            status="draft",
        ),
        current_user=current_user(author),
        db=db,
    )
    after_save = datetime.now(timezone.utc).replace(tzinfo=None)

    db.refresh(copied_draft)
    assert result == {"status": "ok"}
    assert before_save <= copied_draft.created_at <= after_save


def test_capabilities_are_derived_from_document_assignments(db):
    admin = add_user(db, "admin", role="admin")
    dual_role_employee = add_user(db, "dual")
    reviewer = add_user(db, "reviewer")
    another_input = add_user(db, "another-input")

    assert auth.get_user_capability_profile(admin, db) == {
        "can_input": True,
        "can_review": True,
        "roles": ["admin", "input", "reviewer"],
    }
    assert auth.get_user_capability_profile(dual_role_employee, db) == {
        "can_input": False,
        "can_review": False,
        "roles": [],
    }

    own_document = assign_document(db, dual_role_employee, reviewer, filename="own.pdf")
    other_document = assign_document(db, another_input, dual_role_employee, filename="other.pdf")

    assert own_document.assigned_to_user_id == dual_role_employee.id
    assert other_document.assigned_to_user_id != dual_role_employee.id
    assert auth.get_user_capability_profile(dual_role_employee, db) == {
        "can_input": True,
        "can_review": True,
        "roles": ["input", "reviewer"],
    }


def test_new_account_has_no_fixed_role_and_inventory_lists_all_employees(db):
    admin = add_user(db, "admin", role="admin")
    existing = add_user(db, "existing")

    result = auth.api_create_user(
        auth.CreateUserRequest(username="new-user", password="password123"),
        current_user=current_user(admin),
        db=db,
    )
    stats = get_document_stats(current_user=current_user(admin), db=db)
    me = auth.api_get_me(current_user={"id": result["user"]["id"]}, db=db)

    assert result["user"]["roles"] == []
    assert result["user"]["can_input"] is False
    assert result["user"]["can_review"] is False
    assert {item["user_id"] for item in stats["user_stats"]} == {
        existing.id,
        result["user"]["id"],
    }
    assert me["user"]["roles"] == []


@pytest.mark.parametrize("submission_status", ["draft", "pending_review", "rejected", "approved"])
def test_admin_lists_and_revokes_one_input_folder_while_preserving_other_folders(
    db,
    submission_status,
):
    admin = add_user(db, "admin", role="admin")
    employee = add_user(db, "employee")
    reviewer = add_user(db, "reviewer")
    blocked_first = assign_document(db, employee, reviewer, filename="blocked-first.pdf")
    blocked_second = assign_document(db, employee, reviewer, filename="blocked-second.pdf")
    revocable_first = assign_document(db, employee, reviewer, filename="revocable-first.pdf")
    revocable_second = assign_document(db, employee, reviewer, filename="revocable-second.pdf")
    other_folder = assign_document(db, employee, reviewer, filename="other-folder.pdf")
    db.add_all([
        AssignedDocumentFolder(
            document_id=blocked_first.id,
            folder_group="00000000/004/0011",
        ),
        AssignedDocumentFolder(
            document_id=blocked_second.id,
            folder_group="00000000/004/0011",
        ),
        AssignedDocumentFolder(
            document_id=revocable_first.id,
            folder_group="00000000/004/0012",
        ),
        AssignedDocumentFolder(
            document_id=revocable_second.id,
            folder_group="00000000/004/0012",
        ),
        AssignedDocumentFolder(
            document_id=other_folder.id,
            folder_group="00000000/004/0013",
        ),
        Submission(
            data_json=f'{{"_pdf_uuid": "{blocked_first.uuid_filename}"}}',
            created_by_user_id=employee.id,
            status=submission_status,
        ),
    ])
    db.commit()

    listing = get_user_assignment_folders(
        user_id=employee.id,
        current_user=current_user(admin),
        db=db,
    )
    folders = {item["folder_path"]: item for item in listing["data"]}
    assert listing["folder_count"] == 3
    assert folders["00000000/004/0011"]["can_revoke"] is False
    assert folders["00000000/004/0011"]["submission_count"] == 1
    assert folders["00000000/004/0012"]["can_revoke"] is True
    assert folders["00000000/004/0012"]["document_count"] == 2

    result = revoke_user_assignments(
        RevokeAssignmentsRequest(
            user_id=employee.id,
            assignment_type="input",
            folder_path="00000000/004/0012",
        ),
        current_user=current_user(admin),
        db=db,
    )

    db.expire_all()
    assert result["input_revoked"] == 2
    assert result["input_folders_revoked"] == 1
    assert result["input_folders_blocked"] == 0
    assert result["drafts_blocked"] == 0
    assert result["review_reservations_revoked"] == 2
    for document in (revocable_first, revocable_second):
        assert db.get(AssignedDocument, document.id).assigned_to_user_id is None
        assert db.query(AssignedDocumentReviewAssignment).filter_by(
            document_id=document.id
        ).first() is None
    for document in (blocked_first, blocked_second):
        assert db.get(AssignedDocument, document.id).assigned_to_user_id == employee.id
        assert db.query(AssignedDocumentReviewAssignment).filter_by(
            document_id=document.id
        ).one().reviewer_user_id == reviewer.id
    assert db.get(AssignedDocument, other_folder.id).assigned_to_user_id == employee.id

    with pytest.raises(HTTPException) as blocked_error:
        revoke_user_assignments(
            RevokeAssignmentsRequest(
                user_id=employee.id,
                assignment_type="input",
                folder_path="00000000/004/0011",
            ),
            current_user=current_user(admin),
            db=db,
        )
    assert blocked_error.value.status_code == 409


def test_admin_input_revoke_requires_a_specific_folder(db):
    admin = add_user(db, "admin", role="admin")
    employee = add_user(db, "employee")

    with pytest.raises(HTTPException) as error:
        revoke_user_assignments(
            RevokeAssignmentsRequest(user_id=employee.id, assignment_type="input"),
            current_user=current_user(admin),
            db=db,
        )

    assert error.value.status_code == 400


def test_admin_revokes_reviewer_work_and_takes_over_active_submissions(db):
    admin = add_user(db, "admin", role="admin")
    employee = add_user(db, "employee")
    reviewer = add_user(db, "reviewer")
    reserved = assign_document(db, employee, reviewer, filename="reserved.pdf")
    active_documents = []
    submissions_by_status = {}
    for status in ("pending_review", "rejected", "approved"):
        document = assign_document(db, employee, reviewer, filename=f"{status}.pdf")
        document.status = "completed"
        submission = Submission(
            data_json=f'{{"_pdf_uuid": "{document.uuid_filename}"}}',
            created_by_user_id=employee.id,
            status=status,
        )
        db.add(submission)
        db.flush()
        db.add(
            SubmissionReviewAssignment(
                submission_id=submission.id,
                reviewer_user_id=reviewer.id,
            )
        )
        active_documents.append(document)
        submissions_by_status[status] = submission
    db.commit()

    before = get_document_stats(current_user=current_user(admin), db=db)
    reviewer_stats = next(
        item for item in before["user_stats"] if item["user_id"] == reviewer.id
    )
    result = revoke_user_assignments(
        RevokeAssignmentsRequest(user_id=reviewer.id, assignment_type="reviewer"),
        current_user=current_user(admin),
        db=db,
    )

    db.expire_all()
    assert reviewer_stats["review_pending"] == 3
    assert result["review_reservations_revoked"] == 1
    assert result["reviews_transferred_to_admin"] == 2
    assert db.query(AssignedDocumentReviewAssignment).filter_by(
        document_id=reserved.id
    ).first() is None
    for status in ("pending_review", "rejected"):
        assignment = db.query(SubmissionReviewAssignment).filter_by(
            submission_id=submissions_by_status[status].id
        ).one()
        assert assignment.reviewer_user_id == admin.id
    approved_assignment = db.query(SubmissionReviewAssignment).filter_by(
        submission_id=submissions_by_status["approved"].id
    ).one()
    assert approved_assignment.reviewer_user_id == reviewer.id
    for document in active_documents[:2]:
        assert db.query(AssignedDocumentReviewAssignment).filter_by(
            document_id=document.id
        ).one().reviewer_user_id == admin.id


def test_admin_redistributes_review_work_evenly_by_whole_folder(db):
    admin = add_user(db, "admin", role="admin")
    input_user = add_user(db, "input-user")
    old_reviewer = add_user(db, "old-reviewer")
    reviewer_a = add_user(db, "reviewer-a")
    reviewer_b = add_user(db, "reviewer-b")
    documents = []
    for folder_number in range(4):
        for document_number in range(2):
            document = assign_document(
                db,
                input_user,
                old_reviewer,
                filename=f"folder-{folder_number}-{document_number}.pdf",
            )
            db.add(AssignedDocumentFolder(
                document_id=document.id,
                folder_group=f"00000000/004/{folder_number:04d}",
            ))
            documents.append(document)
    db.commit()

    result = redistribute_folder_reviewers(
        RedistributeFolderReviewersRequest(
            reviewer_user_ids=[reviewer_a.id, reviewer_b.id],
        ),
        current_user=current_user(admin),
        db=db,
    )

    db.expire_all()
    reviewer_by_folder = {}
    for document in documents:
        folder = db.query(AssignedDocumentFolder).filter_by(document_id=document.id).one()
        reviewer_id = db.query(AssignedDocumentReviewAssignment).filter_by(
            document_id=document.id,
        ).one().reviewer_user_id
        reviewer_by_folder.setdefault(folder.folder_group, set()).add(reviewer_id)
    assert result["folder_count"] == 4
    assert sorted(item["folder_count"] for item in result["distribution"]) == [2, 2]
    assert all(len(reviewer_ids) == 1 for reviewer_ids in reviewer_by_folder.values())
    assert {
        next(iter(reviewer_ids)) for reviewer_ids in reviewer_by_folder.values()
    } == {reviewer_a.id, reviewer_b.id}


def test_folder_redistribution_moves_active_submission_and_preserves_content(db):
    admin = add_user(db, "admin", role="admin")
    input_user = add_user(db, "input-user")
    old_reviewer = add_user(db, "old-reviewer")
    new_reviewer = add_user(db, "new-reviewer")
    document = assign_document(db, input_user, old_reviewer, filename="submitted.pdf")
    document.status = "completed"
    db.add(AssignedDocumentFolder(document_id=document.id, folder_group="00000000/005/0001"))
    submission = Submission(
        data_json=f'{{"_pdf_uuid": "{document.uuid_filename}", "field": "kept", "_wrong_sections": ["A"]}}',
        created_by_user_id=input_user.id,
        status="rejected",
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=old_reviewer.id,
    ))
    db.commit()

    folder_data = get_reviewer_folder_assignments(
        current_user=current_user(admin),
        db=db,
    )
    result = redistribute_folder_reviewers(
        RedistributeFolderReviewersRequest(reviewer_user_ids=[new_reviewer.id]),
        current_user=current_user(admin),
        db=db,
    )

    db.expire_all()
    assert folder_data["folder_count"] == 1
    assert folder_data["data"][0]["active_submission_count"] == 1
    assert result["submission_updates"] == 1
    assert db.query(SubmissionReviewAssignment).filter_by(
        submission_id=submission.id,
    ).one().reviewer_user_id == new_reviewer.id
    assert db.query(AssignedDocumentReviewAssignment).filter_by(
        document_id=document.id,
    ).one().reviewer_user_id == new_reviewer.id
    assert '"field": "kept"' in db.get(Submission, submission.id).data_json
    assert db.get(Submission, submission.id).status == "rejected"


def test_folder_redistribution_rejects_self_review_without_partial_updates(db):
    admin = add_user(db, "admin", role="admin")
    input_user = add_user(db, "input-user")
    old_reviewer = add_user(db, "old-reviewer")
    first = assign_document(db, input_user, old_reviewer, filename="first.pdf")
    second = assign_document(db, input_user, old_reviewer, filename="second.pdf")
    db.add_all([
        AssignedDocumentFolder(document_id=first.id, folder_group="004/0011"),
        AssignedDocumentFolder(document_id=second.id, folder_group="004/0012"),
    ])
    db.commit()

    with pytest.raises(HTTPException) as error:
        redistribute_folder_reviewers(
            RedistributeFolderReviewersRequest(reviewer_user_ids=[input_user.id]),
            current_user=current_user(admin),
            db=db,
        )

    assert error.value.status_code == 409
    assignments = db.query(AssignedDocumentReviewAssignment).order_by(
        AssignedDocumentReviewAssignment.document_id,
    ).all()
    assert [assignment.reviewer_user_id for assignment in assignments] == [
        old_reviewer.id,
        old_reviewer.id,
    ]


def test_submit_uses_document_reviewer_and_draft_is_hidden(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    document = assign_document(db, author, reviewer)
    db.add(AssignedDocumentFolder(
        document_id=document.id,
        folder_group="004/0011",
    ))
    db.commit()

    submissions.api_submit(
        submissions.SubmitRequest(
            data={"field": "draft", "_pdf_uuid": document.uuid_filename},
            status="draft",
        ),
        current_user=current_user(author),
        db=db,
    )
    assert db.query(SubmissionReviewAssignment).count() == 0

    submissions.api_submit(
        submissions.SubmitRequest(
            data={"field": "submitted", "_pdf_uuid": document.uuid_filename},
            status="pending_review",
        ),
        current_user=current_user(author),
        db=db,
    )

    rows = db.query(Submission).order_by(Submission.id).all()
    assignment = db.query(SubmissionReviewAssignment).one()
    queue = submissions.api_get_review_folder_submissions(
        folder_path="004/0011",
        current_user=current_user(reviewer),
        db=db,
    )

    assert rows[0].status == "draft"
    assert rows[1].status == "pending_review"
    assert assignment.submission_id == rows[1].id
    assert assignment.reviewer_user_id == reviewer.id
    assert [item["id"] for item in queue["data"]] == [rows[1].id]


def test_admin_reviews_unassigned_reports_and_shows_active_viewer(db):
    admin = add_user(db, 'admin', role='admin')
    author = add_user(db, 'author')
    reviewer = add_user(db, 'reviewer')
    assigned = Submission(
        data_json=json.dumps({'_folder_path': '004/0021'}),
        created_by_user_id=author.id,
        folder_path='004/0021',
        status='pending_review',
    )
    unassigned = Submission(
        data_json=json.dumps({'_folder_path': '004/0022'}),
        created_by_user_id=author.id,
        folder_path='004/0022',
        status='pending_review',
    )
    db.add_all([assigned, unassigned])
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=assigned.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    folders = submissions.api_get_review_folders(
        current_user=current_user(admin),
        db=db,
    )
    assert {item['folder_path'] for item in folders['data']} == {'004/0021', '004/0022'}

    queue = submissions.api_get_review_folder_submissions(
        folder_path='004/0022',
        current_user=current_user(admin),
        db=db,
    )
    assert [item['id'] for item in queue['data']] == [unassigned.id]
    assert submissions.api_get_submission(
        unassigned.id,
        current_user=current_user(admin),
        db=db,
    )['can_review'] is True

    corrected = submissions.api_update_review_content(
        unassigned.id,
        submissions.ReviewContentRequest(data={'field': 'admin corrected'}),
        current_user=current_user(admin),
        db=db,
    )
    assert corrected['status'] == 'ok'
    approved = submissions.api_toggle_check(
        unassigned.id,
        current_user=current_user(admin),
        db=db,
    )
    assert approved['new_status'] == 'approved'

    claimed = submissions.api_claim_submission_view(
        assigned.id,
        current_user=current_user(reviewer),
        db=db,
    )
    assert claimed['viewing_user_name'] == reviewer.username
    viewed_queue = submissions.api_get_review_folder_submissions(
        folder_path='004/0021',
        current_user=current_user(admin),
        db=db,
    )
    assert viewed_queue['data'][0]['is_being_viewed'] is True
    assert viewed_queue['data'][0]['viewing_user_name'] == reviewer.username

    released = submissions.api_release_submission_view(
        assigned.id,
        current_user=current_user(reviewer),
        db=db,
    )
    assert released == {'status': 'ok', 'released': True}


def test_admin_review_folder_submissions_are_paginated(db):
    admin = add_user(db, "review-pagination-admin", role="admin")
    template = Template(name="Mẫu phân trang kiểm duyệt", filename="review-pagination.xlsx")
    db.add(template)
    db.flush()
    records = []
    for offset in range(3):
        record = Submission(
            template_id=template.id,
            created_by_user_id=admin.id,
            data_json='{"col_8": "Hồ sơ kiểm duyệt", "_folder_path": "004/0023"}',
            folder_path="004/0023",
            status="pending_review",
            created_at=datetime(2026, 8, 15, 8, 0, 0) + timedelta(minutes=offset),
        )
        db.add(record)
        records.append(record)
    db.commit()

    result = submissions.api_get_review_folder_submissions(
        folder_path="004/0023",
        page=2,
        page_size=2,
        current_user=current_user(admin),
        db=db,
    )

    assert result["pagination"] == {
        "page": 2,
        "page_size": 2,
        "total": 3,
        "total_pages": 2,
        "from": 3,
        "to": 3,
    }
    assert [item["id"] for item in result["data"]] == [records[0].id]

def test_author_cannot_review_own_submission_and_assigned_reviewer_can_approve(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(
        SubmissionReviewAssignment(
            submission_id=submission.id,
            reviewer_user_id=reviewer.id,
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_toggle_check(
            submission.id,
            current_user=current_user(author),
            db=db,
        )
    assert error.value.status_code == 403

    result = submissions.api_toggle_check(
        submission.id,
        current_user=current_user(reviewer),
        db=db,
    )
    db.refresh(submission)
    assert result["new_status"] == "approved"
    assert submission.status == "approved"
    assert submission.is_checked is True


def test_only_admin_can_return_approved_submission_to_pending_review(db):
    author = add_user(db, "reopen-author")
    reviewer = add_user(db, "reopen-reviewer")
    admin = add_user(db, "reopen-admin", role="admin")
    submission = Submission(
        data_json='{"field": "approved content"}',
        created_by_user_id=author.id,
        status="approved",
        is_checked=True,
    )
    db.add(submission)
    db.flush()
    assignment = SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    )
    db.add(assignment)
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_reopen_submission_review(
            submission.id,
            current_user=current_user(reviewer),
            db=db,
        )

    db.refresh(submission)
    assert error.value.status_code == 403
    assert submission.status == "approved"
    assert submission.is_checked is True

    result = submissions.api_reopen_submission_review(
        submission.id,
        current_user=current_user(admin),
        db=db,
    )

    db.refresh(submission)
    db.refresh(assignment)
    assert result == {
        "status": "ok",
        "new_status": "pending_review",
        "is_checked": False,
    }
    assert submission.status == "pending_review"
    assert submission.is_checked is False
    assert assignment.reviewer_user_id == reviewer.id


def test_author_cannot_edit_submission_while_it_is_waiting_for_review(db):
    author = add_user(db, "author")
    submission = Submission(
        data_json='{"field": "original"}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_update_submission(
            submission.id,
            submissions.SubmitRequest(data={"field": "changed"}, status="draft"),
            current_user=current_user(author),
            db=db,
        )

    db.refresh(submission)
    assert error.value.status_code == 409
    assert submission.status == "pending_review"
    assert submission.data_json == '{"field": "original"}'


def test_submission_fails_when_document_has_no_different_reviewer(db):
    author = add_user(db, "author")
    document = assign_document(db, author)

    with pytest.raises(HTTPException) as error:
        submissions.api_submit(
            submissions.SubmitRequest(
                data={"_pdf_uuid": document.uuid_filename},
                status="pending_review",
            ),
            current_user=current_user(author),
            db=db,
        )

    assert error.value.status_code == 409
    assert db.query(Submission).count() == 0


def test_employee_bulk_deletes_only_own_drafts(db):
    author = add_user(db, "bulk-delete-author")
    first = Submission(data_json="{}", created_by_user_id=author.id, status="draft")
    second = Submission(data_json="{}", created_by_user_id=author.id, status="draft")
    db.add_all([first, second])
    db.commit()
    selected_ids = [first.id, second.id]

    result = submissions.api_bulk_submission_action(
        submissions.BulkSubmissionActionRequest(
            submission_ids=selected_ids,
            action="delete",
        ),
        current_user=current_user(author),
        db=db,
    )

    assert result == {
        "status": "ok",
        "action": "delete",
        "processed_count": 2,
    }
    assert db.query(Submission).filter(Submission.id.in_(selected_ids)).count() == 0


def test_employee_cannot_bulk_process_another_users_submission(db):
    author = add_user(db, "bulk-owner")
    outsider = add_user(db, "bulk-outsider")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_bulk_submission_action(
            submissions.BulkSubmissionActionRequest(
                submission_ids=[submission.id],
                action="delete",
            ),
            current_user=current_user(outsider),
            db=db,
        )

    assert error.value.status_code == 403
    assert db.query(Submission).filter(Submission.id == submission.id).count() == 1


def test_bulk_delete_is_atomic_when_selection_contains_submitted_report(db):
    author = add_user(db, "bulk-delete-atomic-author")
    draft = Submission(data_json="{}", created_by_user_id=author.id, status="draft")
    submitted = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add_all([draft, submitted])
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_bulk_submission_action(
            submissions.BulkSubmissionActionRequest(
                submission_ids=[draft.id, submitted.id],
                action="delete",
            ),
            current_user=current_user(author),
            db=db,
        )

    assert error.value.status_code == 409
    assert db.query(Submission).filter(
        Submission.id.in_([draft.id, submitted.id])
    ).count() == 2


def test_employee_bulk_submits_reports_and_assigns_their_reviewers(db):
    author = add_user(db, "bulk-submit-author")
    reviewer = add_user(db, "bulk-submit-reviewer")
    first_document = assign_document(db, author, reviewer, filename="bulk-1.pdf")
    second_document = assign_document(db, author, reviewer, filename="bulk-2.pdf")
    first = Submission(
        data_json=f'{{"_pdf_uuid": "{first_document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="draft",
    )
    second = Submission(
        data_json=f'{{"_pdf_uuid": "{second_document.uuid_filename}", "_wrong_sections": ["Thông tin"]}}',
        created_by_user_id=author.id,
        status="rejected",
    )
    db.add_all([first, second])
    db.commit()
    selected_ids = [first.id, second.id]

    result = submissions.api_bulk_submission_action(
        submissions.BulkSubmissionActionRequest(
            submission_ids=selected_ids,
            action="submit_for_review",
        ),
        current_user=current_user(author),
        db=db,
    )

    refreshed = db.query(Submission).filter(Submission.id.in_(selected_ids)).all()
    assignments = db.query(SubmissionReviewAssignment).filter(
        SubmissionReviewAssignment.submission_id.in_(selected_ids)
    ).all()
    assert result["processed_count"] == 2
    assert {submission.status for submission in refreshed} == {"pending_review"}
    assert len({submission.created_at for submission in refreshed}) == 1
    assert all("_wrong_sections" not in __import__("json").loads(submission.data_json) for submission in refreshed)
    assert {assignment.reviewer_user_id for assignment in assignments} == {reviewer.id}
    assert first_document.status == "completed"
    assert second_document.status == "completed"


def test_bulk_submit_rolls_back_every_report_when_one_has_no_reviewer(db):
    author = add_user(db, "bulk-submit-atomic-author")
    reviewer = add_user(db, "bulk-submit-atomic-reviewer")
    valid_document = assign_document(db, author, reviewer, filename="valid.pdf")
    invalid_document = assign_document(db, author, filename="invalid.pdf")
    valid = Submission(
        data_json=f'{{"_pdf_uuid": "{valid_document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="draft",
    )
    invalid = Submission(
        data_json=f'{{"_pdf_uuid": "{invalid_document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="draft",
    )
    db.add_all([valid, invalid])
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_bulk_submission_action(
            submissions.BulkSubmissionActionRequest(
                submission_ids=[valid.id, invalid.id],
                action="submit_for_review",
            ),
            current_user=current_user(author),
            db=db,
        )

    db.refresh(valid)
    db.refresh(invalid)
    db.refresh(valid_document)
    assert error.value.status_code == 409
    assert valid.status == "draft"
    assert invalid.status == "draft"
    assert valid_document.status == "pending"
    assert db.query(SubmissionReviewAssignment).count() == 0


def test_deleting_submission_also_deletes_review_assignment(db):
    admin = add_user(db, "admin", role="admin")
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(
        SubmissionReviewAssignment(
            submission_id=submission.id,
            reviewer_user_id=reviewer.id,
        )
    )
    db.commit()

    result = submissions.api_delete_submission(
        submission.id,
        current_user=current_user(admin),
        db=db,
    )

    assert result["status"] == "ok"
    assert db.query(Submission).count() == 0
    assert db.query(SubmissionReviewAssignment).count() == 0


def test_employee_can_delete_own_draft_without_removing_document_assignment(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    document = assign_document(db, author, reviewer)
    submission = Submission(
        data_json=f'{{"_pdf_uuid": "{document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    result = submissions.api_delete_submission(
        submission.id,
        current_user=current_user(author),
        db=db,
    )

    assert result["status"] == "ok"
    assert db.query(Submission).count() == 0
    assert db.query(AssignedDocument).filter(AssignedDocument.id == document.id).count() == 1
    assert db.query(AssignedDocumentReviewAssignment).filter(
        AssignedDocumentReviewAssignment.document_id == document.id
    ).count() == 1


def test_employee_cannot_delete_another_users_draft(db):
    author = add_user(db, "author")
    another_employee = add_user(db, "another")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_delete_submission(
            submission.id,
            current_user=current_user(another_employee),
            db=db,
        )

    assert error.value.status_code == 403
    assert db.query(Submission).filter(Submission.id == submission.id).count() == 1


@pytest.mark.parametrize("status", ["pending_review", "rejected", "approved"])
def test_employee_cannot_delete_submitted_submission(db, status):
    author = add_user(db, "author")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status=status,
    )
    db.add(submission)
    db.commit()

    with pytest.raises(HTTPException) as error:
        submissions.api_delete_submission(
            submission.id,
            current_user=current_user(author),
            db=db,
        )

    assert error.value.status_code == 409
    assert db.query(Submission).filter(Submission.id == submission.id).count() == 1


def test_pending_submission_backfill_uses_its_document_reviewer(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    unrelated_reviewer = add_user(db, "unrelated-reviewer")
    document = assign_document(db, author, reviewer)
    db.add(AssignedDocumentFolder(
        document_id=document.id,
        folder_group="004/0012",
    ))
    submission = Submission(
        data_json=f'{{"_pdf_uuid": "{document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(
        SubmissionReviewAssignment(
            submission_id=submission.id,
            reviewer_user_id=unrelated_reviewer.id,
        )
    )
    db.commit()

    queue = submissions.api_get_review_folder_submissions(
        folder_path="004/0012",
        current_user=current_user(reviewer),
        db=db,
    )
    with pytest.raises(HTTPException) as error:
        submissions.api_get_review_folder_submissions(
            folder_path="004/0012",
            current_user=current_user(unrelated_reviewer),
            db=db,
        )

    assignment = db.query(SubmissionReviewAssignment).one()
    assert assignment.reviewer_user_id == reviewer.id
    assert [item["id"] for item in queue["data"]] == [submission.id]
    assert error.value.status_code == 403


def test_review_folders_include_empty_assignments_and_only_submitted_reports(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    empty_document = assign_document(db, author, reviewer, filename="empty.pdf")
    submitted_document = assign_document(db, author, reviewer, filename="submitted.pdf")
    draft_document = assign_document(db, author, reviewer, filename="draft.pdf")
    db.add_all([
        AssignedDocumentFolder(document_id=empty_document.id, folder_group="00000000/004/0011"),
        AssignedDocumentFolder(document_id=submitted_document.id, folder_group="00000000/004/0012"),
        AssignedDocumentFolder(document_id=draft_document.id, folder_group="00000000/004/0012"),
    ])
    submitted = Submission(
        data_json=f'{{"_pdf_uuid": "{submitted_document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    draft = Submission(
        data_json=f'{{"_pdf_uuid": "{draft_document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="draft",
    )
    db.add_all([submitted, draft])
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submitted.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    folders = submissions.api_get_review_folders(
        current_user=current_user(reviewer),
        db=db,
    )
    rows = {item["folder_path"]: item for item in folders["data"]}
    empty_reports = submissions.api_get_review_folder_submissions(
        folder_path="00000000/004/0011",
        current_user=current_user(reviewer),
        db=db,
    )
    submitted_reports = submissions.api_get_review_folder_submissions(
        folder_path="00000000/004/0012",
        current_user=current_user(reviewer),
        db=db,
    )

    assert rows["00000000/004/0011"]["submitted_count"] == 0
    assert rows["00000000/004/0011"]["total_documents"] == 1
    assert empty_reports["data"] == []
    assert rows["00000000/004/0012"]["submitted_count"] == 1
    assert rows["00000000/004/0012"]["total_documents"] == 2
    assert [item["id"] for item in submitted_reports["data"]] == [submitted.id]


def test_reviewer_edits_content_without_overwriting_errors_or_pdf_metadata(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    submission = Submission(
        data_json='{"field": "old", "_wrong_sections": ["Thông tin"], "_pdf_uuid": "safe.pdf", "_folder_path": "004/0011"}',
        created_by_user_id=author.id,
        status="rejected",
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    result = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(data={
            "field": "reviewer corrected",
            "_wrong_sections": [],
            "_pdf_uuid": "tampered.pdf",
            "_folder_path": "tampered",
        }),
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    stored = __import__("json").loads(submission.data_json)
    assert result == {
        "status": "ok",
        "submission_status": "pending_review",
        "wrong_fields": [],
    }
    assert stored["field"] == "reviewer corrected"
    assert stored["_wrong_sections"] == ["Thông tin"]
    assert stored["_pdf_uuid"] == "safe.pdf"
    assert stored["_folder_path"] == "004/0011"


def test_unassigned_reviewer_cannot_open_folder_or_edit_report(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    outsider = add_user(db, "outsider")
    document = assign_document(db, author, reviewer, filename="protected.pdf")
    db.add(AssignedDocumentFolder(document_id=document.id, folder_group="004/0013"))
    submission = Submission(
        data_json=f'{{"field": "old", "_pdf_uuid": "{document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    with pytest.raises(HTTPException) as folder_error:
        submissions.api_get_review_folder_submissions(
            folder_path="004/0013",
            current_user=current_user(outsider),
            db=db,
        )
    with pytest.raises(HTTPException) as edit_error:
        submissions.api_update_review_content(
            submission.id,
            submissions.ReviewContentRequest(data={"field": "tampered"}),
            current_user=current_user(outsider),
            db=db,
        )

    db.refresh(submission)
    assert folder_error.value.status_code == 403
    assert edit_error.value.status_code == 403
    assert __import__("json").loads(submission.data_json)["field"] == "old"


def test_reviewer_saves_corrected_content_and_error_marks_in_one_transaction(db):
    author = add_user(db, "atomic-review-author")
    reviewer = add_user(db, "atomic-reviewer")
    submission = Submission(
        data_json='{"field": "old", "_pdf_uuid": "safe.pdf"}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    marked = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(
            data={"field": "reviewer corrected", "_pdf_uuid": "tampered.pdf"},
            wrong_fields=["field"],
        ),
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    marked_data = __import__("json").loads(submission.data_json)
    assert marked == {
        "status": "ok",
        "submission_status": "pending_review",
        "wrong_fields": ["field"],
    }
    assert marked_data["field"] == "reviewer corrected"
    assert marked_data["_pdf_uuid"] == "safe.pdf"
    assert marked_data["_wrong_fields"] == ["field"]
    assert submission.status == "pending_review"

    cleared = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(
            data={"field": "fully corrected"},
            wrong_fields=[],
        ),
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    cleared_data = __import__("json").loads(submission.data_json)
    assert cleared == {
        "status": "ok",
        "submission_status": "pending_review",
        "wrong_fields": [],
    }
    assert cleared_data["field"] == "fully corrected"
    assert cleared_data["_wrong_fields"] == []
    assert submission.status == "pending_review"


def test_marking_wrong_fields_does_not_return_report_to_input_user(db):
    author = add_user(db, "marker-author")
    reviewer = add_user(db, "marker-reviewer")
    submission = Submission(
        data_json='{"col_8": "original"}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    result = submissions.api_update_errors(
        submission.id,
        submissions.ErrorSectionsRequest(
            wrong_sections=[],
            wrong_fields=["col_8"],
        ),
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    stored = __import__("json").loads(submission.data_json)
    assert result == {
        "status": "ok",
        "submission_status": "pending_review",
        "wrong_fields": ["col_8"],
    }
    assert submission.status == "pending_review"
    assert stored["_wrong_fields"] == ["col_8"]
