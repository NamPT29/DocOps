from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Submission,
)


class ProjectWorkspaceRepository:
    def __init__(self, session):
        self.session = session

    def get_project(self, project_id):
        return self.session.get(Project, project_id)

    def user_is_active_member(self, project_id, user_id):
        return self.session.query(ProjectMember.project_id).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        ).first() is not None

    def list_assets_with_cases(self, project_id):
        return self.session.query(
            ProjectDocumentAsset,
            ProjectCase,
        ).join(
            ProjectCase,
            ProjectCase.id == ProjectDocumentAsset.case_id,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
        ).order_by(
            ProjectCase.case_key,
            ProjectDocumentAsset.relative_path,
            ProjectDocumentAsset.id,
        ).all()

    def list_input_workspace_assets(self, project_id, user_id):
        return self.session.query(
            ProjectDocumentAsset,
            ProjectCase,
            ProjectReportUnit,
            AssignedDocument,
        ).join(
            ProjectCase,
            ProjectCase.id == ProjectDocumentAsset.case_id,
        ).join(
            ProjectReportUnit,
            ProjectReportUnit.id == ProjectDocumentAsset.report_unit_id,
        ).outerjoin(
            AssignedDocument,
            AssignedDocument.id == ProjectDocumentAsset.assigned_document_id,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
            ProjectCase.assigned_input_user_id == user_id,
        ).order_by(
            ProjectCase.case_key,
            ProjectReportUnit.report_key,
            ProjectDocumentAsset.relative_path,
            ProjectDocumentAsset.id,
        ).all()

    def get_document(self, document_id):
        return self.session.get(AssignedDocument, document_id)

    def submission_statuses_by_document(self, document_ids):
        result = {document_id: [] for document_id in document_ids}
        if not document_ids:
            return result
        rows = self.session.query(
            Submission.assigned_document_id,
            Submission.status,
        ).filter(
            Submission.assigned_document_id.in_(document_ids),
        ).all()
        for document_id, status in rows:
            result.setdefault(document_id, []).append(status)
        return result

    def add_document(self, document):
        self.session.add(document)
        return document

    def get_document_path(self, document_id):
        return self.session.query(AssignedDocumentPath).filter(
            AssignedDocumentPath.document_id == document_id,
        ).first()

    def add_document_path(self, path):
        self.session.add(path)
        return path

    def get_document_folder(self, document_id):
        return self.session.query(AssignedDocumentFolder).filter(
            AssignedDocumentFolder.document_id == document_id,
        ).first()

    def add_document_folder(self, folder):
        self.session.add(folder)
        return folder

    def get_document_review_assignment(self, document_id):
        return self.session.query(AssignedDocumentReviewAssignment).filter(
            AssignedDocumentReviewAssignment.document_id == document_id,
        ).first()

    def add_document_review_assignment(self, assignment):
        self.session.add(assignment)
        return assignment

    def delete_document_review_assignment(self, assignment):
        self.session.delete(assignment)
