from sqlalchemy import func

from server.models import ArrangementDossier, Project, ProjectCase, ProjectDocumentAsset, Submission
from server.models_payroll import PayrollLine, PayrollPeriod, ProjectWorkRate
from server.models_scan import CaseScanPackage
from server.repositories.base import BaseRepository
from server.repositories.timesheet_repository import _chunks


class PayrollRepository(BaseRepository[Project]):
    """Chi trả theo sản lượng (P1). Không commit/rollback."""

    model = Project

    def rates(self, project_id: int) -> dict[str, ProjectWorkRate]:
        rows = self.session.query(ProjectWorkRate).filter(ProjectWorkRate.project_id == project_id).all()
        return {row.work_code: row for row in rows}

    def add_rate(self, rate: ProjectWorkRate) -> None:
        self.session.add(rate)

    def delete_rate(self, rate: ProjectWorkRate) -> None:
        self.session.delete(rate)

    def active_dossiers(self, project_id: int) -> list[ArrangementDossier]:
        return self.session.query(ArrangementDossier).filter(
            ArrangementDossier.project_id == project_id,
            ArrangementDossier.missing_from_import_id.is_(None),
        ).all()

    def active_assets(self, project_id: int) -> list[ProjectDocumentAsset]:
        return self.session.query(ProjectDocumentAsset).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
            ProjectDocumentAsset.assigned_document_id.isnot(None),
        ).all()

    def latest_submissions_by_document(self, document_ids) -> dict[int, Submission]:
        result = {}
        for chunk in _chunks(document_ids):
            latest_ids = self.session.query(func.max(Submission.id)).filter(
                Submission.assigned_document_id.in_(chunk),
            ).group_by(Submission.assigned_document_id)
            for submission in self.session.query(Submission).filter(Submission.id.in_(latest_ids)).all():
                result[submission.assigned_document_id] = submission
        return result

    def done_scan_packages_between(self, project_id: int, start_utc, end_utc) -> list[CaseScanPackage]:
        """Gói S `done` có finished_at trong [start_utc, end_utc)."""
        return self.session.query(CaseScanPackage).join(ProjectCase, ProjectCase.id == CaseScanPackage.case_id).filter(
            ProjectCase.project_id == project_id,
            CaseScanPackage.status == "done",
            CaseScanPackage.finished_at >= start_utc,
            CaseScanPackage.finished_at < end_utc,
        ).all()

    def periods(self, project_id: int) -> list[PayrollPeriod]:
        return self.session.query(PayrollPeriod).filter(PayrollPeriod.project_id == project_id).order_by(
            PayrollPeriod.date_from, PayrollPeriod.id,
        ).all()

    def overlapping_periods(self, project_id: int, date_from, date_to) -> list[PayrollPeriod]:
        return self.session.query(PayrollPeriod).filter(
            PayrollPeriod.project_id == project_id,
            PayrollPeriod.date_from <= date_to,
            PayrollPeriod.date_to >= date_from,
        ).all()

    def period(self, project_id: int, period_id: int) -> PayrollPeriod | None:
        return self.session.query(PayrollPeriod).filter(
            PayrollPeriod.project_id == project_id, PayrollPeriod.id == period_id,
        ).first()

    def period_lines(self, period_id: int) -> list[PayrollLine]:
        return self.session.query(PayrollLine).filter(PayrollLine.period_id == period_id).order_by(PayrollLine.id).all()

    def line_counts(self, period_ids) -> dict[int, int]:
        if not period_ids:
            return {}
        rows = self.session.query(PayrollLine.period_id, func.count(PayrollLine.id)).filter(
            PayrollLine.period_id.in_(list(period_ids)),
        ).group_by(PayrollLine.period_id).all()
        return {period_id: count for period_id, count in rows}

    def delete_period(self, period: PayrollPeriod) -> None:
        # Xóa dòng trước: SQLite mặc định không bật khóa ngoại nên ON DELETE CASCADE không chạy.
        self.session.query(PayrollLine).filter(PayrollLine.period_id == period.id).delete(synchronize_session=False)
        self.session.delete(period)
