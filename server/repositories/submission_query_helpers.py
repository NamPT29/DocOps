from sqlalchemy import func

from server.models import Submission


DUPLICATE_REPORT_STATUSES = ("pending_review", "rejected", "approved")


def duplicate_document_ids_query(session):
    """Document IDs linked to more than one workflow report."""
    return session.query(Submission.assigned_document_id).filter(
        Submission.assigned_document_id.isnot(None),
        Submission.status.in_(DUPLICATE_REPORT_STATUSES),
    ).group_by(
        Submission.assigned_document_id,
    ).having(
        func.count(Submission.id) > 1,
    )
