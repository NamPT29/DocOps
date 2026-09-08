import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    AssignedDocumentReviewAssignment,
    Notification,
    NotificationRecipient,
    Project,
    ProjectCase,
    ProjectMember,
    ServerFolderImportJob,
    ServerFolderImportReviewer,
    Submission,
    SubmissionReviewAssignment,
    SubmissionViewPresence,
    Task,
    Template,
    User,
    UserCapability,
)
from server.routers import auth, templates


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'business.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_user(db, username, *, role="user"):
    user = User(username=username, password="hash", role=role)
    db.add(user)
    db.flush()
    return user


def _current_user(user):
    return {"id": user.id, "username": user.username, "role": user.role}


def test_deleting_user_detaches_references_but_preserves_business_records(db):
    admin = _add_user(db, "admin", role="admin")
    target = _add_user(db, "employee")
    other_user = _add_user(db, "other-employee")
    template = Template(name="Biểu mẫu", filename="form.xlsx")
    db.add(template)
    db.flush()

    input_document = AssignedDocument(
        original_filename="input.pdf",
        uuid_filename="input-uuid.pdf",
        assigned_to_user_id=target.id,
        template_id=template.id,
        status="pending",
    )
    reviewed_document = AssignedDocument(
        original_filename="review.pdf",
        uuid_filename="review-uuid.pdf",
        assigned_to_user_id=other_user.id,
        template_id=template.id,
        status="pending",
    )
    db.add_all([input_document, reviewed_document])
    db.flush()
    db.add_all(
        [
            AssignedDocumentReviewAssignment(
                document_id=input_document.id,
                reviewer_user_id=other_user.id,
            ),
            AssignedDocumentReviewAssignment(
                document_id=reviewed_document.id,
                reviewer_user_id=target.id,
            ),
        ]
    )

    submission = Submission(
        data_json='{"field": "must survive"}',
        template_id=template.id,
        created_by_user_id=target.id,
        status="pending_review",
    )
    task = Task(
        user_id=target.id,
        template_id=template.id,
        title="Công việc phải giữ",
        target_quantity=10,
    )
    import_job = ServerFolderImportJob(
        created_by_user_id=admin.id,
        template_id=template.id,
        source_relative_path="00000000",
        grouping_level=2,
        user_ids_json=f"[{other_user.id}]",
    )
    db.add_all([submission, task, import_job])
    db.flush()
    db.add_all(
        [
            SubmissionReviewAssignment(
                submission_id=submission.id,
                reviewer_user_id=target.id,
            ),
            ServerFolderImportReviewer(
                job_id=import_job.id,
                reviewer_user_id=target.id,
            ),
            UserCapability(
                user_id=target.id,
                can_input=True,
                can_review=True,
            ),
        ]
    )
    db.commit()

    target_id = target.id
    input_document_id = input_document.id
    reviewed_document_id = reviewed_document.id
    submission_id = submission.id
    task_id = task.id
    import_job_id = import_job.id

    result = auth.api_delete_user(
        target_id,
        current_user=_current_user(admin),
        db=db,
    )

    db.expire_all()
    assert result == {"status": "ok"}
    assert db.get(User, target_id) is None

    preserved_input = db.get(AssignedDocument, input_document_id)
    preserved_reviewed = db.get(AssignedDocument, reviewed_document_id)
    preserved_submission = db.get(Submission, submission_id)
    preserved_task = db.get(Task, task_id)

    assert preserved_input.assigned_to_user_id is None
    assert preserved_reviewed.assigned_to_user_id == other_user.id
    assert preserved_submission.created_by_user_id is None
    assert preserved_submission.data_json == '{"field": "must survive"}'
    assert preserved_task.user_id is None
    assert db.get(ServerFolderImportJob, import_job_id) is not None

    assert db.query(AssignedDocumentReviewAssignment).filter_by(
        document_id=input_document_id
    ).one().reviewer_user_id == other_user.id
    assert db.query(AssignedDocumentReviewAssignment).filter_by(
        document_id=reviewed_document_id
    ).first() is None
    assert db.query(SubmissionReviewAssignment).filter_by(
        submission_id=submission_id
    ).first() is None
    assert db.query(ServerFolderImportReviewer).filter_by(
        job_id=import_job_id
    ).first() is None
    assert db.get(UserCapability, target_id) is None


