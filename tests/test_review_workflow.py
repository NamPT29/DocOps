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
    SubmissionViewPresence,
    Template,
    User,
)
from server.routers import auth, submissions, templates as template_routes
from server.routers.documents import (
    RedistributeFolderReviewersRequest,
    RevokeAssignmentsRequest,
    get_user_assignment_folders,
    get_reviewer_folder_assignments,
    get_document_stats,
    redistribute_folder_reviewers,
    revoke_user_assignments,
)
from server.utils.folder_utils import folder_path_key


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


@pytest.fixture(autouse=True)
def isolated_heavy_api_limiter(db, monkeypatch):
    from server.services import api_rate_limit_service

    limiter = api_rate_limit_service.DatabaseRateLimiter(
        240, 60, session_factory=sessionmaker(bind=db.get_bind()),
    )
    monkeypatch.setattr(api_rate_limit_service, "heavy_api_rate_limiter", limiter)


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


def make_submission(*, document=None, folder_path=None, **kwargs):
    if document is not None:
        kwargs["assigned_document_id"] = document.id
    kwargs["folder_path"] = folder_path
    kwargs["folder_path_key"] = folder_path_key(folder_path)
    return Submission(**kwargs)


def current_user(user):
    return {"id": user.id, "username": user.username, "role": user.role}


def claim_lease(db, submission, user):
    return submissions.api_claim_submission_view(
        submission.id,
        current_user=current_user(user),
        db=db,
    )["lease_token"]


