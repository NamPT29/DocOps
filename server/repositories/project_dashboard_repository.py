from sqlalchemy import func

from server.models import ArrangementDossier, Project, ProjectCase, ProjectDocumentAsset, Submission
from server.models_scan import CaseScanPackage
from server.repositories.base import BaseRepository
from server.repositories.timesheet_repository import _chunks


class ProjectDashboardRepository(BaseRepository[Project]):
    """Đọc số liệu cho bảng tiến độ dự án (D1). Chỉ đọc, không ghi."""

    model = Project

    def dossier_counts_by_case(self, project_id: int) -> dict[int, int]:
        """Số hồ sơ mục lục đang dùng (chưa bị import sau bỏ) của từng hộp."""
        rows = self.session.query(ArrangementDossier.case_id, func.count(ArrangementDossier.id)).filter(
            ArrangementDossier.project_id == project_id,
            ArrangementDossier.missing_from_import_id.is_(None),
        ).group_by(ArrangementDossier.case_id).all()
        return {case_id: count for case_id, count in rows}

    def latest_done_scan_a4_by_case(self, project_id: int) -> dict[int, int]:
        """Trang A4 quy đổi của gói S `done` mới nhất (phiên bản lớn nhất) từng hộp."""
        latest = self.session.query(
            CaseScanPackage.case_id, func.max(CaseScanPackage.version).label("version"),
        ).join(ProjectCase, ProjectCase.id == CaseScanPackage.case_id).filter(
            ProjectCase.project_id == project_id,
            CaseScanPackage.status == "done",
        ).group_by(CaseScanPackage.case_id).subquery()
        rows = self.session.query(CaseScanPackage.case_id, CaseScanPackage.total_a4_equivalent).join(
            latest,
            (latest.c.case_id == CaseScanPackage.case_id) & (latest.c.version == CaseScanPackage.version),
        ).all()
        return {case_id: a4 or 0 for case_id, a4 in rows}

    def done_scan_packages_finished_since(self, project_id: int, since_utc) -> list[tuple]:
        """(scanned_by_user_id, total_a4_equivalent, finished_at) của mọi gói S `done` xong từ since_utc."""
        return self.session.query(
            CaseScanPackage.scanned_by_user_id,
            CaseScanPackage.total_a4_equivalent,
            CaseScanPackage.finished_at,
        ).join(ProjectCase, ProjectCase.id == CaseScanPackage.case_id).filter(
            ProjectCase.project_id == project_id,
            CaseScanPackage.status == "done",
            CaseScanPackage.finished_at.isnot(None),
            CaseScanPackage.finished_at >= since_utc,
        ).all()

    def active_assets(self, project_id: int) -> list[tuple]:
        """(assigned_document_id, original_filename) của file nhập liệu đang dùng."""
        return self.session.query(
            ProjectDocumentAsset.assigned_document_id, ProjectDocumentAsset.original_filename,
        ).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
        ).all()

    def latest_submissions_by_document(self, document_ids) -> dict[int, Submission]:
        """Lần lưu mới nhất (id lớn nhất) của từng văn bản."""
        result = {}
        for chunk in _chunks(document_ids):
            latest_ids = self.session.query(func.max(Submission.id)).filter(
                Submission.assigned_document_id.in_(chunk),
            ).group_by(Submission.assigned_document_id)
            for submission in self.session.query(Submission).filter(Submission.id.in_(latest_ids)).all():
                result[submission.assigned_document_id] = submission
        return result
