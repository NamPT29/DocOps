"""BA 3.3: admins may enter data; BR-04 still forbids reviewing one's own entry."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    Project,
    ProjectCase,
    ProjectMember,
    Submission,
    SubmissionQualityAssessment,
    Template,
    User,
)
from server.routers import submissions
from server.services.project_assignment_service import assign_unassigned_project_cases
from server.services.project_service import _validate_project_members


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'admin-entry.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, username, role="user"):
    user = User(username=username, password="x", role=role)
    db.add(user)
    db.commit()
    return user


def _as(user):
    return {"id": user.id, "username": user.username, "role": user.role}


def _submission(db, author, *, status="draft", document=None, created_at=None, folder="p/001"):
    submission = Submission(
        data_json='{"col_1": "x"}',
        created_by_user_id=author.id,
        status=status,
        assigned_document_id=document.id if document else None,
        folder_path=folder,
        created_at=created_at or datetime(2026, 10, 3, 9, 0, 0),
    )
    db.add(submission)
    db.commit()
    return submission


def test_admin_may_be_assigned_as_input_member(db):
    admin = _user(db, "pm", role="admin")
    staff = _user(db, "staff1")

    assert _validate_project_members(db, [admin.id, staff.id], [admin.id, staff.id]) == (
        sorted([admin.id, staff.id]),
        sorted([admin.id, staff.id]),
    )


def test_case_assignment_never_makes_an_admin_review_their_own_case(db):
    admin = _user(db, "pm", role="admin")
    staff = _user(db, "staff1")
    template = Template(name="t", filename="t.xlsx", is_active=True)
    db.add(template)
    db.flush()
    project = Project(
        name="P", root_folder_name="p", template_id=template.id,
        template_name_snapshot="t", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf", created_by_user_id=admin.id,
    )
    db.add(project)
    db.flush()
    cases = [
        ProjectCase(project_id=project.id, case_key=key, display_name=key)
        for key in ("001", "002", "003", "004")
    ]
    db.add_all(cases)
    db.add_all([
        ProjectMember(project_id=project.id, user_id=user.id, member_role=role, is_active=True)
        for user in (admin, staff)
        for role in ("input", "reviewer")
    ])
    db.commit()

    assign_unassigned_project_cases(db, project_id=project.id, changed_by_user_id=admin.id)

    admin_cases = [case for case in cases if case.assigned_input_user_id == admin.id]
    assert admin_cases, "the admin is part of the input pool"
    for case in cases:
        assert case.assigned_input_user_id is not None
        assert case.assigned_reviewer_user_id not in (None, case.assigned_input_user_id)


def test_input_page_lists_only_the_admins_own_reports(db):
    admin = _user(db, "pm", role="admin")
    staff = _user(db, "staff1")
    own = _submission(db, admin)
    _submission(db, staff)

    def listed(**kwargs):
        payload = submissions.api_get_submissions(current_user=_as(admin), db=db, **kwargs)
        return [item["id"] for item in payload["data"]]

    assert listed(mine=True) == [own.id]
    assert len(listed()) == 2, "the admin pages keep the full list"


def test_admin_gets_the_input_view_of_an_own_report_but_cannot_review_it(db):
    admin = _user(db, "pm", role="admin")
    document = AssignedDocument(
        original_filename="a.pdf", uuid_filename="uuid-a.pdf",
        assigned_to_user_id=admin.id, status="completed",
    )
    db.add(document)
    db.commit()
    own = _submission(db, admin, status="pending_input_confirmation", document=document)
    db.add(SubmissionQualityAssessment(
        submission_id=own.id, input_user_id=admin.id, baseline_data_json="{}",
    ))
    db.commit()

    payload = submissions.api_get_submission(own.id, current_user=_as(admin), db=db)

    assert payload["can_review"] is False  # BR-04
    assert payload["quality"] is not None  # needed to confirm a reviewer's correction


def test_next_review_item_skips_the_admins_own_reports(db):
    admin = _user(db, "pm", role="admin")
    staff = _user(db, "staff1")
    current = _submission(db, staff, status="pending_review", created_at=datetime(2026, 10, 3, 12))
    _submission(db, admin, status="pending_review", created_at=datetime(2026, 10, 3, 11))
    older = _submission(db, staff, status="pending_review", created_at=datetime(2026, 10, 3, 10))

    result = submissions.api_get_next_review_submission(
        current_id=current.id, folder_path=None, current_user=_as(admin), db=db,
    )

    assert result == {"status": "ok", "data": {"id": older.id}}
