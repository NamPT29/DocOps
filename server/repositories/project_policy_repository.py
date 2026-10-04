from server.models import Project, ProjectPolicy, User
from server.repositories.base import BaseRepository


class ProjectPolicyRepository(BaseRepository[ProjectPolicy]):
    model = ProjectPolicy

    def for_project(self, project_id: int) -> ProjectPolicy | None:
        return self.session.query(ProjectPolicy).filter(
            ProjectPolicy.project_id == project_id
        ).first()

    def project_exists(self, project_id: int) -> bool:
        return self.session.query(Project.id).filter(Project.id == project_id).first() is not None

    def username(self, user_id: int) -> str | None:
        row = self.session.query(User.username).filter(User.id == user_id).first()
        return row[0] if row else None
