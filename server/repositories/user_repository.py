from server.models import (
    AssignedDocument,
    AssignedDocumentReviewAssignment,
    ServerFolderImportReviewer,
    Submission,
    SubmissionReviewAssignment,
    Task,
    User,
    UserCapability,
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

    def detach_references_and_delete(self, user: User) -> None:
        user_id = user.id
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
        self.delete(user)
