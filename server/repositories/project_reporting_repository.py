from sqlalchemy import func

from server.models import Project, ProjectCase, ProjectDocumentAsset, Submission


PROJECT_REVIEW_STATUSES = ("pending_review",)
PROJECT_COMPLETED_STATUSES = ("completed",)
PROJECT_EXPORT_ALL_STATUSES = (
    "pending_review",
    "pending_input_confirmation",
    "completed",
)


class ProjectReportingRepository:
    def __init__(self, session):
        self.session = session

    def get_project(self, project_id):
        return self.session.get(Project, project_id)

    def _project_submission_query(self, project_id, statuses, folder_path=None):
        query = self.session.query(Submission, ProjectCase).join(
            ProjectDocumentAsset,
            ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id,
        ).join(
            ProjectCase,
            ProjectCase.id == ProjectDocumentAsset.case_id,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
            Submission.status.in_(statuses),
        )
        if folder_path is not None:
            query = query.filter(ProjectCase.case_key == folder_path)
        return query

    def folder_groups(self, project_id, statuses):
        return self.session.query(
            ProjectCase.case_key,
            ProjectCase.display_name,
            func.count(func.distinct(Submission.id)),
        ).join(
            ProjectDocumentAsset,
            ProjectDocumentAsset.case_id == ProjectCase.id,
        ).join(
            Submission,
            Submission.assigned_document_id == ProjectDocumentAsset.assigned_document_id,
        ).filter(
            ProjectCase.project_id == project_id,
            ProjectDocumentAsset.status == "active",
            Submission.status.in_(statuses),
        ).group_by(
            ProjectCase.id,
            ProjectCase.case_key,
            ProjectCase.display_name,
        ).order_by(
            func.lower(ProjectCase.case_key),
            ProjectCase.case_key,
            ProjectCase.id,
        ).all()

    def paginate(self, project_id, statuses, *, folder_path, page, page_size):
        query = self._project_submission_query(project_id, statuses, folder_path)
        total = query.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        rows = query.order_by(
            Submission.created_at.desc(),
            Submission.id.desc(),
        ).offset((current_page - 1) * page_size).limit(page_size).all()
        return rows, total, total_pages, current_page

    def submission_belongs_to_project(self, project_id, submission_id):
        return self.session.query(Submission.id).join(
            ProjectDocumentAsset,
            ProjectDocumentAsset.assigned_document_id == Submission.assigned_document_id,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
            Submission.id == submission_id,
        ).first() is not None

    def active_review_submissions(self, project_id, folder_path=None):
        return [
            submission
            for submission, _case_row in self._project_submission_query(
                project_id,
                PROJECT_REVIEW_STATUSES,
                folder_path,
            ).order_by(
                Submission.created_at.desc(),
                Submission.id.desc(),
            ).all()
        ]

    def submissions_for_export(self, project_id, *, include_pending_review):
        statuses = (
            PROJECT_EXPORT_ALL_STATUSES
            if include_pending_review
            else PROJECT_COMPLETED_STATUSES
        )
        return [
            submission
            for submission, _case_row in self._project_submission_query(
                project_id,
                statuses,
            ).order_by(
                func.lower(ProjectCase.case_key),
                ProjectCase.case_key,
                func.lower(ProjectDocumentAsset.normalized_relative_path),
                ProjectDocumentAsset.normalized_relative_path,
                Submission.id,
            ).all()
        ]
