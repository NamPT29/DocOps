from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from server.database import Base
from server.models import Submission, SubmissionReviewHistory, Template, User
from server.services.submission_status_service import ensure_submission_status_schema


def test_legacy_submission_statuses_are_normalized_by_confirmation_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        input_user = User(username="legacy-input", password="hash", role="user")
        reviewer = User(username="legacy-reviewer", password="hash", role="user")
        template = Template(name="Legacy", filename="legacy.xlsx")
        db.add_all([input_user, reviewer, template])
        db.flush()
        rejected = Submission(data_json="{}", template_id=template.id, status="rejected")
        awaiting = Submission(data_json="{}", template_id=template.id, status="approved")
        completed = Submission(data_json="{}", template_id=template.id, status="approved")
        db.add_all([rejected, awaiting, completed])
        db.flush()
        db.add(SubmissionReviewHistory(
            submission_id=completed.id,
            event_type="input_corrected",
            input_user_id=input_user.id,
            reviewer_user_id=reviewer.id,
            baseline_data_json="{}",
            reviewer_data_json="{}",
            final_data_json="{}",
            correction_token=f"input-correction:{completed.id}",
        ))
        db.commit()

        ensure_submission_status_schema(engine)
        db.expire_all()

        assert db.get(Submission, rejected.id).status == "pending_review"
        assert db.get(Submission, awaiting.id).status == "pending_input_confirmation"
        assert db.get(Submission, completed.id).status == "completed"

    engine.dispose()


def test_legacy_review_history_schema_adds_confirmation_actor_idempotently():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE submissions ("
            "id INTEGER PRIMARY KEY, status VARCHAR(50)"
            ")"
        ))
        connection.execute(text(
            "CREATE TABLE submission_review_histories ("
            "id INTEGER PRIMARY KEY, submission_id INTEGER NOT NULL, "
            "event_type VARCHAR(32) NOT NULL"
            ")"
        ))

    ensure_submission_status_schema(engine)
    ensure_submission_status_schema(engine)

    inspector = inspect(engine)
    column_names = {
        column["name"]
        for column in inspector.get_columns("submission_review_histories")
    }
    index_names = {
        index["name"]
        for index in inspector.get_indexes("submission_review_histories")
    }
    assert "confirmed_by_user_id" in column_names
    assert "ix_submission_review_histories_confirmed_by_user_id" in index_names

    engine.dispose()
