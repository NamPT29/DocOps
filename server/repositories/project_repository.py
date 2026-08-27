from sqlalchemy import and_, case, func

from server.models import (
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Submission,
    SubmissionQualityAssessment,
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

    def member_report_stats_by_project(self, project_ids):
        result = {project_id: [] for project_id in project_ids}
        if not project_ids:
            return result

        attributed_user_id = func.coalesce(
            SubmissionQualityAssessment.input_user_id,
            Submission.created_by_user_id,
        )
        rows = (
            self.session.query(
                ProjectDocumentAsset.project_id,
                attributed_user_id.label("user_id"),
                func.sum(
                    case((SubmissionQualityAssessment.is_error_report.is_(True), 1), else_=0)
                ).label("error_reports"),
                func.sum(
                    case((Submission.status == "pending_review", 1), else_=0)
                ).label("pending_review_reports"),
                func.count(Submission.id).label("total_reports"),
            )
            .join(
                Submission,
                Submission.assigned_document_id
                == ProjectDocumentAsset.assigned_document_id,
            )
            .outerjoin(
                SubmissionQualityAssessment,
                SubmissionQualityAssessment.submission_id == Submission.id,
            )
            .filter(
                ProjectDocumentAsset.project_id.in_(project_ids),
                attributed_user_id.is_not(None),
            )
            .group_by(ProjectDocumentAsset.project_id, attributed_user_id)
            .order_by(ProjectDocumentAsset.project_id, attributed_user_id)
            .all()
        )
        for project_id, user_id, error_reports, pending_reports, total_reports in rows:
            result[project_id].append({
                "user_id": int(user_id),
                "error_reports": int(error_reports or 0),
                "pending_review_reports": int(pending_reports or 0),
                "total_reports": int(total_reports or 0),
            })
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

        submission_summary = (
            self.session.query(
                ProjectDocumentAsset.report_unit_id.label("report_unit_id"),
                func.count(Submission.id).label("submission_count"),
                func.sum(case((Submission.status == "completed", 1), else_=0)).label(
                    "approved_count"
                ),
            )
            .outerjoin(
                Submission,
                Submission.assigned_document_id == ProjectDocumentAsset.assigned_document_id,
            )
            .filter(ProjectDocumentAsset.project_id.in_(project_ids))
            .group_by(ProjectDocumentAsset.report_unit_id)
            .subquery()
        )
        report_rows = (
            self.session.query(
                ProjectReportUnit.project_id,
                func.count(ProjectReportUnit.id),
                func.sum(
                    case((submission_summary.c.submission_count > 0, 1), else_=0)
                ),
                func.sum(
                    case(
                        (
                            and_(
                                submission_summary.c.submission_count > 0,
                                submission_summary.c.approved_count
                                == submission_summary.c.submission_count,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .outerjoin(
                submission_summary,
                submission_summary.c.report_unit_id == ProjectReportUnit.id,
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
