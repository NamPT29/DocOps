from sqlalchemy import case as sql_case
from sqlalchemy import func

from server.models import (
    ArrangementDossier,
    ArrangementImport,
    CaseStageState,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    User,
)
from server.repositories.base import BaseRepository


class ArrangementRepository(BaseRepository[ArrangementDossier]):
    model = ArrangementDossier

    def lock_project(self, project_id: int) -> Project | None:
        return self.session.query(Project).filter(
            Project.id == project_id
        ).with_for_update().first()

    def get_project(self, project_id: int) -> Project | None:
        return self.session.query(Project).filter(Project.id == project_id).first()

    def cases(self, project_id: int) -> list[ProjectCase]:
        return self.session.query(ProjectCase).filter(
            ProjectCase.project_id == project_id
        ).all()

    def active_asset_paths(self, project_id: int) -> list[str]:
        return [
            row[0]
            for row in self.session.query(ProjectDocumentAsset.relative_path).filter(
                ProjectDocumentAsset.project_id == project_id,
                ProjectDocumentAsset.status == "active",
            ).all()
        ]

    def started_scan_case_ids(self, project_id: int) -> set[int]:
        """Boxes whose scan began: they hold PDFs or left "pending" in Scan."""
        with_pdfs = self.session.query(ProjectDocumentAsset.case_id).filter(
            ProjectDocumentAsset.project_id == project_id,
            ProjectDocumentAsset.status == "active",
        )
        scan_moved = self.session.query(CaseStageState.case_id).filter(
            CaseStageState.project_id == project_id,
            CaseStageState.stage_key == "scan",
            CaseStageState.status != "pending",
        )
        return {row[0] for row in with_pdfs.union(scan_moved).all()}

    def has_catalog(self, project_id: int) -> bool:
        return self.session.query(ArrangementDossier.id).filter(
            ArrangementDossier.project_id == project_id
        ).first() is not None

    def find_case_by_key(self, project_id: int, case_key: str) -> ProjectCase | None:
        return self.session.query(ProjectCase).filter(
            ProjectCase.project_id == project_id,
            ProjectCase.case_key == case_key,
        ).first()

    def dossiers_for_boxes(self, project_id: int, box_numbers) -> list[ArrangementDossier]:
        numbers = sorted(set(box_numbers))
        if not numbers:
            return []
        return self.session.query(ArrangementDossier).filter(
            ArrangementDossier.project_id == project_id,
            ArrangementDossier.box_number.in_(numbers),
        ).all()

    def add_import(self, entry: ArrangementImport) -> ArrangementImport:
        self.session.add(entry)
        self.session.flush()
        return entry

    def add_case(self, case_row: ProjectCase) -> ProjectCase:
        self.session.add(case_row)
        self.session.flush()
        return case_row

    def box_summaries(self, project_id: int) -> list[tuple]:
        """(box, case id, dossiers, bad-paper dossiers, kept-but-missing dossiers)."""
        return self.session.query(
            ArrangementDossier.box_number,
            ArrangementDossier.case_id,
            func.count(ArrangementDossier.id),
            func.sum(sql_case((ArrangementDossier.bad_paper.is_(True), 1), else_=0)),
            func.sum(sql_case((ArrangementDossier.missing_from_import_id.is_not(None), 1), else_=0)),
        ).filter(
            ArrangementDossier.project_id == project_id
        ).group_by(
            ArrangementDossier.box_number, ArrangementDossier.case_id
        ).order_by(ArrangementDossier.box_number).all()

    def box_dossiers(self, project_id: int, box_number: int) -> list[ArrangementDossier]:
        return self.session.query(ArrangementDossier).filter(
            ArrangementDossier.project_id == project_id,
            ArrangementDossier.box_number == box_number,
        ).order_by(
            ArrangementDossier.dossier_number, ArrangementDossier.dossier_suffix
        ).all()

    def recent_imports(self, project_id: int, limit: int = 10) -> list[tuple]:
        return self.session.query(ArrangementImport, User.username).outerjoin(
            User, User.id == ArrangementImport.imported_by_user_id
        ).filter(
            ArrangementImport.project_id == project_id
        ).order_by(
            ArrangementImport.created_at.desc(), ArrangementImport.id.desc()
        ).limit(limit).all()

    def dossier_count_for_case(self, case_id: int) -> int:
        return self.session.query(func.count(ArrangementDossier.id)).filter(
            ArrangementDossier.case_id == case_id
        ).scalar() or 0
