from sqlalchemy import func

from server.models import (
    ArrangementDossier,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    Submission,
)
from server.repositories.base import BaseRepository


class NormalizationRepository(BaseRepository[Project]):
    """Đọc dữ liệu cho kế hoạch chuẩn hóa (G1). Chỉ đọc, không ghi."""

    model = Project

    def cases(self, project_id: int) -> list[ProjectCase]:
        return self.session.query(ProjectCase).filter(
            ProjectCase.project_id == project_id
        ).order_by(ProjectCase.id).all()

    def active_dossiers(self, project_id: int) -> list[ArrangementDossier]:
        return self.session.query(ArrangementDossier).filter(
            ArrangementDossier.project_id == project_id,
            ArrangementDossier.missing_from_import_id.is_(None),
        ).all()

    def active_assets(self, project_id: int) -> list[ProjectDocumentAsset]:
        return self.session.query(ProjectDocumentAsset).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
        ).all()

    def latest_submission_data_by_document(self, document_ids: set[int]) -> dict[int, str]:
        """data_json của lần lưu mới nhất cho từng văn bản."""
        if not document_ids:
            return {}
        latest_ids = self.session.query(func.max(Submission.id)).filter(
            Submission.assigned_document_id.in_(document_ids)
        ).group_by(Submission.assigned_document_id)
        rows = self.session.query(Submission.assigned_document_id, Submission.data_json).filter(
            Submission.id.in_(latest_ids)
        ).all()
        return {document_id: data_json for document_id, data_json in rows}

    def latest_submission_status_by_document(self, document_ids: set[int]) -> dict[int, str]:
        if not document_ids:
            return {}
        latest_ids = self.session.query(func.max(Submission.id)).filter(
            Submission.assigned_document_id.in_(document_ids)
        ).group_by(Submission.assigned_document_id)
        rows = self.session.query(Submission.assigned_document_id, Submission.status).filter(
            Submission.id.in_(latest_ids)
        ).all()
        return {document_id: status for document_id, status in rows}
