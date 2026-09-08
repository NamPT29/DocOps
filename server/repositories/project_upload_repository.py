from sqlalchemy import func

from server.models import (
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    ProjectUploadFile,
    ProjectUploadSession,
)


class ProjectUploadRepository:
    def __init__(self, session):
        self.session = session

    def lock_project(self, project_id):
        return (
            self.session.query(Project)
            .filter(Project.id == project_id)
            .with_for_update()
            .first()
        )

    def get_session(self, session_id):
        return self.session.get(ProjectUploadSession, session_id)

    def lock_session(self, session_id):
        return (
            self.session.query(ProjectUploadSession)
            .filter(ProjectUploadSession.id == session_id)
            .with_for_update()
            .first()
        )

    def find_session_by_client_key(self, project_id, client_session_key):
        return (
            self.session.query(ProjectUploadSession)
            .filter(
                ProjectUploadSession.project_id == project_id,
                ProjectUploadSession.client_session_key == client_session_key,
            )
            .with_for_update()
            .first()
        )

    def list_session_files(self, session_id):
        return (
            self.session.query(ProjectUploadFile)
            .filter(ProjectUploadFile.session_id == session_id)
            .order_by(ProjectUploadFile.id)
            .all()
        )

    def lock_session_file(self, session_id, file_id):
        return (
            self.session.query(ProjectUploadFile)
            .filter(
                ProjectUploadFile.id == file_id,
                ProjectUploadFile.session_id == session_id,
            )
            .with_for_update()
            .first()
        )

    def lock_session_files(self, session_id):
        return (
            self.session.query(ProjectUploadFile)
            .filter(ProjectUploadFile.session_id == session_id)
            .order_by(ProjectUploadFile.id)
            .with_for_update()
            .all()
        )

    def count_session_files_by_status(self, session_id, status):
        return (
            self.session.query(func.count(ProjectUploadFile.id))
            .filter(
                ProjectUploadFile.session_id == session_id,
                ProjectUploadFile.status == status,
            )
            .scalar()
            or 0
        )

    def list_open_sessions_with_latest_file_activity(self):
        return (
            self.session.query(
                ProjectUploadSession,
                func.max(ProjectUploadFile.updated_at).label("latest_file_activity"),
            )
            .outerjoin(
                ProjectUploadFile,
                ProjectUploadFile.session_id == ProjectUploadSession.id,
            )
            .filter(ProjectUploadSession.status.notin_(("completed", "cancelled")))
            .group_by(ProjectUploadSession.id)
            .all()
        )

    def asset_identities(self, project_id):
        return (
            self.session.query(
                ProjectDocumentAsset.normalized_relative_path,
                ProjectDocumentAsset.content_sha256,
                ProjectDocumentAsset.byte_size,
                ProjectDocumentAsset.status,
            )
            .filter(ProjectDocumentAsset.project_id == project_id)
            .all()
        )

    def find_case(self, project_id, case_key):
        return (
            self.session.query(ProjectCase)
            .filter(
                ProjectCase.project_id == project_id,
                ProjectCase.case_key == case_key,
            )
            .first()
        )

    def find_report(self, case_id, report_key):
        return (
            self.session.query(ProjectReportUnit)
            .filter(
                ProjectReportUnit.case_id == case_id,
                ProjectReportUnit.report_key == report_key,
            )
            .first()
        )

    def find_exact_asset(self, project_id, normalized_relative_path, content_sha256, byte_size):
        return (
            self.session.query(ProjectDocumentAsset)
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.normalized_relative_path == normalized_relative_path,
                ProjectDocumentAsset.content_sha256 == content_sha256,
                ProjectDocumentAsset.byte_size == byte_size,
            )
            .first()
        )

    def mark_other_active_path_assets_replaced(self, project_id, normalized_relative_path):
        return (
            self.session.query(ProjectDocumentAsset)
            .filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.normalized_relative_path == normalized_relative_path,
                ProjectDocumentAsset.status == "active",
            )
            .update(
                {ProjectDocumentAsset.status: "replaced"},
                synchronize_session=False,
            )
        )
