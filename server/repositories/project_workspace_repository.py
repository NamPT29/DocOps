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

    def documents_by_ids(self, document_ids):
        if not document_ids:
            return {}
        return {
            document.id: document
            for document in self.session.query(AssignedDocument).filter(
                AssignedDocument.id.in_(document_ids),
            ).all()
        }

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

    def submission_summary_by_report(self, report_unit_ids):
        result = {
            report_unit_id: {"submission_count": 0, "approved_count": 0}
            for report_unit_id in report_unit_ids
        }
        if not report_unit_ids:
            return result
        rows = self.session.query(
            ProjectDocumentAsset.report_unit_id,
            Submission.status,
        ).join(
            Submission,
            Submission.assigned_document_id == ProjectDocumentAsset.assigned_document_id,
        ).filter(
            ProjectDocumentAsset.report_unit_id.in_(report_unit_ids),
        ).all()
        for report_unit_id, status in rows:
            result[report_unit_id]["submission_count"] += 1
            if status == "completed":
                result[report_unit_id]["approved_count"] += 1
        return result

    def add_document(self, document):
        self.session.add(document)
        return document

    def get_document_path(self, document_id):
        return self.session.query(AssignedDocumentPath).filter(
            AssignedDocumentPath.document_id == document_id,
        ).first()

    def document_paths_by_ids(self, document_ids):
        if not document_ids:
            return {}
        return {
            path.document_id: path
            for path in self.session.query(AssignedDocumentPath).filter(
                AssignedDocumentPath.document_id.in_(document_ids),
            ).all()
        }

    def add_document_path(self, path):
        self.session.add(path)
        return path

    def get_document_folder(self, document_id):
        return self.session.query(AssignedDocumentFolder).filter(
            AssignedDocumentFolder.document_id == document_id,
        ).first()

    def document_folders_by_ids(self, document_ids):
        if not document_ids:
            return {}
        return {
            folder.document_id: folder
            for folder in self.session.query(AssignedDocumentFolder).filter(
                AssignedDocumentFolder.document_id.in_(document_ids),
            ).all()
        }

    def add_document_folder(self, folder):
        self.session.add(folder)
        return folder

    def get_document_review_assignment(self, document_id):
        return self.session.query(AssignedDocumentReviewAssignment).filter(
            AssignedDocumentReviewAssignment.document_id == document_id,
        ).first()

    def document_review_assignments_by_ids(self, document_ids):
        if not document_ids:
            return {}
        return {
            assignment.document_id: assignment
            for assignment in self.session.query(
                AssignedDocumentReviewAssignment,
            ).filter(
                AssignedDocumentReviewAssignment.document_id.in_(document_ids),
            ).all()
        }

    def add_document_review_assignment(self, assignment):
        self.session.add(assignment)
        return assignment

    def delete_document_review_assignment(self, assignment):
        self.session.delete(assignment)
