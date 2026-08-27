from datetime import datetime, timezone

from sqlalchemy import and_, func, or_

from server.models import (
    ProjectCase,
    ProjectDocumentAsset,
    Submission,
    SubmissionReviewFieldHistory,
    SubmissionReviewHistory,
    SubmissionReviewSeen,
)
from server.repositories.base import BaseRepository


class SubmissionReviewHistoryRepository(BaseRepository[SubmissionReviewHistory]):
    model = SubmissionReviewHistory

    @staticmethod
    def correction_token(review_event_id: int) -> str:
        return f"input-confirmation:{review_event_id}"

    def latest_confirmed_review(
        self,
        submission_id: int,
    ) -> SubmissionReviewHistory | None:
        return (
            self.session.query(SubmissionReviewHistory)
            .filter(
                SubmissionReviewHistory.submission_id == submission_id,
                SubmissionReviewHistory.event_type == "review_confirmed",
            )
            .order_by(SubmissionReviewHistory.id.desc())
            .first()
        )

    def get_input_correction(
        self,
        review_event_id: int,
    ) -> SubmissionReviewHistory | None:
        return (
            self.session.query(SubmissionReviewHistory)
            .filter(
                SubmissionReviewHistory.review_event_id == review_event_id,
                SubmissionReviewHistory.event_type.in_((
                    "input_confirmed",
                    "input_corrected",
                    "input_correction",
                )),
            )
            .first()
        )

    def add_field(self, field: SubmissionReviewFieldHistory) -> SubmissionReviewFieldHistory:
        self.session.add(field)
        return field

    def field_names_for_event(self, event_id: int) -> list[str]:
        rows = (
            self.session.query(SubmissionReviewFieldHistory.field_name)
            .filter(SubmissionReviewFieldHistory.event_id == event_id)
            .order_by(SubmissionReviewFieldHistory.id)
            .all()
        )
        return [field_name for (field_name,) in rows]

    def corrected_field_names(self, review_event_id: int) -> list[str]:
        rows = (
            self.session.query(SubmissionReviewFieldHistory)
            .join(
                SubmissionReviewHistory,
                SubmissionReviewHistory.id == SubmissionReviewFieldHistory.event_id,
            )
            .filter(
                SubmissionReviewHistory.event_type.in_((
                    "input_confirmed",
                    "input_corrected",
                    "input_correction",
                )),
                SubmissionReviewHistory.review_event_id == review_event_id,
            )
            .order_by(SubmissionReviewFieldHistory.id)
            .all()
        )
        return [
            row.field_name
            for row in rows
            if row.final_value_json != row.reviewer_value_json
        ]

    def unread_submission_ids(self, input_user_id: int) -> set[int]:
        latest_reviews = (
            self.session.query(
                SubmissionReviewHistory.submission_id.label("submission_id"),
                func.max(SubmissionReviewHistory.id).label("event_id"),
            )
            .filter(
                SubmissionReviewHistory.event_type == "review_confirmed",
            )
            .group_by(SubmissionReviewHistory.submission_id)
            .subquery()
        )
        rows = (
            self.session.query(SubmissionReviewHistory.submission_id)
            .join(
                latest_reviews,
                latest_reviews.c.event_id == SubmissionReviewHistory.id,
            )
            .join(
                Submission,
                Submission.id == SubmissionReviewHistory.submission_id,
            )
            .outerjoin(
                ProjectDocumentAsset,
                ProjectDocumentAsset.assigned_document_id
                == Submission.assigned_document_id,
            )
            .outerjoin(
                ProjectCase,
                ProjectCase.id == ProjectDocumentAsset.case_id,
            )
            .outerjoin(
                SubmissionReviewSeen,
                and_(
                    SubmissionReviewSeen.submission_id
                    == SubmissionReviewHistory.submission_id,
                    SubmissionReviewSeen.user_id == input_user_id,
                ),
            )
            .filter(
                Submission.status == "pending_input_confirmation",
                or_(
                    ProjectCase.assigned_input_user_id == input_user_id,
                    and_(
                        ProjectDocumentAsset.id.is_(None),
                        Submission.created_by_user_id == input_user_id,
                    ),
                ),
                or_(
                    SubmissionReviewSeen.review_event_id.is_(None),
                    SubmissionReviewSeen.review_event_id
                    < SubmissionReviewHistory.id,
                ),
            )
            .distinct()
            .all()
        )
        return {submission_id for (submission_id,) in rows}

    def mark_seen(
        self,
        submission_id: int,
        user_id: int,
        review_event_id: int,
    ) -> SubmissionReviewSeen:
        seen = self.session.get(
            SubmissionReviewSeen,
            {"submission_id": submission_id, "user_id": user_id},
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if seen is None:
            seen = SubmissionReviewSeen(
                submission_id=submission_id,
                user_id=user_id,
                review_event_id=review_event_id,
                seen_at=now,
            )
            self.session.add(seen)
        elif seen.review_event_id < review_event_id:
            seen.review_event_id = review_event_id
            seen.seen_at = now
        return seen
