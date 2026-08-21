from collections import Counter

from server.models import Project, ProjectAssignmentHistory, ProjectCase, ProjectMember


class ProjectAssignmentRepository:
    def __init__(self, session):
        self.session = session

    def lock_project(self, project_id):
        return (
            self.session.query(Project)
            .filter(Project.id == project_id)
            .with_for_update()
            .first()
        )

    def active_member_ids(self, project_id, member_role):
        return [
            row[0]
            for row in (
                self.session.query(ProjectMember.user_id)
                .filter(
                    ProjectMember.project_id == project_id,
                    ProjectMember.member_role == member_role,
                    ProjectMember.is_active.is_(True),
                )
                .order_by(ProjectMember.user_id)
                .all()
            )
        ]

    def lock_cases(self, project_id):
        return (
            self.session.query(ProjectCase)
            .filter(ProjectCase.project_id == project_id)
            .order_by(ProjectCase.case_key, ProjectCase.id)
            .with_for_update()
            .all()
        )

    def existing_assignment_counts(self, project_id):
        input_counts = Counter()
        reviewer_counts = Counter()
        rows = (
            self.session.query(
                ProjectCase.assigned_input_user_id,
                ProjectCase.assigned_reviewer_user_id,
            )
            .filter(ProjectCase.project_id == project_id)
            .all()
        )
        for input_user_id, reviewer_user_id in rows:
            if input_user_id is not None:
                input_counts[input_user_id] += 1
            if reviewer_user_id is not None:
                reviewer_counts[reviewer_user_id] += 1
        return input_counts, reviewer_counts

    def add_history(
        self,
        *,
        project_id,
        case_id,
        assignment_role,
        from_user_id,
        to_user_id,
        changed_by_user_id,
        reason,
    ):
        self.session.add(
            ProjectAssignmentHistory(
                project_id=project_id,
                case_id=case_id,
                assignment_role=assignment_role,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                changed_by_user_id=changed_by_user_id,
                reason=reason,
            )
        )
