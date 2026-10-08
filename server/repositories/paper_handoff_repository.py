from typing import List, Optional
from server.models import Project, ProjectCase, User
from server.models_paper import CasePaperHandoff

class PaperHandoffRepository:
    def __init__(self, session):
        self.session = session

    def get_project(self, project_id: int) -> Optional[Project]:
        return self.session.query(Project).filter(Project.id == project_id).first()

    def get_case(self, project_id: int, case_id: int) -> Optional[ProjectCase]:
        return self.session.query(ProjectCase).filter(
            ProjectCase.id == case_id,
            ProjectCase.project_id == project_id
        ).first()

    def get_handoffs_for_project(self, project_id: int) -> List[CasePaperHandoff]:
        return self.session.query(CasePaperHandoff).filter(
            CasePaperHandoff.project_id == project_id
        ).all()

    def get_cases_for_project(self, project_id: int) -> List[ProjectCase]:
        return self.session.query(ProjectCase).filter(
            ProjectCase.project_id == project_id
        ).all()

    def get_handoff_by_milestone(self, case_id: int, milestone: str) -> Optional[CasePaperHandoff]:
        return self.session.query(CasePaperHandoff).filter(
            CasePaperHandoff.case_id == case_id,
            CasePaperHandoff.milestone == milestone
        ).first()

    def get_handoffs_for_case(self, case_id: int) -> List[CasePaperHandoff]:
        return self.session.query(CasePaperHandoff).filter(
            CasePaperHandoff.case_id == case_id
        ).all()

    def add_handoff(self, handoff: CasePaperHandoff):
        self.session.add(handoff)

    def delete_handoff(self, handoff: CasePaperHandoff):
        self.session.delete(handoff)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self.session.query(User).filter(User.id == user_id).first()

    def users_by_ids(self, user_ids: set) -> dict:
        if not user_ids:
            return {}
        users = self.session.query(User).filter(User.id.in_(user_ids)).all()
        return {u.id: u for u in users}
