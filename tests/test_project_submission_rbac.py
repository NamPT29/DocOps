import inspect
from datetime import timedelta

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db, get_utc_now
from server.models import (
    AssignedDocument,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
    UserLoginSession,
)
from server.routers import projects, submissions
from server.routers.auth import ALGORITHM, SECRET_KEY
from server.routers.project_access import get_project_input_member


def _auth_token(db, user, browser_id):
    login_session = UserLoginSession(
        session_id=f"session-{browser_id}",
        user_id=user.id,
        browser_id=browser_id,
        expires_at=get_utc_now() + timedelta(minutes=10),
    )
    db.add(login_session)
    db.commit()
    return jwt.encode(
        {"sub": str(user.id), "sid": login_session.session_id},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'project-submission-rbac.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_project(db):
    admin = User(username="rbac-admin", password="hash", role="admin")
    input_user = User(username="rbac-input", password="hash", role="user")
    reviewer = User(username="rbac-reviewer", password="hash", role="user")
    template = Template(name="RBAC template", filename="rbac.xlsx", is_active=True)
    db.add_all([admin, input_user, reviewer, template])
    db.flush()
    project = Project(
        name="RBAC project",
        root_folder_name="rbac-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot="project_snapshots/rbac.xlsx",
        case_level=1,
        report_mode="pdf",
        status="ready",
        created_by_user_id=admin.id,
    )
    db.add(project)
    db.flush()
    db.add_all([
        ProjectMember(
            project_id=project.id,
            user_id=input_user.id,
            member_role="input",
        ),
        ProjectMember(
            project_id=project.id,
            user_id=reviewer.id,
            member_role="reviewer",
        ),
    ])
    db.commit()
    return admin, input_user, reviewer, project


def test_project_workspace_requires_input_role_inside_the_project(db):
    admin, input_user, reviewer, project = _seed_project(db)

    assert get_project_input_member(
        project.id,
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )["id"] == input_user.id
    assert get_project_input_member(
        project.id,
        current_user={"id": admin.id, "role": "admin"},
        db=db,
    )["id"] == admin.id

    with pytest.raises(HTTPException) as forbidden:
        get_project_input_member(
            project.id,
            current_user={"id": reviewer.id, "role": "user"},
            db=db,
        )
    assert forbidden.value.status_code == 403


def test_workspace_route_uses_project_scoped_input_dependency():
    dependency = inspect.signature(projects.api_get_project_workspace).parameters[
        "current_user"
    ].default

    assert dependency.dependency is projects.get_project_input_member


def test_submission_copy_and_delete_require_input_capability():
    for handler in (submissions.api_copy_submission, submissions.api_delete_submission):
        dependency = inspect.signature(handler).parameters["current_user"].default
        assert dependency.dependency is submissions.get_input_user


def test_assigned_reviewer_cannot_delete_employee_submission(db):
    author = User(username="delete-author", password="hash", role="user")
    reviewer = User(username="delete-reviewer", password="hash", role="user")
    db.add_all([author, reviewer])
    db.flush()
    submission = Submission(
        data_json="{}",
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

    with pytest.raises(HTTPException) as forbidden:
        submissions.api_delete_submission(
            submission.id,
            current_user={"id": reviewer.id, "role": "user"},
            db=db,
        )

    assert forbidden.value.status_code == 403
    assert db.get(Submission, submission.id) is not None


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("GET", "/api/submissions/{submission_id}"),
        ("PUT", "/api/submissions/{submission_id}/view"),
    ],
)
def test_submission_access_routes_return_401_403_and_allow_owner(
    db,
    method,
    path_template,
):
    owner = User(username=f"access-owner-{method}", password="hash", role="user")
    outsider = User(username=f"access-outsider-{method}", password="hash", role="user")
    db.add_all([owner, outsider])
    db.flush()
    submission = Submission(
        data_json="{}",
        created_by_user_id=owner.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    app = FastAPI()
    app.include_router(submissions.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    path = path_template.format(submission_id=submission.id)

    unauthenticated = client.request(method, path)
    assert unauthenticated.status_code == 401

    outsider_token = _auth_token(db, outsider, f"outsider-{method}")
    forbidden = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert forbidden.status_code == 403

    owner_token = _auth_token(db, owner, f"owner-{method}")
    allowed = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "ok"


def test_transferred_case_revokes_original_author_and_allows_active_assignee(db):
    _admin, original_author, _reviewer, project = _seed_project(db)
    active_assignee = User(username="rbac-new-input", password="hash", role="user")
    db.add(active_assignee)
    db.flush()
    db.add(ProjectMember(
        project_id=project.id,
        user_id=active_assignee.id,
        member_role="input",
    ))
    case_row = ProjectCase(
        project_id=project.id,
        case_key="case-001",
        display_name="Case 001",
        assigned_input_user_id=active_assignee.id,
    )
    db.add(case_row)
    db.flush()
    report_unit = ProjectReportUnit(
        project_id=project.id,
        case_id=case_row.id,
        report_key="report-001",
        display_name="Report 001",
    )
    document = AssignedDocument(
        original_filename="transferred.pdf",
        uuid_filename="transferred.pdf",
        assigned_to_user_id=active_assignee.id,
        template_id=project.template_id,
        status="assigned",
    )
    db.add_all([report_unit, document])
    db.flush()
    db.add(ProjectDocumentAsset(
        project_id=project.id,
        case_id=case_row.id,
        report_unit_id=report_unit.id,
        assigned_document_id=document.id,
        relative_path="case-001/transferred.pdf",
        normalized_relative_path="case-001/transferred.pdf",
        original_filename="transferred.pdf",
        storage_filename="transferred.pdf",
        content_sha256="a" * 64,
        byte_size=1,
    ))
    submission = Submission(
        data_json='{"_pdf_uuid": "transferred.pdf"}',
        template_id=project.template_id,
        created_by_user_id=original_author.id,
        assigned_document_id=document.id,
        status="draft",
    )
    db.add(submission)
    db.commit()

    with pytest.raises(HTTPException) as update_forbidden:
        submissions.api_update_submission(
            submission.id,
            submissions.SubmitRequest(data={"_pdf_uuid": document.uuid_filename}, status="draft"),
            current_user={"id": original_author.id, "role": "user"},
            db=db,
        )
    with pytest.raises(HTTPException) as view_forbidden:
        submissions.api_claim_submission_view(
            submission.id,
            current_user={"id": original_author.id, "role": "user"},
            db=db,
        )

    assert update_forbidden.value.status_code == 403
    assert view_forbidden.value.status_code == 403
    lease_token = submissions.api_claim_submission_view(
        submission.id,
        current_user={"id": active_assignee.id, "role": "user"},
        db=db,
    )["lease_token"]
    assert submissions.api_update_submission(
        submission.id,
        submissions.SubmitRequest(data={"_pdf_uuid": document.uuid_filename}, status="draft"),
        lease_token=lease_token,
        current_user={"id": active_assignee.id, "role": "user"},
        db=db,
    ) == {"status": "ok"}
    claimed = submissions.api_claim_submission_view(
        submission.id,
        current_user={"id": active_assignee.id, "role": "user"},
        db=db,
    )
    assert claimed["viewer_is_current_user"] is True
    assert submission.created_by_user_id == original_author.id
