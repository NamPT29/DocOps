from sqlalchemy import func

from server.models import (
    SubmissionQualityAssessment,
    SubmissionReviewHistory,
    User,
)


# SQLite giới hạn 999 tham số trong một câu lệnh; chia nhỏ danh sách id.
ID_CHUNK_SIZE = 900


def _chunks(ids):
    ids = sorted(set(ids))
    for start in range(0, len(ids), ID_CHUNK_SIZE):
        yield ids[start:start + ID_CHUNK_SIZE]


class TimesheetRepository:
    """Read-only data for the daily timesheet sheet of an Excel export."""

    def __init__(self, session):
        self.session = session

    def assessments_by_submission(self, submission_ids):
        """{submission_id: (input_user_id, created_at)}; created_at = lần nộp đầu tiên."""
        result = {}
        for chunk in _chunks(submission_ids):
            rows = self.session.query(
                SubmissionQualityAssessment.submission_id,
                SubmissionQualityAssessment.input_user_id,
                SubmissionQualityAssessment.created_at,
            ).filter(
                SubmissionQualityAssessment.submission_id.in_(chunk),
            ).all()
            for submission_id, input_user_id, created_at in rows:
                result[submission_id] = (input_user_id, created_at)
        return result

    def first_review_confirmations(self, submission_ids):
        """{submission_id: (reviewer_user_id, created_at)} của lần duyệt đầu tiên."""
        result = {}
        for chunk in _chunks(submission_ids):
            first_ids = self.session.query(
                func.min(SubmissionReviewHistory.id),
            ).filter(
                SubmissionReviewHistory.event_type == "review_confirmed",
                SubmissionReviewHistory.submission_id.in_(chunk),
            ).group_by(SubmissionReviewHistory.submission_id).subquery()
            rows = self.session.query(
                SubmissionReviewHistory.submission_id,
                SubmissionReviewHistory.reviewer_user_id,
                SubmissionReviewHistory.created_at,
            ).filter(
                SubmissionReviewHistory.id.in_(first_ids.select()),
            ).all()
            for submission_id, reviewer_user_id, created_at in rows:
                result[submission_id] = (reviewer_user_id, created_at)
        return result

    def display_names(self, user_ids):
        result = {}
        for chunk in _chunks(user_id for user_id in user_ids if user_id is not None):
            rows = self.session.query(User.id, User.full_name, User.username).filter(
                User.id.in_(chunk),
            ).all()
            for user_id, full_name, username in rows:
                result[user_id] = (full_name or "").strip() or username
        return result