def test_deleting_user_detaches_transient_project_and_presence_references(db):
    admin = _add_user(db, "admin-project-owner", role="admin")
    target = _add_user(db, "transient-project-member")
    template = Template(name="Biểu mẫu dự án", filename="project-form.xlsx")
    db.add(template)
    db.flush()
    project = Project(
        name="Dự án giữ lại",
        root_folder_name="du-an-giu-lai",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        case_level=1,
        report_mode="pdf",
        created_by_user_id=admin.id,
    )
    submission = Submission(
        data_json="{}",
        template_id=template.id,
        created_by_user_id=admin.id,
        status="draft",
    )
    notification = Notification(
        title="Thông báo giữ lại",
        message="Nội dung giữ lại",
        created_by_user_id=admin.id,
    )
    db.add_all([project, submission, notification])
    db.flush()
    project_case = ProjectCase(
        project_id=project.id,
        case_key="case-001",
        display_name="Hồ sơ 001",
        assigned_input_user_id=target.id,
        assigned_reviewer_user_id=target.id,
    )
    db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=target.id, member_role="input"),
            ProjectMember(project_id=project.id, user_id=target.id, member_role="reviewer"),
            project_case,
            NotificationRecipient(notification_id=notification.id, user_id=target.id),
            SubmissionViewPresence(submission_id=submission.id, viewer_user_id=target.id),
        ]
    )
    db.commit()
    target_id = target.id
    project_id = project.id
    case_id = project_case.id

    result = auth.api_delete_user(
        target_id,
        current_user=_current_user(admin),
        db=db,
    )

    db.expire_all()
    assert result == {"status": "ok"}
    assert db.get(User, target_id) is None
    assert db.get(Project, project_id) is not None
    preserved_case = db.get(ProjectCase, case_id)
    assert preserved_case.assigned_input_user_id is None
    assert preserved_case.assigned_reviewer_user_id is None
    assert db.query(ProjectMember).filter_by(user_id=target_id).count() == 0
    assert db.query(NotificationRecipient).filter_by(user_id=target_id).count() == 0
    assert db.query(SubmissionViewPresence).filter_by(viewer_user_id=target_id).count() == 0


def test_deleting_user_with_historical_project_reference_returns_conflict(db):
    admin = _add_user(db, "admin-delete-blocker", role="admin")
    target = _add_user(db, "project-creator")
    template = Template(name="Biểu mẫu lịch sử", filename="history-form.xlsx")
    db.add(template)
    db.flush()
    project = Project(
        name="Dự án lịch sử",
        root_folder_name="du-an-lich-su",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        case_level=1,
        report_mode="pdf",
        created_by_user_id=target.id,
    )
    db.add(project)
    db.commit()
    target_id = target.id
    project_id = project.id

    with pytest.raises(HTTPException) as error:
        auth.api_delete_user(
            target_id,
            current_user=_current_user(admin),
            db=db,
        )

    assert error.value.status_code == 409
    assert "dự án đã tạo" in error.value.detail
    assert db.get(User, target_id) is not None
    assert db.get(Project, project_id) is not None


def test_admin_cannot_delete_own_account(db):
    admin = _add_user(db, "admin", role="admin")
    db.commit()

    with pytest.raises(HTTPException) as error:
        auth.api_delete_user(
            admin.id,
            current_user=_current_user(admin),
            db=db,
        )

    assert error.value.status_code == 409
    assert db.get(User, admin.id) is not None


def test_duplicate_username_returns_conflict(db):
    admin = _add_user(db, "admin", role="admin")
    _add_user(db, "existing")
    db.commit()

    with pytest.raises(HTTPException) as error:
        auth.api_create_user(
            auth.CreateUserRequest(username="existing", password="password123"),
            current_user=_current_user(admin),
            db=db,
        )

    assert error.value.status_code == 409


def test_changing_password_for_missing_user_returns_not_found(db):
    admin = _add_user(db, "admin", role="admin")
    db.commit()

    with pytest.raises(HTTPException) as error:
        auth.api_change_user_password(
            999,
            auth.ChangePasswordRequest(new_password="password123"),
            current_user=_current_user(admin),
            db=db,
        )

    assert error.value.status_code == 404


def test_template_configuration_round_trip_and_soft_delete(db):
    admin = _add_user(db, "admin", role="admin")
    template = Template(name="Biểu mẫu địa chính", filename="land.xlsx")
    db.add(template)
    db.commit()
    config = {
        "placeholders": {"col_8": "Nhập số hồ sơ"},
        "hidden_fields": ["col_12", "col_13"],
        "nested": {"unicode": "Gợi ý tiếng Việt"},
    }

    saved = templates.save_template_config(
        template.id,
        config,
        current_user=_current_user(admin),
        db=db,
    )
    loaded = templates.get_template_config(template.id, db=db)
    deleted = templates.delete_template(
        template.id,
        current_user=_current_user(admin),
        db=db,
    )
    active_templates = templates.get_templates(db=db)

    db.refresh(template)
    assert saved == {"status": "ok"}
    assert loaded == {"status": "ok", "data": config}
    assert deleted == {"status": "ok"}
    assert template.is_active is False
    assert template.config_json is not None
    assert active_templates["data"] == []


def test_template_config_returns_not_found_for_unknown_template(db):
    with pytest.raises(HTTPException) as error:
        templates.get_template_config(999, db=db)

    assert error.value.status_code == 404


def test_template_schema_returns_not_found_for_unknown_template(db):
    with pytest.raises(HTTPException) as error:
        asyncio.run(templates.get_template_schema(999, db=db))

    assert error.value.status_code == 404
    assert error.value.detail == "Template not found"
    assert db.query(Task).count() == 0
