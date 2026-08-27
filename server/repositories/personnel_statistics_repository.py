from sqlalchemy import func

from server.models import (
    ProjectMember,
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewFieldHistory,
    SubmissionReviewHistory,
    User,
)


class PersonnelStatisticsRepository:
    """Read-only aggregates for the account-management personnel table."""

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _count_map(rows):
        return {int(user_id): int(count or 0) for user_id, count in rows}

    def list_personnel(self):
        return self.session.query(User).filter(
            User.role != "admin",
        ).order_by(User.id).all()

    def active_project_counts(self):
        rows = self.session.query(
            ProjectMember.user_id,
            func.count(func.distinct(ProjectMember.project_id)),
        ).filter(
            ProjectMember.is_active.is_(True),
        ).group_by(ProjectMember.user_id).all()
        return self._count_map(rows)

    def submitted_report_counts(self):
        owner_id = func.coalesce(
            SubmissionQualityAssessment.input_user_id,
            Submission.created_by_user_id,
        )
        rows = self.session.query(
            owner_id,
            func.count(Submission.id),
        ).outerjoin(
            SubmissionQualityAssessment,
            SubmissionQualityAssessment.submission_id == Submission.id,
        ).filter(
            Submission.status != "draft",
        ).group_by(owner_id).all()
        return self._count_map(rows)

    def first_reviewed_report_counts(self):
        first_review_ids = self.session.query(
            SubmissionReviewHistory.submission_id.label("submission_id"),
            func.min(SubmissionReviewHistory.id).label("first_review_id"),
        ).filter(
            SubmissionReviewHistory.event_type == "review_confirmed",
        ).group_by(SubmissionReviewHistory.submission_id).subquery()
        rows = self.session.query(
            SubmissionReviewHistory.reviewer_user_id,
            func.count(SubmissionReviewHistory.id),
        ).join(
            first_review_ids,
            first_review_ids.c.first_review_id == SubmissionReviewHistory.id,
        ).group_by(SubmissionReviewHistory.reviewer_user_id).all()
        return self._count_map(rows)

    def input_error_report_counts(self):
        rows = self.session.query(
            SubmissionQualityAssessment.input_user_id,
            func.count(SubmissionQualityAssessment.submission_id),
        ).filter(
            SubmissionQualityAssessment.is_error_report.is_(True),
        ).group_by(SubmissionQualityAssessment.input_user_id).all()
        return self._count_map(rows)

    def reviewer_error_field_counts(self):
        rows = self.session.query(
            SubmissionReviewHistory.reviewer_user_id,
            func.count(SubmissionReviewFieldHistory.id),
        ).join(
            SubmissionReviewFieldHistory,
            SubmissionReviewFieldHistory.event_id == SubmissionReviewHistory.id,
        ).filter(
            SubmissionReviewHistory.event_type.in_((
                "input_confirmed",
                "input_corrected",
                "input_correction",
            )),
            SubmissionReviewFieldHistory.reviewer_error.is_(True),
        ).group_by(SubmissionReviewHistory.reviewer_user_id).all()
        return self._count_map(rows)
