from server.models import ServerFolderImportJob, ServerFolderImportReviewer
from server.repositories.base import BaseRepository


class ServerFolderRepository(BaseRepository[ServerFolderImportJob]):
    model = ServerFolderImportJob

    def reviewer_ids(self, job_id: int) -> list[int]:
        return [
            row.reviewer_user_id
            for row in self.session.query(ServerFolderImportReviewer).filter(
                ServerFolderImportReviewer.job_id == job_id
            ).all()
        ]

    def add_reviewers(self, job_id: int, reviewer_ids: list[int]) -> None:
        self.session.add_all([
            ServerFolderImportReviewer(
                job_id=job_id,
                reviewer_user_id=reviewer_id,
            )
            for reviewer_id in reviewer_ids
        ])
