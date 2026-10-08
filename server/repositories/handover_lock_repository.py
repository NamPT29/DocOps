from server.models import Project, ProjectDocumentAsset
from server.repositories.base import BaseRepository
from server.repositories.timesheet_repository import _chunks


class HandoverLockRepository(BaseRepository[Project]):
    """Khóa sửa hồ sơ sau bàn giao (K1). Không commit/rollback."""

    model = Project

    def locked_document_ids(self, document_ids) -> set[int]:
        """Văn bản (assigned_document_id) thuộc file nhập liệu của dự án đã khóa bàn giao."""
        locked = set()
        for chunk in _chunks(document_id for document_id in document_ids if document_id is not None):
            rows = self.session.query(ProjectDocumentAsset.assigned_document_id).join(
                Project, Project.id == ProjectDocumentAsset.project_id,
            ).filter(
                ProjectDocumentAsset.assigned_document_id.in_(chunk),
                Project.handover_locked_at.isnot(None),
            ).all()
            locked.update(document_id for (document_id,) in rows)
        return locked
