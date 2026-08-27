from server.repositories.submission_repository import SubmissionRepository
from server.services.review_workflow_service import ReviewWorkflowService


def evaluate_submission_access(submission, current_user: dict, db) -> tuple[bool, bool]:
    """Return whether a user may open a submission and whether they may review it."""

    can_review = ReviewWorkflowService.can_review_submission(
        submission,
        current_user,
        db,
    )
    is_active_input = SubmissionRepository(db).is_active_input_assignee(
        submission,
        current_user.get("id"),
    )
    can_access = (
        current_user.get("role") == "admin"
        or is_active_input
        or can_review
    )
    return can_access, can_review
