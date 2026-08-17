from sqlalchemy import func, or_

from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentReviewAssignment,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
)
from server.repositories.base import BaseRepository
from server.utils.folder_utils import folder_path_key, normalize_folder_path


class ReviewRepository(BaseRepository[SubmissionReviewAssignment]):
    model = SubmissionReviewAssignment

    def get_submission_assignment(
        self,
        submission_id: int,
    ) -> SubmissionReviewAssignment | None:
        return self.session.query(SubmissionReviewAssignment).filter(
            SubmissionReviewAssignment.submission_id == submission_id
        ).first()

    def get_document_assignment(
        self,
        document_id: int,
    ) -> AssignedDocumentReviewAssignment | None:
        return self.session.query(AssignedDocumentReviewAssignment).filter(
            AssignedDocumentReviewAssignment.document_id == document_id
        ).first()

    def get_folder_reviewer(self, folder_path: str) -> int | None:
        if not folder_path or folder_path == "__ROOT__":
            return None
        assignment = self.session.query(AssignedDocumentReviewAssignment.reviewer_user_id).join(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocumentReviewAssignment.document_id
        ).filter(
            AssignedDocumentFolder.folder_group == folder_path
        ).first()
        return assignment[0] if assignment else None

    def delete_document_assignments(self, document_ids: list[int]) -> int:
        if not document_ids:
            return 0
        return self.session.query(AssignedDocumentReviewAssignment).filter(
            AssignedDocumentReviewAssignment.document_id.in_(document_ids)
        ).delete(synchronize_session=False)

    def pending_document_assignments(self, reviewer_id: int) -> list:
        return self.session.query(AssignedDocumentReviewAssignment).join(
            AssignedDocument,
            AssignedDocument.id == AssignedDocumentReviewAssignment.document_id,
        ).filter(
            AssignedDocumentReviewAssignment.reviewer_user_id == reviewer_id,
            AssignedDocument.status == "pending",
        ).all()

    def active_submission_assignments(self, reviewer_id: int) -> list[tuple]:
        return self.session.query(
            SubmissionReviewAssignment,
            Submission,
        ).join(
            Submission,
            Submission.id == SubmissionReviewAssignment.submission_id,
        ).filter(
            SubmissionReviewAssignment.reviewer_user_id == reviewer_id,
            Submission.status.in_(["pending_review", "rejected"]),
        ).all()

    def pending_assignment_context(self) -> tuple[list[Submission], dict, dict]:
        pending = self.session.query(Submission).filter(
            Submission.status == "pending_review"
        ).all()
        if not pending:
            return [], {}, {}
        submission_ids = [submission.id for submission in pending]
        assignments = {
            assignment.submission_id: assignment
            for assignment in self.session.query(SubmissionReviewAssignment).filter(
                SubmissionReviewAssignment.submission_id.in_(submission_ids)
            ).all()
        }
        document_ids = {
            submission.assigned_document_id
            for submission in pending
            if submission.assigned_document_id is not None
        }
        document_reviewers = {
            assignment.document_id: assignment.reviewer_user_id
            for assignment in self.session.query(AssignedDocumentReviewAssignment).filter(
                AssignedDocumentReviewAssignment.document_id.in_(document_ids)
            ).all()
        } if document_ids else {}
        return pending, assignments, document_reviewers

    def assignment_map(self, submissions: list[Submission]) -> dict[int, int | None]:
        if not submissions:
            return {}
        submission_ids = [submission.id for submission in submissions]
        reviewer_by_submission = {
            assignment.submission_id: assignment.reviewer_user_id
            for assignment in self.session.query(SubmissionReviewAssignment).filter(
                SubmissionReviewAssignment.submission_id.in_(submission_ids)
            ).all()
        }
        document_ids = {
            submission.assigned_document_id
            for submission in submissions
            if submission.assigned_document_id is not None
            and reviewer_by_submission.get(submission.id) is None
        }
        reviewer_by_document = {
            assignment.document_id: assignment.reviewer_user_id
            for assignment in self.session.query(AssignedDocumentReviewAssignment).filter(
                AssignedDocumentReviewAssignment.document_id.in_(document_ids)
            ).all()
        } if document_ids else {}
        for submission in submissions:
            if reviewer_by_submission.get(submission.id) is not None:
                continue
            reviewer_id = reviewer_by_document.get(submission.assigned_document_id)
            if reviewer_id is not None:
                reviewer_by_submission[submission.id] = reviewer_id
        return reviewer_by_submission

    def delete_for_submissions(self, submission_ids: list[int]) -> int:
        if not submission_ids:
            return 0
        return self.session.query(SubmissionReviewAssignment).filter(
            SubmissionReviewAssignment.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)

    def reviewer_folder_rows(self, reviewer_id: int, template_id: int | None) -> list[tuple]:
        from sqlalchemy import func
        query = self.session.query(
            AssignedDocumentFolder.folder_group,
            User.username,
            Template.name,
            func.count(AssignedDocument.id),
        ).join(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).join(
            AssignedDocumentReviewAssignment,
            AssignedDocumentReviewAssignment.document_id == AssignedDocument.id,
        ).join(
            User,
            User.id == AssignedDocument.assigned_to_user_id,
        ).outerjoin(
            Template,
            Template.id == AssignedDocument.template_id,
        ).filter(
            AssignedDocumentReviewAssignment.reviewer_user_id == reviewer_id,
            AssignedDocument.assigned_to_user_id != reviewer_id,
        )
        if template_id:
            query = query.filter(AssignedDocument.template_id == template_id)
        return query.group_by(
            AssignedDocumentFolder.folder_group,
            User.username,
            Template.name,
        ).order_by(
            AssignedDocumentFolder.folder_group,
        ).all()

    def reviewer_submitted_counts(
        self,
        reviewer_id: int,
        template_id: int | None,
    ) -> list[tuple[str | None, int]]:
        query = self.session.query(
            Submission.folder_path,
            func.count(Submission.id),
        ).join(
            SubmissionReviewAssignment,
            SubmissionReviewAssignment.submission_id == Submission.id,
        ).filter(
            SubmissionReviewAssignment.reviewer_user_id == reviewer_id,
            Submission.created_by_user_id != reviewer_id,
            Submission.status == "pending_review",
        )
        if template_id:
            query = query.filter(Submission.template_id == template_id)
        return query.group_by(Submission.folder_path).all()

    def reviewer_has_folder(
        self,
        reviewer_id: int,
        folder_path: str,
        template_id: int | None,
    ) -> bool:
        query = self.session.query(AssignedDocument.id).join(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).join(
            AssignedDocumentReviewAssignment,
            AssignedDocumentReviewAssignment.document_id == AssignedDocument.id,
        ).filter(
            AssignedDocumentFolder.folder_group == folder_path,
            AssignedDocumentReviewAssignment.reviewer_user_id == reviewer_id,
            AssignedDocument.assigned_to_user_id != reviewer_id,
        )
        if template_id:
            query = query.filter(AssignedDocument.template_id == template_id)
        return query.first() is not None

    def reviewer_folder_submissions(
        self,
        reviewer_id: int,
        folder_path: str,
        template_id: int | None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[Submission]:
        normalized = normalize_folder_path(folder_path)
        query = self.session.query(Submission).join(
            SubmissionReviewAssignment,
            SubmissionReviewAssignment.submission_id == Submission.id,
        ).filter(
            SubmissionReviewAssignment.reviewer_user_id == reviewer_id,
            Submission.created_by_user_id != reviewer_id,
            Submission.status == "pending_review",
            Submission.folder_path_key == folder_path_key(normalized),
            Submission.folder_path == normalized,
        )
        if template_id:
            query = query.filter(Submission.template_id == template_id)
        query = query.order_by(
            Submission.created_at.desc(),
            Submission.id.desc(),
        )
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def reviewer_folder_submissions_count(
        self,
        reviewer_id: int,
        folder_path: str,
        template_id: int | None,
    ) -> int:
        normalized = normalize_folder_path(folder_path)
        query = self.session.query(Submission.id).join(
            SubmissionReviewAssignment,
            SubmissionReviewAssignment.submission_id == Submission.id,
        ).filter(
            SubmissionReviewAssignment.reviewer_user_id == reviewer_id,
            Submission.created_by_user_id != reviewer_id,
            Submission.status == "pending_review",
            Submission.folder_path_key == folder_path_key(normalized),
            Submission.folder_path == normalized,
        )
        if template_id:
            query = query.filter(Submission.template_id == template_id)
        return query.count()

    def reviewer_has_linked_submission(
        self,
        reviewer_id: int,
        document_id: int,
        uuid_filename: str,
    ) -> bool:
        assignment = self.session.query(SubmissionReviewAssignment).filter(
            SubmissionReviewAssignment.reviewer_user_id == reviewer_id,
        ).first()
        if not assignment:
            return False
        return self.session.query(Submission).filter(
            Submission.id == assignment.submission_id,
            or_(
                Submission.assigned_document_id == document_id,
                Submission.data_json.contains(uuid_filename),
            ),
        ).first() is not None

    def active_review_counts(self) -> dict[int, int]:
        rows = self.session.query(
            SubmissionReviewAssignment.reviewer_user_id,
            func.count(SubmissionReviewAssignment.submission_id),
        ).join(
            Submission,
            Submission.id == SubmissionReviewAssignment.submission_id,
        ).filter(
            Submission.status.in_(["pending_review", "rejected"]),
        ).group_by(
            SubmissionReviewAssignment.reviewer_user_id
        ).all()
        return {reviewer_id: count for reviewer_id, count in rows}
