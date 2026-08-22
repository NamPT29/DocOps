import inspect

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import Project, ProjectMember, Submission, SubmissionReviewAssignment, Template, User
from server.routers import projects, submissions
from server.routers.project_access import get_project_input_member


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
