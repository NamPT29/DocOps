from sqlalchemy import case, func

from server.models import (
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
)
from server.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    def list_all(self):
        return self.session.query(Project).order_by(Project.created_at.desc(), Project.id.desc()).all()

    def list_for_user(self, user_id):
        return (
            self.session.query(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .filter(
                ProjectMember.user_id == user_id,
                ProjectMember.is_active.is_(True),
            )
            .distinct()
            .order_by(Project.created_at.desc(), Project.id.desc())
            .all()
        )

    def lock_for_update(self, project_id):
        return (
            self.session.query(Project)
            .filter(Project.id == project_id)
            .with_for_update()
            .first()
        )

    def member_ids_by_role(self, project_ids):
        result = {
            project_id: {"input": [], "reviewer": []}
            for project_id in project_ids
        }
        if not project_ids:
            return result
        rows = (
            self.session.query(
                ProjectMember.project_id,
                ProjectMember.member_role,
                ProjectMember.user_id,
            )
            .filter(
                ProjectMember.project_id.in_(project_ids),
                ProjectMember.is_active.is_(True),
            )
            .order_by(ProjectMember.project_id, ProjectMember.member_role, ProjectMember.user_id)
            .all()
        )
        for project_id, member_role, user_id in rows:
            result[project_id][member_role].append(user_id)
        return result

    def metrics_by_project(self, project_ids):
        result = {
            project_id: {
                "total_cases": 0,
                "input_assigned_cases": 0,
                "input_unassigned_cases": 0,
                "reviewer_assigned_cases": 0,
                "reviewer_unassigned_cases": 0,
                "total_pdfs": 0,
                "error_pdfs": 0,
                "entered_reports": 0,
                "required_reports": 0,
                "approved_reports": 0,
            }
            for project_id in project_ids
        }
        if not project_ids:
            return result

        case_rows = (
            self.session.query(
                ProjectCase.project_id,
                func.count(ProjectCase.id),
                func.sum(case((ProjectCase.assigned_input_user_id.is_not(None), 1), else_=0)),
                func.sum(case((ProjectCase.assigned_input_user_id.is_(None), 1), else_=0)),
                func.sum(case((ProjectCase.assigned_reviewer_user_id.is_not(None), 1), else_=0)),
                func.sum(case((ProjectCase.assigned_reviewer_user_id.is_(None), 1), else_=0)),
            )
            .filter(ProjectCase.project_id.in_(project_ids))
            .group_by(ProjectCase.project_id)
            .all()
        )
        for row in case_rows:
            metrics = result[row[0]]
            (
                metrics["total_cases"],
                metrics["input_assigned_cases"],
                metrics["input_unassigned_cases"],
                metrics["reviewer_assigned_cases"],
                metrics["reviewer_unassigned_cases"],
            ) = [int(value or 0) for value in row[1:]]

        report_rows = (
            self.session.query(
                ProjectReportUnit.project_id,
                func.count(ProjectReportUnit.id),
                func.sum(case((ProjectReportUnit.status != "not_entered", 1), else_=0)),
                func.sum(case((ProjectReportUnit.status == "approved", 1), else_=0)),
            )
            .filter(ProjectReportUnit.project_id.in_(project_ids))
            .group_by(ProjectReportUnit.project_id)
            .all()
        )
        for project_id, required_reports, entered_reports, approved_reports in report_rows:
            metrics = result[project_id]
            metrics["required_reports"] = int(required_reports or 0)
            metrics["entered_reports"] = int(entered_reports or 0)
            metrics["approved_reports"] = int(approved_reports or 0)

        asset_rows = (
            self.session.query(
                ProjectDocumentAsset.project_id,
                func.sum(case((ProjectDocumentAsset.status == "active", 1), else_=0)),
                func.sum(case((ProjectDocumentAsset.status == "error", 1), else_=0)),
            )
            .filter(ProjectDocumentAsset.project_id.in_(project_ids))
            .group_by(ProjectDocumentAsset.project_id)
            .all()
        )
        for project_id, total_pdfs, error_pdfs in asset_rows:
            result[project_id]["total_pdfs"] = int(total_pdfs or 0)
            result[project_id]["error_pdfs"] = int(error_pdfs or 0)
        return result
