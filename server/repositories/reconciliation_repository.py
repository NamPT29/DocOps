from sqlalchemy import func

from server.models import ArrangementDossier, Project, ProjectCase, ProjectDocumentAsset, Submission
from server.models_scan import CaseScanFile, CaseScanPackage
from server.repositories.base import BaseRepository
from server.repositories.timesheet_repository import _chunks


class ReconciliationRepository(BaseRepository[Project]):
    """Đọc dữ liệu cho đối soát R1–R4 (lát R1). Chỉ đọc, không ghi."""

    model = Project

    def cases(self, project_id: int) -> list[ProjectCase]:
        return self.session.query(ProjectCase).filter(ProjectCase.project_id == project_id).all()

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

    def latest_done_packages(self, project_id: int) -> dict[int, CaseScanPackage]:
        """Gói S `done` mới nhất (phiên bản lớn nhất trong các gói done) của từng hộp."""
        latest = self.session.query(
            CaseScanPackage.case_id, func.max(CaseScanPackage.version).label("version"),
        ).join(ProjectCase, ProjectCase.id == CaseScanPackage.case_id).filter(
            ProjectCase.project_id == project_id,
            CaseScanPackage.status == "done",
        ).group_by(CaseScanPackage.case_id).subquery()
        packages = self.session.query(CaseScanPackage).join(
            latest,
            (latest.c.case_id == CaseScanPackage.case_id) & (latest.c.version == CaseScanPackage.version),
        ).all()
        return {package.case_id: package for package in packages}

    def scan_files(self, package_ids) -> list[CaseScanFile]:
        files = []
        for chunk in _chunks(package_ids):
            files.extend(self.session.query(CaseScanFile).filter(CaseScanFile.package_id.in_(chunk)).all())
        return files

    def submissions_by_document(self, document_ids) -> dict[int, list[tuple[int, str]]]:
        """{document_id: [(submission_id, status), ...]} theo thứ tự id."""
        result: dict[int, list[tuple[int, str]]] = {}
        for chunk in _chunks(document_ids):
            rows = self.session.query(Submission.assigned_document_id, Submission.id, Submission.status).filter(
                Submission.assigned_document_id.in_(chunk),
            ).order_by(Submission.id).all()
            for document_id, submission_id, status in rows:
                result.setdefault(document_id, []).append((submission_id, status))
        return result
