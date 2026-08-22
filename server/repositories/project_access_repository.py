from server.models import Project, ProjectMember


class ProjectAccessRepository:
    """Read-only project membership queries used by authorization policies."""

    def __init__(self, session):
        self.session = session

    def project_exists(self, project_id: int) -> bool:
        return self.session.query(Project.id).filter(Project.id == project_id).first() is not None

    def user_has_active_role(
        self,
        project_id: int,
        user_id: int,
        member_role: str,
    ) -> bool:
        return self.session.query(ProjectMember.project_id).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.member_role == member_role,
            ProjectMember.is_active.is_(True),
        ).first() is not None
