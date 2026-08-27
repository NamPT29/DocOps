import inspect as python_inspect

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    Project,
    ProjectMember,
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewFieldHistory,
    SubmissionReviewHistory,
    Template,
    User,
)
from server.routers import auth
from server.services.personnel_statistics_service import get_personnel_statistics


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _history(db, submission, input_user, reviewer, *, event_type, review_event_id=None):
    row = SubmissionReviewHistory(
        submission_id=submission.id,
        review_event_id=review_event_id,
        event_type=event_type,
        input_user_id=input_user.id,
        reviewer_user_id=reviewer.id,
        baseline_data_json="{}",
        reviewer_data_json="{}",
        final_data_json="{}" if event_type == "input_correction" else None,
        visible_field_count=10,
        changed_field_count=1,
        reviewer_error_count=0,
        correction_token=(
            f"correction-{submission.id}-{review_event_id}"
            if event_type == "input_correction"
            else None
        ),
    )
    db.add(row)
    db.flush()
    return row


def test_personnel_statistics_use_immutable_quality_and_first_review_history():
    engine, db = _database()
    try:
        admin = User(username="admin", password="hash", full_name="Admin", role="admin")
        input_user = User(
            username="input-user",
            password="hash",
            full_name="Nguyễn Văn Nhập",
            role="user",
        )
        reviewer = User(
            username="reviewer",
            password="hash",
            full_name="Trần Thị Duyệt",
            role="user",
        )
        template = Template(name="Form", filename="form.xlsx")
        db.add_all([admin, input_user, reviewer, template])
        db.flush()

        projects = [
            Project(
                name=f"Project {index}",
                root_folder_name=f"project-{index}",
                template_id=template.id,
                template_name_snapshot=template.name,
                template_filename_snapshot=template.filename,
                case_level=1,
                report_mode="pdf",
                status="in_progress",
                created_by_user_id=admin.id,
            )
            for index in range(2)
        ]
        db.add_all(projects)
        db.flush()
        db.add_all([
            ProjectMember(
                project_id=projects[0].id,
                user_id=input_user.id,
                member_role="input",
                is_active=True,
            ),
            ProjectMember(
                project_id=projects[0].id,
                user_id=input_user.id,
                member_role="reviewer",
                is_active=True,
            ),
            ProjectMember(
                project_id=projects[1].id,
                user_id=input_user.id,
                member_role="input",
                is_active=False,
            ),
            ProjectMember(
                project_id=projects[1].id,
                user_id=reviewer.id,
                member_role="reviewer",
                is_active=True,
            ),
        ])

        submissions = [
            Submission(
                data_json="{}",
                template_id=template.id,
                created_by_user_id=input_user.id,
                status="pending_review",
            )
            for _ in range(3)
        ]
        db.add_all(submissions)
        db.add(Submission(
            data_json="{}",
            template_id=template.id,
            created_by_user_id=input_user.id,
            status="draft",
        ))
        db.flush()
        db.add_all([
            SubmissionQualityAssessment(
                submission_id=submissions[0].id,
                input_user_id=input_user.id,
                baseline_data_json="{}",
                visible_field_count=20,
                changed_field_count=1,
                is_error_report=True,
            ),
            SubmissionQualityAssessment(
                submission_id=submissions[1].id,
                input_user_id=input_user.id,
                baseline_data_json="{}",
                visible_field_count=20,
                changed_field_count=0,
                is_error_report=False,
            ),
            SubmissionQualityAssessment(
                submission_id=submissions[2].id,
                input_user_id=reviewer.id,
                baseline_data_json="{}",
                visible_field_count=20,
                changed_field_count=0,
                is_error_report=False,
            ),
        ])
        submissions[0].created_by_user_id = reviewer.id

        first_review = _history(
            db,
            submissions[0],
            input_user,
            reviewer,
            event_type="review_confirmed",
        )
        _history(
            db,
            submissions[0],
            input_user,
            admin,
            event_type="review_confirmed",
        )
        _history(
            db,
            submissions[1],
            input_user,
            reviewer,
            event_type="review_confirmed",
        )
        _history(
            db,
            submissions[2],
            reviewer,
            input_user,
            event_type="review_confirmed",
        )
        correction = _history(
            db,
            submissions[0],
            input_user,
            reviewer,
            event_type="input_correction",
            review_event_id=first_review.id,
        )
        db.add_all([
            SubmissionReviewFieldHistory(
                event_id=correction.id,
                submission_id=submissions[0].id,
                field_name="field_a",
                baseline_value_json='"a"',
                reviewer_value_json='"b"',
                final_value_json='"a"',
                reviewer_error=True,
            ),
            SubmissionReviewFieldHistory(
                event_id=correction.id,
                submission_id=submissions[0].id,
                field_name="field_b",
                baseline_value_json='"a"',
                reviewer_value_json='"b"',
                final_value_json='"a"',
                reviewer_error=True,
            ),
            SubmissionReviewFieldHistory(
                event_id=correction.id,
                submission_id=submissions[0].id,
                field_name="field_c",
                baseline_value_json='"a"',
                reviewer_value_json='"b"',
                final_value_json='"c"',
                reviewer_error=False,
            ),
        ])
        db.commit()

        rows = {row["user_id"]: row for row in get_personnel_statistics(db)}

        assert set(rows) == {input_user.id, reviewer.id}
        assert rows[input_user.id] == {
            "user_id": input_user.id,
            "username": input_user.username,
            "full_name": "Nguyễn Văn Nhập",
            "active_project_count": 1,
            "submitted_report_count": 2,
            "reviewed_report_count": 1,
            "input_error_report_count": 1,
            "reviewer_error_field_count": 0,
        }
        assert rows[reviewer.id] == {
            "user_id": reviewer.id,
            "username": reviewer.username,
            "full_name": "Trần Thị Duyệt",
            "active_project_count": 1,
            "submitted_report_count": 1,
            "reviewed_report_count": 2,
            "input_error_report_count": 0,
            "reviewer_error_field_count": 2,
        }
    finally:
        db.close()
        engine.dispose()


def test_personnel_statistics_route_requires_admin():
    dependency = python_inspect.signature(
        auth.api_get_personnel_statistics,
    ).parameters["current_user"].default
    assert dependency.dependency is auth.get_admin_user