def test_duplicate_report_filter_uses_shared_source_document(db):
    author = add_user(db, "duplicate-author")
    reviewer = add_user(db, "duplicate-reviewer")
    template = Template(name="Mẫu lọc trùng", filename="duplicate-filter.xlsx")
    db.add(template)
    db.flush()

    duplicate_document = assign_document(
        db,
        author,
        reviewer,
        filename="duplicate-source.pdf",
    )
    unique_review_document = assign_document(
        db,
        author,
        reviewer,
        filename="unique-review.pdf",
    )
    unique_completed_document = assign_document(
        db,
        author,
        reviewer,
        filename="unique-completed.pdf",
    )
    folder = "004/0099"
    for document in (
        duplicate_document,
        unique_review_document,
        unique_completed_document,
    ):
        document.template_id = template.id
    db.add_all([
        AssignedDocumentFolder(document_id=document.id, folder_group=folder)
        for document in (
            duplicate_document,
            unique_review_document,
            unique_completed_document,
        )
    ])

    def report(document, status, value):
        return Submission(
            template_id=template.id,
            created_by_user_id=author.id,
            assigned_document_id=document.id,
            folder_path=folder,
            folder_path_key=folder_path_key(folder),
            data_json=json.dumps({"col_0": value}),
            status=status,
        )

    duplicate_review = report(duplicate_document, "pending_review", "dup-review")
    duplicate_completed = report(duplicate_document, "completed", "dup-completed")
    unique_review = report(unique_review_document, "pending_review", "unique-review")
    unique_completed = report(unique_completed_document, "completed", "unique-completed")
    db.add_all([
        duplicate_review,
        duplicate_completed,
        unique_review,
        unique_completed,
    ])
    db.flush()
    db.add_all([
        SubmissionReviewAssignment(
            submission_id=submission.id,
            reviewer_user_id=reviewer.id,
        )
        for submission in (duplicate_review, unique_review)
    ])
    db.commit()

    reviewer_folders = submissions.api_get_review_folders(
        template_id=template.id,
        duplicate_only=True,
        current_user=current_user(reviewer),
        db=db,
    )
    reviewer_rows = submissions.api_get_review_folder_submissions(
        folder_path=folder,
        template_id=template.id,
        duplicate_only=True,
        current_user=current_user(reviewer),
        db=db,
    )
    completed_folders = submissions.api_get_completed_folders(
        template_id=template.id,
        duplicate_only=True,
        current_user={"id": 1, "role": "admin"},
        db=db,
    )
    completed_rows = submissions.api_get_submissions(
        template_id=template.id,
        status="completed",
        folder_path=folder,
        duplicate_only=True,
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert reviewer_folders["data"][0]["folder_path"] == folder
    assert reviewer_folders["data"][0]["submitted_count"] == 1
    assert [row["id"] for row in reviewer_rows["data"]] == [duplicate_review.id]
    assert completed_folders["data"][0]["approved_count"] == 1
    assert [row["id"] for row in completed_rows["data"]] == [duplicate_completed.id]



def test_excel_export_includes_only_approved_submissions(db, mocker):
    template = Template(name="Mẫu xuất duyệt", filename="approved-export.xlsx")
    db.add(template)
    db.flush()
    records = []
    for status in (
        "draft",
        "pending_review",
        "pending_input_confirmation",
        "completed",
    ):
        record = Submission(
            template_id=template.id,
            data_json=f'{{"col_0": "{status}"}}',
            status=status,
        )
        db.add(record)
        records.append(record)
    db.commit()

    export_call = mocker.patch(
        "server.services.excel_service.export_submissions_to_excel",
    )
    mocker.patch(
        "server.routers.submissions.FileResponse",
        return_value={"status": "file-ready"},
    )

    result = submissions.api_export(
        template.id,
        BackgroundTasks(),
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert result == {"status": "file-ready"}
    exported_submissions = export_call.call_args.args[1]
    assert [submission.id for submission in exported_submissions] == [records[-1].id]
    assert {submission.status for submission in exported_submissions} == {"completed"}


def test_legacy_excel_export_all_is_rejected_before_heavy_processing(db, mocker):
    template = Template(name="Mẫu xuất toàn bộ", filename="all-export.xlsx")
    db.add(template)
    db.flush()
    records = {}
    for status in (
        "draft",
        "pending_review",
        "pending_input_confirmation",
        "completed",
    ):
        record = Submission(
            template_id=template.id,
            data_json=f'{{"col_0": "{status}"}}',
            status=status,
        )
        db.add(record)
        records[status] = record
    db.commit()

    export_call = mocker.patch(
        "server.services.excel_service.export_submissions_to_excel",
    )
    mocker.patch(
        "server.routers.submissions.FileResponse",
        return_value={"status": "file-ready"},
    )

    with pytest.raises(HTTPException) as exc:
        submissions.api_export(
            template.id,
            BackgroundTasks(),
            include_pending_review=True,
            current_user={"id": 1, "role": "admin"},
            db=db,
        )

    assert exc.value.status_code == 409
    assert "xử lý nền" in exc.value.detail
    export_call.assert_not_called()


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
        "server.services.excel_service.export_submissions_to_excel",
    )

    with pytest.raises(HTTPException) as exc:
        submissions.api_export(
            template.id,
            BackgroundTasks(),
            current_user={"id": 1, "role": "admin"},
            db=db,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Không có hồ sơ hoàn thành để xuất báo cáo cho biểu mẫu này."
    export_call.assert_not_called()


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
    first_approved = make_submission(
        document=first_document,
        folder_path="00000000/004/0011",
        template_id=template.id,
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{first_document.uuid_filename}"}}',
        status="completed",
    )
    second_approved = make_submission(
        document=second_document,
        folder_path="00000000/004/0012",
        template_id=template.id,
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{second_document.uuid_filename}"}}',
        status="completed",
    )
    pending = make_submission(
        document=pending_document,
        folder_path="00000000/004/0011",
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
        status="completed",
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
        "server.services.excel_service.export_submissions_to_excel",
    )
    mocker.patch(
        "server.routers.submissions.FileResponse",
        return_value={"status": "file-ready"},
    )
    result = submissions.api_export(
        template.id,
        BackgroundTasks(),
        folder_path="00000000/004/0011",
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert result == {"status": "file-ready"}
    assert [item.id for item in export_call.call_args.args[1]] == [first_approved.id]

    result = submissions.api_export(
        template.id,
        BackgroundTasks(),
        current_user={"id": 1, "role": "admin"},
        db=db,
    )

    assert result == {"status": "file-ready"}
    assert [item.id for item in export_call.call_args.args[1]] == [
        first_approved.id,
        second_approved.id,
    ]


def test_completed_folders_keep_approved_legacy_records_without_folder(db):
    author = add_user(db, "legacy-completed-author")
    legacy = make_submission(
        created_by_user_id=author.id,
        data_json='{"col_8": "Hồ sơ cũ"}',
        status="completed",
    )
    db.add(legacy)
    db.commit()

    folders = submissions.api_get_completed_folders(
        current_user={"id": 1, "role": "admin"},
        db=db,
    )
    selected = submissions.api_get_submissions(
        status="completed",
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
    approved = make_submission(
        document=document,
        folder_path="__ROOT__",
        created_by_user_id=author.id,
        data_json=f'{{"_pdf_uuid": "{document.uuid_filename}"}}',
        status="completed",
    )
    db.add(approved)
    db.commit()

    selected = submissions.api_get_submissions(
        status="completed",
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

    before_count = db.query(Submission).count()
    with pytest.raises(HTTPException) as exc:
        submissions.api_copy_submission(
            original.id,
            current_user=current_user(author),
            db=db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "copy_requires_form"
    assert db.query(Submission).count() == before_count


def prepare_copy_submission_scope(db, author, *, target_folder="project/7/case-a"):
    template = Template(
        name="Mẫu nhân bản an toàn",
        filename="safe-copy.xlsx",
        config_json=json.dumps({
            "linked_pdf_path": {"enabled": True, "col": 1, "folder_levels": 1},
        }),
    )
    db.add(template)
    db.flush()

    source_document = assign_document(db, author, filename="copy-source.pdf")
    target_document = assign_document(db, author, filename="copy-target.pdf")
    source_document.template_id = template.id
    source_document.status = "completed"
    target_document.template_id = template.id
    db.add_all([
        AssignedDocumentFolder(document_id=source_document.id, folder_group="project/7/case-a"),
        AssignedDocumentFolder(document_id=target_document.id, folder_group=target_folder),
    ])
    source = Submission(
        data_json=json.dumps({
            "col_0": "case-a/copy-source.pdf",
            "col_1": "Nội dung nguồn",
            "_pdf_uuid": source_document.uuid_filename,
            "_folder_path": "project/7/case-a",
        }, ensure_ascii=False),
        created_by_user_id=author.id,
        template_id=template.id,
        status="draft",
        assigned_document_id=source_document.id,
        folder_path="project/7/case-a",
        folder_path_key=folder_path_key("project/7/case-a"),
    )
    db.add(source)
    db.commit()
    return template, source, target_document


def test_copy_save_rejects_path_only_change_then_accepts_business_change(db):
    author = add_user(db, "safe-copy-author")
    template, source, target_document = prepare_copy_submission_scope(db, author)
    request_data = {
        "col_0": "case-a/copy-target.pdf",
        "col_1": "Nội dung nguồn",
        "_pdf_uuid": target_document.uuid_filename,
    }

    with pytest.raises(HTTPException) as exc:
        submissions.api_submit(
            submissions.SubmitRequest(
                template_id=template.id,
                data=request_data,
                status="draft",
                copy_source_submission_id=source.id,
            ),
            current_user=current_user(author),
            db=db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "copy_unchanged"
    assert db.query(Submission).count() == 1
    db.refresh(target_document)
    assert target_document.status == "pending"

    changed_data = dict(request_data, col_1="Nội dung đã sửa")
    result = submissions.api_submit(
        submissions.SubmitRequest(
            template_id=template.id,
            data=changed_data,
            status="draft",
            copy_source_submission_id=source.id,
        ),
        current_user=current_user(author),
        db=db,
    )

    assert result == {"status": "ok"}
    assert db.query(Submission).count() == 2
    db.refresh(target_document)
    assert target_document.status == "completed"


def test_copy_save_rejects_pdf_outside_source_project_case(db):
    author = add_user(db, "copy-scope-author")
    template, source, target_document = prepare_copy_submission_scope(
        db,
        author,
        target_folder="project/7/case-b",
    )

    with pytest.raises(HTTPException) as exc:
        submissions.api_submit(
            submissions.SubmitRequest(
                template_id=template.id,
                data={
                    "col_0": "case-b/copy-target.pdf",
                    "col_1": "Nội dung đã sửa",
                    "_pdf_uuid": target_document.uuid_filename,
                },
                status="draft",
                copy_source_submission_id=source.id,
            ),
            current_user=current_user(author),
            db=db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "copy_scope_mismatch"
    assert db.query(Submission).count() == 1


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
    lease_token = claim_lease(db, copied_draft, author)
    result = submissions.api_update_submission(
        copied_draft.id,
        submissions.SubmitRequest(
            data={"col_8": "Dữ liệu vừa nhập"},
            status="draft",
        ),
        lease_token=lease_token,
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


@pytest.mark.parametrize(
    "submission_status",
    ["draft", "pending_review", "pending_input_confirmation", "completed"],
)
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
        make_submission(
            document=blocked_first,
            folder_path="00000000/004/0011",
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
    for status in ("pending_review", "pending_input_confirmation", "completed"):
        document = assign_document(db, employee, reviewer, filename=f"{status}.pdf")
        document.status = "completed"
        submission = Submission(
            data_json=f'{{"_pdf_uuid": "{document.uuid_filename}"}}',
            created_by_user_id=employee.id,
            assigned_document_id=document.id,
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
    assert reviewer_stats["review_pending"] == 2
    assert result["review_reservations_revoked"] == 1
    assert result["reviews_transferred_to_admin"] == 1
    assert db.query(AssignedDocumentReviewAssignment).filter_by(
        document_id=reserved.id
    ).first() is None
    for status in ("pending_review",):
        assignment = db.query(SubmissionReviewAssignment).filter_by(
            submission_id=submissions_by_status[status].id
        ).one()
        assert assignment.reviewer_user_id == admin.id
    for status in ("pending_input_confirmation", "completed"):
        assignment = db.query(SubmissionReviewAssignment).filter_by(
            submission_id=submissions_by_status[status].id
        ).one()
        assert assignment.reviewer_user_id == reviewer.id
    for document in active_documents[:1]:
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
    submission = make_submission(
        document=document,
        folder_path="00000000/005/0001",
        data_json=f'{{"_pdf_uuid": "{document.uuid_filename}", "field": "kept", "_wrong_sections": ["A"]}}',
        created_by_user_id=input_user.id,
        status="pending_review",
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
    assert db.get(Submission, submission.id).status == "pending_review"


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


def test_draft_is_submitted_from_existing_report_and_uses_document_reviewer(db):
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

    draft = db.query(Submission).one()
    lease_token = claim_lease(db, draft, author)
    submissions.api_update_submission(
        draft.id,
        submissions.SubmitRequest(
            data={"field": "submitted", "_pdf_uuid": document.uuid_filename},
            status="pending_review",
        ),
        lease_token=lease_token,
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

    assert len(rows) == 1
    assert rows[0].status == "pending_review"
    assert assignment.submission_id == rows[0].id
    assert assignment.reviewer_user_id == reviewer.id
    assert [item["id"] for item in queue["data"]] == [rows[0].id]


def test_admin_reviews_unassigned_reports_and_shows_active_viewer(db):
    admin = add_user(db, 'admin', role='admin')
    author = add_user(db, 'author')
    reviewer = add_user(db, 'reviewer')
    assigned = make_submission(
        folder_path="004/0021",
        data_json=json.dumps({'_folder_path': '004/0021'}),
        created_by_user_id=author.id,
        status='pending_review',
    )
    unassigned = make_submission(
        folder_path="004/0022",
        data_json=json.dumps({'_folder_path': '004/0022'}),
        created_by_user_id=author.id,
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
    assert queue['data'][0]['reviewer_user_id'] is None
    assert queue['data'][0]['reviewer_name'] == 'Chưa phân công'
    assert queue['data'][0]['is_reviewer_assigned'] is False
    assert submissions.api_get_submission(
        unassigned.id,
        current_user=current_user(admin),
        db=db,
    )['can_review'] is True

    admin_lease = claim_lease(db, unassigned, admin)
    corrected = submissions.api_update_review_content(
        unassigned.id,
        submissions.ReviewContentRequest(data={'field': 'admin corrected'}),
        lease_token=admin_lease,
        current_user=current_user(admin),
        db=db,
    )
    assert corrected['status'] == 'ok'
    approved = submissions.api_toggle_check(
        unassigned.id,
        lease_token=admin_lease,
        current_user=current_user(admin),
        db=db,
    )
    assert approved['new_status'] == 'pending_input_confirmation'

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

    with pytest.raises(HTTPException) as admin_conflict:
        submissions.api_claim_submission_view(
            assigned.id,
            current_user=current_user(admin),
            db=db,
        )
    assert admin_conflict.value.status_code == 409
    assert admin_conflict.value.detail['viewing_user_name'] == reviewer.username

    released = submissions.api_release_submission_view(
        assigned.id,
        current_user=current_user(reviewer),
        db=db,
    )
    assert released == {'status': 'ok', 'released': True}

    admin_claimed = submissions.api_claim_submission_view(
        assigned.id,
        current_user=current_user(admin),
        db=db,
    )
    assert admin_claimed['viewer_is_current_user'] is True

    with pytest.raises(HTTPException) as conflict:
        submissions.api_claim_submission_view(
            assigned.id,
            current_user=current_user(reviewer),
            db=db,
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail['code'] == 'submission_view_conflict'
    assert conflict.value.detail['viewing_user_name'] == admin.username

    admin_released = submissions.api_release_submission_view(
        assigned.id,
        current_user=current_user(admin),
        db=db,
    )
    assert admin_released == {'status': 'ok', 'released': True}


def test_submission_edit_lease_requires_token_renews_and_allows_stale_takeover(db):
    owner = add_user(db, "lease-owner")
    admin = add_user(db, "lease-admin", role="admin")
    submission = Submission(
        data_json='{"field": "original"}',
        created_by_user_id=owner.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    lease_token = claim_lease(db, submission, owner)
    with pytest.raises(HTTPException) as missing:
        submissions.api_update_submission(
            submission.id,
            submissions.SubmitRequest(data={"field": "missing"}, status="draft"),
            lease_token=None,
            current_user=current_user(owner),
            db=db,
        )
    assert missing.value.status_code == 409
    assert missing.value.detail["code"] == "submission_lease_required"

    with pytest.raises(HTTPException) as wrong:
        submissions.api_update_submission(
            submission.id,
            submissions.SubmitRequest(data={"field": "wrong"}, status="draft"),
            lease_token="wrong-token",
            current_user=current_user(owner),
            db=db,
        )
    assert wrong.value.status_code == 409
    assert wrong.value.detail["code"] == "submission_lease_invalid"

    presence = db.get(SubmissionViewPresence, submission.id)
    before_renewal = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    presence.last_seen_at = before_renewal
    db.commit()
    assert submissions.api_update_submission(
        submission.id,
        submissions.SubmitRequest(data={"field": "saved"}, status="draft"),
        lease_token=lease_token,
        current_user=current_user(owner),
        db=db,
    ) == {"status": "ok"}
    db.refresh(presence)
    assert presence.last_seen_at > before_renewal

    with pytest.raises(HTTPException) as admin_write_conflict:
        submissions.api_update_submission(
            submission.id,
            submissions.SubmitRequest(data={"field": "admin"}, status="draft"),
            lease_token=lease_token,
            current_user=current_user(admin),
            db=db,
        )
    assert admin_write_conflict.value.status_code == 409
    assert admin_write_conflict.value.detail["code"] == "submission_view_conflict"

    presence = db.get(SubmissionViewPresence, submission.id)
    presence.last_seen_at = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=91)
    )
    db.commit()
    takeover = submissions.api_claim_submission_view(
        submission.id,
        current_user=current_user(admin),
        db=db,
    )
    assert takeover["viewer_is_current_user"] is True
    assert takeover["lease_token"] != lease_token
    assert takeover["expires_in_seconds"] == 90


def test_admin_cannot_self_review_even_with_owned_lease(db):
    admin = add_user(db, "self-review-admin", role="admin")
    submission = Submission(
        data_json='{"field": "original"}',
        created_by_user_id=admin.id,
        status="pending_review",
    )
    db.add(submission)
    db.commit()
    lease_token = claim_lease(db, submission, admin)

    assert submissions.api_get_submission(
        submission.id,
        current_user=current_user(admin),
        db=db,
    )["can_review"] is False
    operations = [
        lambda: submissions.api_update_review_content(
            submission.id,
            submissions.ReviewContentRequest(data={"field": "changed"}),
            lease_token=lease_token,
            current_user=current_user(admin),
            db=db,
        ),
        lambda: submissions.api_confirm_submission_review(
            submission.id,
            submissions.ReviewContentRequest(data={"field": "changed"}),
            lease_token=lease_token,
            current_user=current_user(admin),
            db=db,
        ),
        lambda: submissions.api_toggle_check(
            submission.id,
            lease_token=lease_token,
            current_user=current_user(admin),
            db=db,
        ),
        lambda: submissions.api_update_errors(
            submission.id,
            submissions.ErrorSectionsRequest(wrong_sections=["Thông tin"]),
            lease_token=lease_token,
            current_user=current_user(admin),
            db=db,
        ),
    ]
    for operation in operations:
        with pytest.raises(HTTPException) as forbidden:
            operation()
        assert forbidden.value.status_code == 403
    assert submission.status == "pending_review"


def test_all_reviewer_write_routes_require_owned_lease(db):
    author = add_user(db, "lease-route-author")
    reviewer = add_user(db, "lease-route-reviewer")
    submission = Submission(
        data_json='{"field": "original"}',
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

    operations = [
        lambda: submissions.api_update_review_content(
            submission.id,
            submissions.ReviewContentRequest(data={"field": "changed"}),
            lease_token=None,
            current_user=current_user(reviewer),
            db=db,
        ),
        lambda: submissions.api_confirm_submission_review(
            submission.id,
            submissions.ReviewContentRequest(data={"field": "changed"}),
            lease_token=None,
            current_user=current_user(reviewer),
            db=db,
        ),
        lambda: submissions.api_toggle_check(
            submission.id,
            lease_token=None,
            current_user=current_user(reviewer),
            db=db,
        ),
        lambda: submissions.api_update_errors(
            submission.id,
            submissions.ErrorSectionsRequest(wrong_sections=["Thông tin"]),
            lease_token=None,
            current_user=current_user(reviewer),
            db=db,
        ),
    ]
    for operation in operations:
        with pytest.raises(HTTPException) as missing:
            operation()
        assert missing.value.status_code == 409
        assert missing.value.detail["code"] == "submission_lease_required"


def test_review_confirmation_completes_only_when_public_data_is_unchanged(db):
    author = add_user(db, "transition-author")
    reviewer = add_user(db, "transition-reviewer")
    results = []
    for suffix, final_value in (("same", "original"), ("changed", "reviewed")):
        submission = Submission(
            data_json='{"field": "original"}',
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
        lease_token = claim_lease(db, submission, reviewer)
        result = submissions.api_confirm_submission_review(
            submission.id,
            submissions.ReviewContentRequest(data={"field": final_value}),
            lease_token=lease_token,
            current_user=current_user(reviewer),
            db=db,
        )
        results.append((suffix, result["submission_status"]))

    assert results == [
        ("same", "completed"),
        ("changed", "pending_input_confirmation"),
    ]


@pytest.mark.parametrize(
    "status",
    ["draft", "approved", "pending_review", "pending_input_confirmation"],
)
def test_reopen_accepts_only_completed_status(db, status):
    admin = add_user(db, f"reopen-only-admin-{status}", role="admin")
    submission = Submission(
        data_json="{}",
        created_by_user_id=None,
        status=status,
    )
    db.add(submission)
    db.commit()

    with pytest.raises(HTTPException) as invalid:
        submissions.api_reopen_submission_review(
            submission.id,
            current_user=current_user(admin),
            db=db,
        )
    assert invalid.value.status_code == 409
    assert submission.status == status


def test_reopen_and_delete_reject_another_users_active_view(db):
    author = add_user(db, "guarded-action-author")
    reviewer = add_user(db, "guarded-action-reviewer")
    admin = add_user(db, "guarded-action-admin", role="admin")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="completed",
        is_checked=True,
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()
    claim_lease(db, submission, reviewer)

    with pytest.raises(HTTPException) as reopen_conflict:
        submissions.api_reopen_submission_review(
            submission.id,
            current_user=current_user(admin),
            db=db,
        )
    assert reopen_conflict.value.status_code == 409
    with pytest.raises(HTTPException) as delete_conflict:
        submissions.api_delete_submission(
            submission.id,
            current_user=current_user(admin),
            db=db,
        )
    assert delete_conflict.value.status_code == 409
    assert db.get(Submission, submission.id) is not None


@pytest.mark.parametrize("value", [0, 101, "5", True, None])
def test_template_config_rejects_invalid_error_threshold(db, value):
    admin = add_user(db, f"threshold-admin-{value!r}", role="admin")
    template = Template(name="Threshold template", filename="threshold.xlsx")
    db.add(template)
    db.commit()

    with pytest.raises(HTTPException) as invalid:
        template_routes.save_template_config(
            template.id,
            {"error_report_threshold_percent": value},
            current_user=current_user(admin),
            db=db,
        )
    assert invalid.value.status_code == 400
    assert template.config_json is None


@pytest.mark.parametrize("value", [1, 100])
def test_template_config_accepts_error_threshold_range_endpoints(db, value):
    admin = add_user(db, f"threshold-valid-admin-{value}", role="admin")
    template = Template(name="Valid threshold", filename=f"threshold-{value}.xlsx")
    db.add(template)
    db.commit()

    assert template_routes.save_template_config(
        template.id,
        {"error_report_threshold_percent": value},
        current_user=current_user(admin),
        db=db,
    ) == {"status": "ok"}
    assert json.loads(template.config_json)["error_report_threshold_percent"] == value


def test_admin_review_folder_submissions_are_paginated(db):
    admin = add_user(db, "review-pagination-admin", role="admin")
    template = Template(name="Mẫu phân trang kiểm duyệt", filename="review-pagination.xlsx")
    db.add(template)
    db.flush()
    records = []
    for offset in range(3):
        record = make_submission(
            folder_path="004/0023",
            template_id=template.id,
            created_by_user_id=admin.id,
            data_json='{"col_8": "Hồ sơ kiểm duyệt", "_folder_path": "004/0023"}',
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

    lease_token = claim_lease(db, submission, reviewer)
    result = submissions.api_toggle_check(
        submission.id,
        lease_token=lease_token,
        current_user=current_user(reviewer),
        db=db,
    )
    db.refresh(submission)
    assert result["new_status"] == "completed"
    assert submission.status == "completed"
    assert submission.is_checked is True


def test_only_admin_can_return_approved_submission_to_pending_review(db):
    author = add_user(db, "reopen-author")
    reviewer = add_user(db, "reopen-reviewer")
    admin = add_user(db, "reopen-admin", role="admin")
    submission = Submission(
        data_json='{"field": "approved content"}',
        created_by_user_id=author.id,
        status="completed",
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
    assert submission.status == "completed"
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


def test_submission_succeeds_without_reviewer_assignment(db):
    author = add_user(db, "author")
    document = assign_document(db, author)

    submissions.api_submit(
        submissions.SubmitRequest(
            data={"_pdf_uuid": document.uuid_filename},
            status="draft",
        ),
        current_user=current_user(author),
        db=db,
    )
    draft = db.query(Submission).one()
    lease_token = claim_lease(db, draft, author)

    submissions.api_update_submission(
            draft.id,
            submissions.SubmitRequest(
                data={"_pdf_uuid": document.uuid_filename},
                status="pending_review",
            ),
            lease_token=lease_token,
            current_user=current_user(author),
            db=db,
        )

    assert db.query(Submission).one().status == "pending_review"
    assert db.query(SubmissionReviewAssignment).count() == 0


def test_new_submission_cannot_skip_draft_state(db):
    author = add_user(db, "draft-only-author")

    with pytest.raises(HTTPException) as error:
        submissions.api_submit(
            submissions.SubmitRequest(data={"col_0": "value"}, status="pending_review"),
            current_user=current_user(author),
            db=db,
        )

    assert error.value.status_code == 409
    assert db.query(Submission).count() == 0


def test_exact_path_and_content_duplicate_is_kept_as_draft(db):
    author = add_user(db, "exact-duplicate-author")
    template = Template(name="Mẫu kiểm tra trùng", filename="duplicate.xlsx")
    db.add(template)
    db.flush()
    data = {
        "col_0": "Nội dung giống nhau",
        "_pdf_relative_path": "001/hoso.pdf",
        "_folder_path": "001",
    }
    submitted = Submission(
        data_json=json.dumps(data, ensure_ascii=False),
        template_id=template.id,
        created_by_user_id=author.id,
        folder_path="001",
        folder_path_key=folder_path_key("001"),
        status="pending_review",
    )
    draft = Submission(
        data_json=json.dumps(data, ensure_ascii=False),
        template_id=template.id,
        created_by_user_id=author.id,
        folder_path="001",
        folder_path_key=folder_path_key("001"),
        status="draft",
    )
    db.add_all([submitted, draft])
    db.commit()
    lease_token = claim_lease(db, draft, author)

    with pytest.raises(HTTPException) as error:
        submissions.api_update_submission(
            draft.id,
            submissions.SubmitRequest(data=data, template_id=template.id, status="pending_review"),
            lease_token=lease_token,
            current_user=current_user(author),
            db=db,
        )

    db.refresh(draft)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "duplicate_submission"
    assert error.value.detail["duplicate_count"] == 1
    assert draft.status == "draft"
    assert db.query(Submission).count() == 2


def test_missing_path_submission_is_allowed(db):
    author = add_user(db, "missing-path-author")
    draft = Submission(
        data_json='{"col_0": "Không có path"}',
        created_by_user_id=author.id,
        status="draft",
    )
    db.add(draft)
    db.commit()
    lease_token = claim_lease(db, draft, author)

    submissions.api_update_submission(
        draft.id,
        submissions.SubmitRequest(data={"col_0": "Không có path"}, status="pending_review"),
        lease_token=lease_token,
        current_user=current_user(author),
        db=db,
    )

    assert draft.status == "pending_review"


def test_configured_required_path_may_be_missing_when_submitting(db):
    author = add_user(db, "configured-missing-path-author")
    template = Template(
        name="Mẫu cho phép thiếu path",
        filename="missing-path.xlsx",
        config_json=json.dumps({
            "required_cols": [39],
            "linked_pdf_path": {"enabled": True, "col": 39},
        }),
    )
    db.add(template)
    db.flush()
    draft = Submission(
        data_json='{"col_0": "Nội dung"}',
        template_id=template.id,
        created_by_user_id=author.id,
        status="draft",
    )
    db.add(draft)
    db.commit()
    lease_token = claim_lease(db, draft, author)

    submissions.api_update_submission(
        draft.id,
        submissions.SubmitRequest(
            data={"col_0": "Nội dung"},
            template_id=template.id,
            status="pending_review",
        ),
        lease_token=lease_token,
        current_user=current_user(author),
        db=db,
    )

    assert draft.status == "pending_review"


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


def test_bulk_action_blocks_other_viewer_and_releases_owners_lease(db):
    author = add_user(db, "bulk-lease-author")
    viewer = add_user(db, "bulk-lease-viewer", role="admin")
    submission = Submission(
        data_json="{}",
        created_by_user_id=author.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    claim_lease(db, submission, viewer)
    with pytest.raises(HTTPException) as conflict:
        submissions.api_bulk_submission_action(
            submissions.BulkSubmissionActionRequest(
                submission_ids=[submission.id],
                action="delete",
            ),
            current_user=current_user(author),
            db=db,
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "submission_view_conflict"
    assert db.get(Submission, submission.id) is not None

    submissions.api_release_submission_view(
        submission.id,
        current_user=current_user(viewer),
        db=db,
    )
    claim_lease(db, submission, author)
    result = submissions.api_bulk_submission_action(
        submissions.BulkSubmissionActionRequest(
            submission_ids=[submission.id],
            action="delete",
        ),
        current_user=current_user(author),
        db=db,
    )
    assert result["processed_count"] == 1
    assert db.get(SubmissionViewPresence, submission.id) is None


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
        data_json=json.dumps({"_pdf_uuid": first_document.uuid_filename}),
        created_by_user_id=author.id,
        assigned_document_id=first_document.id,
        status="draft",
    )
    second = Submission(
        data_json=json.dumps({
            "_pdf_uuid": second_document.uuid_filename,
            "_wrong_sections": ["Thông tin"],
            "_wrong_fields": ["col_0"],
        }),
        created_by_user_id=author.id,
        assigned_document_id=second_document.id,
        status="draft",
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
    assert result == {
        "status": "ok",
        "action": "submit_for_review",
        "processed_count": 2,
    }
    assert {submission.status for submission in refreshed} == {"pending_review"}
    assert len({submission.created_at for submission in refreshed}) == 1
    assert all(
        "_wrong_sections" not in json.loads(submission.data_json)
        and "_wrong_fields" not in json.loads(submission.data_json)
        for submission in refreshed
    )
    assert {assignment.reviewer_user_id for assignment in assignments} == {reviewer.id}
    assert first_document.status == "completed"
    assert second_document.status == "completed"


def test_bulk_submit_is_atomic_when_one_report_is_invalid(db):
    author = add_user(db, "bulk-submit-atomic-author")
    reviewer = add_user(db, "bulk-submit-atomic-reviewer")
    template = Template(
        name="Mẫu nộp hàng loạt",
        filename="bulk-submit.xlsx",
        config_json=json.dumps({"required_cols": [1]}),
    )
    db.add(template)
    db.commit()
    valid_document = assign_document(db, author, reviewer, filename="valid.pdf")
    invalid_document = assign_document(db, author, reviewer, filename="invalid.pdf")
    valid = Submission(
        template_id=template.id,
        data_json=json.dumps({
            "col_0": "Đủ dữ liệu",
            "_pdf_uuid": valid_document.uuid_filename,
        }),
        created_by_user_id=author.id,
        assigned_document_id=valid_document.id,
        status="draft",
    )
    invalid = Submission(
        template_id=template.id,
        data_json=json.dumps({"_pdf_uuid": invalid_document.uuid_filename}),
        created_by_user_id=author.id,
        assigned_document_id=invalid_document.id,
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
    db.refresh(invalid_document)
    assert error.value.status_code == 400
    assert valid.status == "draft"
    assert invalid.status == "draft"
    assert valid_document.status == "pending"
    assert invalid_document.status == "pending"
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


@pytest.mark.parametrize(
    "status",
    ["pending_review", "pending_input_confirmation", "completed"],
)
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
    submission = make_submission(
        document=document,
        folder_path="004/0012",
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
    submitted = make_submission(
        document=submitted_document,
        folder_path="00000000/004/0012",
        data_json=f'{{"_pdf_uuid": "{submitted_document.uuid_filename}"}}',
        created_by_user_id=author.id,
        status="pending_review",
    )
    draft = make_submission(
        document=draft_document,
        folder_path="00000000/004/0012",
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


def test_submission_folder_files_expose_review_statuses(db):
    author = add_user(db, "folder-status-author")
    reviewer = add_user(db, "folder-status-reviewer")
    pending_document = assign_document(db, author, reviewer, filename="pending-review.pdf")
    approved_document = assign_document(db, author, reviewer, filename="approved-review.pdf")
    unentered_document = assign_document(db, author, reviewer, filename="unentered.pdf")
    folder = "004/0042"
    db.add_all([
        AssignedDocumentFolder(document_id=pending_document.id, folder_group=folder),
        AssignedDocumentFolder(document_id=approved_document.id, folder_group=folder),
        AssignedDocumentFolder(document_id=unentered_document.id, folder_group=folder),
    ])
    pending = Submission(
        data_json=json.dumps({"_pdf_uuid": pending_document.uuid_filename}),
        created_by_user_id=author.id,
        assigned_document_id=pending_document.id,
        folder_path=folder,
        folder_path_key=folder_path_key(folder),
        status="pending_review",
    )
    approved = Submission(
        data_json=json.dumps({"_pdf_uuid": approved_document.uuid_filename}),
        created_by_user_id=author.id,
        assigned_document_id=approved_document.id,
        folder_path=folder,
        folder_path_key=folder_path_key(folder),
        status="completed",
        is_checked=True,
    )
    db.add_all([pending, approved])
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=pending.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()

    payload = submissions.api_get_submission(
        pending.id,
        current_user=current_user(reviewer),
        db=db,
    )

    statuses = {
        item["uuid"]: item["review_status"]
        for item in payload["folder_files"]
    }
    assert statuses == {
        pending_document.uuid_filename: "pending_review",
        approved_document.uuid_filename: "completed",
        unentered_document.uuid_filename: None,
    }


def test_reviewer_edits_content_without_overwriting_errors_or_pdf_metadata(db):
    author = add_user(db, "author")
    reviewer = add_user(db, "reviewer")
    submission = Submission(
        data_json='{"field": "old", "_wrong_sections": ["Thông tin"], "_pdf_uuid": "safe.pdf", "_folder_path": "004/0011"}',
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
    lease_token = claim_lease(db, submission, reviewer)

    result = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(data={
            "field": "reviewer corrected",
            "_wrong_sections": [],
            "_pdf_uuid": "tampered.pdf",
            "_folder_path": "tampered",
        }),
        lease_token=lease_token,
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    stored = __import__("json").loads(submission.data_json)
    assert result == {
        "status": "ok",
        "submission_status": "pending_review",
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


def test_reviewer_saves_corrected_content_without_manual_error_marks(db):
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
    lease_token = claim_lease(db, submission, reviewer)

    marked = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(
            data={"field": "reviewer corrected", "_pdf_uuid": "tampered.pdf"},
        ),
        lease_token=lease_token,
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    marked_data = __import__("json").loads(submission.data_json)
    assert marked == {
        "status": "ok",
        "submission_status": "pending_review",
    }
    assert marked_data["field"] == "reviewer corrected"
    assert marked_data["_pdf_uuid"] == "safe.pdf"
    assert "_wrong_fields" not in marked_data
    assert submission.status == "pending_review"

    cleared = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(
            data={"field": "fully corrected"},
        ),
        lease_token=lease_token,
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    cleared_data = __import__("json").loads(submission.data_json)
    assert cleared == {
        "status": "ok",
        "submission_status": "pending_review",
    }
    assert cleared_data["field"] == "fully corrected"
    assert "_wrong_fields" not in cleared_data
    assert submission.status == "pending_review"


def test_reviewer_confirmation_saves_content_and_approves_atomically(db):
    author = add_user(db, "confirm-review-author")
    reviewer = add_user(db, "confirm-reviewer")
    submission = Submission(
        data_json=json.dumps({
            "col_8": "Nội dung cũ",
            "_pdf_uuid": "safe.pdf",
            "_folder_path": "004/0011",
        }),
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
    lease_token = claim_lease(db, submission, reviewer)

    result = submissions.api_confirm_submission_review(
        submission.id,
        submissions.ReviewContentRequest(
            data={
                "col_8": "Nội dung đã kiểm duyệt",
                "_pdf_uuid": "tampered.pdf",
                "_folder_path": "tampered",
            },
        ),
        lease_token=lease_token,
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    stored = json.loads(submission.data_json)
    assert result == {
        "status": "ok",
        "submission_status": "pending_input_confirmation",
        "is_checked": True,
    }
    assert submission.status == "pending_input_confirmation"
    assert submission.is_checked is True
    assert stored["col_8"] == "Nội dung đã kiểm duyệt"
    assert stored["_pdf_uuid"] == "safe.pdf"
    assert stored["_folder_path"] == "004/0011"
    assert "_wrong_fields" not in stored


def test_unassigned_reviewer_cannot_confirm_submission(db):
    author = add_user(db, "confirm-owner")
    reviewer = add_user(db, "assigned-confirm-reviewer")
    outsider = add_user(db, "unassigned-confirm-reviewer")
    submission = Submission(
        data_json=json.dumps({"col_8": "Nội dung cũ"}),
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

    with pytest.raises(HTTPException) as error:
        submissions.api_confirm_submission_review(
            submission.id,
            submissions.ReviewContentRequest(data={"col_8": "Không được phép"}),
            current_user=current_user(outsider),
            db=db,
        )

    db.refresh(submission)
    assert error.value.status_code == 403
    assert submission.status == "pending_review"
    assert submission.is_checked is False
    assert json.loads(submission.data_json)["col_8"] == "Nội dung cũ"


def test_legacy_wrong_fields_are_discarded_during_review_save(db):
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
    lease_token = claim_lease(db, submission, reviewer)

    result = submissions.api_update_review_content(
        submission.id,
        submissions.ReviewContentRequest(
            data={"col_8": "reviewed"},
            wrong_fields=["col_8"],
        ),
        lease_token=lease_token,
        current_user=current_user(reviewer),
        db=db,
    )

    db.refresh(submission)
    stored = __import__("json").loads(submission.data_json)
    assert result == {
        "status": "ok",
        "submission_status": "pending_review",
    }
    assert submission.status == "pending_review"
    assert "_wrong_fields" not in stored


@pytest.mark.parametrize(
    "operation",
    [
        lambda db: submissions.api_get_submission(
            999,
            current_user={"id": 1, "role": "admin"},
            db=db,
        ),
        lambda db: submissions.api_update_submission(
            999,
            submissions.SubmitRequest(data={}),
            current_user={"id": 1, "role": "admin"},
            db=db,
        ),
        lambda db: submissions.api_toggle_check(
            999,
            current_user={"id": 1, "role": "admin"},
            db=db,
        ),
        lambda db: submissions.api_delete_submission(
            999,
            current_user={"id": 1, "role": "admin"},
            db=db,
        ),
    ],
)
def test_missing_submission_operations_return_not_found(db, operation):
    with pytest.raises(HTTPException) as error:
        operation(db)

    assert error.value.status_code == 404


def test_next_review_submission_skips_completed_current_item(db):
    author = add_user(db, "next-review-author")
    reviewer = add_user(db, "next-review-reviewer")
    older = Submission(
        data_json='{"col_8": "older"}',
        created_by_user_id=author.id,
        folder_path="004/0023",
        folder_path_key="004-0023",
        status="pending_review",
        created_at=datetime(2026, 1, 1, 10, 0, 0),
    )
    current = Submission(
        data_json='{"col_8": "current"}',
        created_by_user_id=author.id,
        folder_path="004/0023",
        folder_path_key="004-0023",
        status="pending_input_confirmation",
        created_at=datetime(2026, 1, 1, 11, 0, 0),
    )
    db.add_all([older, current])
    db.flush()
    db.add_all([
        SubmissionReviewAssignment(submission_id=older.id, reviewer_user_id=reviewer.id),
        SubmissionReviewAssignment(submission_id=current.id, reviewer_user_id=reviewer.id),
    ])
    db.commit()

    result = submissions.api_get_next_review_submission(
        current_id=current.id,
        folder_path="004/0023",
        current_user=current_user(reviewer),
        db=db,
    )

    assert result == {"status": "ok", "data": {"id": older.id}}
