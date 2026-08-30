from sqlalchemy import func, literal, or_

from server.models import (
    AssignedDocument,
    AssignedDocumentReviewAssignment,
    Notification,
    NotificationRecipient,
    Project,
    ProjectAssignmentHistory,
    ProjectCase,
    ProjectMember,
    ProjectPdfDeletionAudit,
    ProjectUploadSession,
    ServerFolderImportJob,
    ServerFolderImportReviewer,
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewAssignment,
    SubmissionReviewHistory,
    SubmissionReviewSeen,
    SubmissionViewPresence,
    Task,
    User,
    UserCapability,
    UserLoginSession,
)
from server.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_username(self, username: str) -> User | None:
        return self.session.query(User).filter(User.username == username).first()

    def list_all(self) -> list[User]:
        return self.session.query(User).all()

    def input_user_ids(self) -> set[int]:
        return {
            user_id
            for user_id, in self.session.query(User.id).filter(
                User.role != "admin"
            ).all()
        }

    def user_map(self, user_ids: list[int] | set[int]) -> dict[int, User]:
        if not user_ids:
            return {}
        return {
            user.id: user
            for user in self.session.query(User).filter(User.id.in_(user_ids)).all()
        }

    def capability_flags(self, user_id: int) -> tuple[bool, bool]:
        can_input = bool(
            self.session.query(AssignedDocument.id).filter(
                AssignedDocument.assigned_to_user_id == user_id
            ).first()
            or self.session.query(Submission.id).filter(
                Submission.created_by_user_id == user_id
            ).first()
        )
        can_review = bool(
            self.session.query(AssignedDocumentReviewAssignment.document_id).filter(
                AssignedDocumentReviewAssignment.reviewer_user_id == user_id
            ).first()
            or self.session.query(SubmissionReviewAssignment.submission_id).filter(
                SubmissionReviewAssignment.reviewer_user_id == user_id
            ).first()
        )
        return can_input, can_review

    def capability_flags_map(
        self,
        user_ids: list[int] | set[int],
    ) -> dict[int, tuple[bool, bool]]:
        """Return input/review capability flags in one bounded query."""
        normalized_ids = {int(user_id) for user_id in user_ids}
        if not normalized_ids:
            return {}

        flags = {user_id: (False, False) for user_id in normalized_ids}
        capability_rows = self.session.query(
            AssignedDocument.assigned_to_user_id.label("user_id"),
            literal(1).label("can_input"),
            literal(0).label("can_review"),
        ).filter(
            AssignedDocument.assigned_to_user_id.in_(normalized_ids)
        ).union_all(
            self.session.query(
                Submission.created_by_user_id.label("user_id"),
                literal(1).label("can_input"),
                literal(0).label("can_review"),
            ).filter(Submission.created_by_user_id.in_(normalized_ids)),
            self.session.query(
                AssignedDocumentReviewAssignment.reviewer_user_id.label("user_id"),
                literal(0).label("can_input"),
                literal(1).label("can_review"),
            ).filter(
                AssignedDocumentReviewAssignment.reviewer_user_id.in_(normalized_ids)
            ),
            self.session.query(
                SubmissionReviewAssignment.reviewer_user_id.label("user_id"),
                literal(0).label("can_input"),
                literal(1).label("can_review"),
            ).filter(
                SubmissionReviewAssignment.reviewer_user_id.in_(normalized_ids)
            ),
        ).subquery()
        rows = self.session.query(
            capability_rows.c.user_id,
            func.max(capability_rows.c.can_input),
            func.max(capability_rows.c.can_review),
        ).group_by(capability_rows.c.user_id).all()
        for user_id, input_flag, review_flag in rows:
            flags[user_id] = (bool(input_flag), bool(review_flag))
        return flags

    def deletion_blockers(self, user_id: int) -> list[str]:
        """Return historical records whose attribution must not be erased."""
        checks = (
            ("thông báo đã tạo", Notification.id, Notification.created_by_user_id == user_id),
            (
                "kết quả đánh giá chất lượng",
                SubmissionQualityAssessment.submission_id,
                or_(
                    SubmissionQualityAssessment.input_user_id == user_id,
                    SubmissionQualityAssessment.reviewer_user_id == user_id,
                ),
            ),
            (
                "lịch sử kiểm duyệt",
                SubmissionReviewHistory.id,
                or_(
                    SubmissionReviewHistory.input_user_id == user_id,
                    SubmissionReviewHistory.reviewer_user_id == user_id,
                ),
            ),
            (
                "lịch sử nhập thư mục",
                ServerFolderImportJob.id,
                ServerFolderImportJob.created_by_user_id == user_id,
            ),
            ("dự án đã tạo", Project.id, Project.created_by_user_id == user_id),
            (
                "phiên tải tệp dự án",
                ProjectUploadSession.id,
                ProjectUploadSession.created_by_user_id == user_id,
            ),
            (
                "lịch sử phân công dự án",
                ProjectAssignmentHistory.id,
                or_(
                    ProjectAssignmentHistory.from_user_id == user_id,
                    ProjectAssignmentHistory.to_user_id == user_id,
                    ProjectAssignmentHistory.changed_by_user_id == user_id,
                ),
            ),
            (
                "nhật ký xóa PDF",
                ProjectPdfDeletionAudit.id,
                ProjectPdfDeletionAudit.deleted_by_user_id == user_id,
            ),
        )
        return [
            label
            for label, identity_column, condition in checks
            if self.session.query(identity_column).filter(condition).first() is not None
        ]

    def detach_references_and_delete(self, user: User) -> None:
        user_id = user.id
        self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(NotificationRecipient).filter(
            NotificationRecipient.user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(SubmissionReviewSeen).filter(
            SubmissionReviewSeen.user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(SubmissionViewPresence).filter(
            SubmissionViewPresence.viewer_user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(SubmissionReviewAssignment).filter(
            SubmissionReviewAssignment.reviewer_user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(AssignedDocumentReviewAssignment).filter(
            AssignedDocumentReviewAssignment.reviewer_user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(ServerFolderImportReviewer).filter(
            ServerFolderImportReviewer.reviewer_user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(UserCapability).filter(
            UserCapability.user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(ProjectMember).filter(
            ProjectMember.user_id == user_id
        ).delete(synchronize_session=False)
        self.session.query(AssignedDocument).filter(
            AssignedDocument.assigned_to_user_id == user_id
        ).update(
            {AssignedDocument.assigned_to_user_id: None},
            synchronize_session=False,
        )
        self.session.query(Submission).filter(
            Submission.created_by_user_id == user_id
        ).update(
            {Submission.created_by_user_id: None},
            synchronize_session=False,
        )
        self.session.query(Task).filter(Task.user_id == user_id).update(
            {Task.user_id: None},
            synchronize_session=False,
        )
        self.session.query(ProjectCase).filter(
            ProjectCase.assigned_input_user_id == user_id
        ).update(
            {ProjectCase.assigned_input_user_id: None},
            synchronize_session=False,
        )
        self.session.query(ProjectCase).filter(
            ProjectCase.assigned_reviewer_user_id == user_id
        ).update(
            {ProjectCase.assigned_reviewer_user_id: None},
            synchronize_session=False,
        )
        self.delete(user)
