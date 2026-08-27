import os

from sqlalchemy import case, exists, func, or_
from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
    Submission,
    Template,
)
from server.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[AssignedDocument]):
    model = AssignedDocument

    def resolve_reference(
        self,
        *,
        owner_id: int | None,
        uuid_filename: object = None,
        original_filename: object = None,
        pending_only: bool = False,
    ) -> AssignedDocument | None:
        if not uuid_filename and not original_filename:
            return None
        query = self.session.query(AssignedDocument)
        if owner_id is not None:
            query = query.filter(AssignedDocument.assigned_to_user_id == owner_id)
        if uuid_filename:
            query = query.filter(
                AssignedDocument.uuid_filename == os.path.basename(str(uuid_filename))
            )
        else:
            query = query.filter(AssignedDocument.original_filename == original_filename)
        if pending_only:
            query = query.filter(AssignedDocument.status == "pending")
            return query.order_by(
                AssignedDocument.created_at.asc(),
                AssignedDocument.id.asc(),
            ).first()
        return query.order_by(
            AssignedDocument.created_at.desc(),
            AssignedDocument.id.desc(),
        ).first()

    def get_by_uuid(self, uuid_filename: str) -> AssignedDocument | None:
        return self.session.query(AssignedDocument).filter(
            AssignedDocument.uuid_filename == uuid_filename
        ).first()

    def map_by_ids(self, document_ids: set[int]) -> dict[int, AssignedDocument]:
        if not document_ids:
            return {}
        return {
            document.id: document
            for document in self.session.query(AssignedDocument).filter(
                AssignedDocument.id.in_(document_ids),
            ).all()
        }

    def reference_maps(
        self,
        *,
        owner_id: int | None,
        uuid_filenames: set[str],
        original_filenames: set[str],
    ) -> tuple[dict[str, AssignedDocument], dict[str, AssignedDocument]]:
        """Resolve many PDF references while preserving newest-file semantics."""
        if not uuid_filenames and not original_filenames:
            return {}, {}
        filters = []
        if uuid_filenames:
            filters.append(AssignedDocument.uuid_filename.in_(uuid_filenames))
        if original_filenames:
            filters.append(AssignedDocument.original_filename.in_(original_filenames))
        query = self.session.query(AssignedDocument)
        if owner_id is not None:
            query = query.filter(AssignedDocument.assigned_to_user_id == owner_id)
        rows = query.filter(or_(*filters)).order_by(
            AssignedDocument.created_at.desc(),
            AssignedDocument.id.desc(),
        ).all()
        by_uuid: dict[str, AssignedDocument] = {}
        by_original: dict[str, AssignedDocument] = {}
        for document in rows:
            by_uuid.setdefault(document.uuid_filename, document)
            by_original.setdefault(document.original_filename, document)
        return by_uuid, by_original

    def get_path_and_folder(self, document_id: int) -> tuple[str | None, str | None]:
        path = self.session.query(AssignedDocumentPath).filter(
            AssignedDocumentPath.document_id == document_id
        ).first()
        folder = self.get_folder(document_id)
        return (
            getattr(path, "relative_path", None),
            getattr(folder, "folder_group", None),
        )

    def get_folder(self, document_id: int) -> AssignedDocumentFolder | None:
        return self.session.query(AssignedDocumentFolder).filter(
            AssignedDocumentFolder.document_id == document_id
        ).first()

    def metadata_map(self, document_ids: set[int]) -> dict[int, dict]:
        if not document_ids:
            return {}
        rows = self.session.query(
            AssignedDocument,
            AssignedDocumentPath.relative_path,
            AssignedDocumentFolder.folder_group,
        ).outerjoin(
            AssignedDocumentPath,
            AssignedDocumentPath.document_id == AssignedDocument.id,
        ).outerjoin(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).filter(
            AssignedDocument.id.in_(document_ids)
        ).all()
        return {
            document.id: {
                "document": document,
                "relative_path": relative_path,
                "folder_path": folder_path,
            }
            for document, relative_path, folder_path in rows
        }

    def list_folder_files(self, folder_path: str) -> list[tuple]:
        return self.session.query(
            AssignedDocument,
            AssignedDocumentPath.relative_path,
            Submission.id.label("submission_id"),
            Submission.status.label("submission_status"),
        ).join(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).outerjoin(
            AssignedDocumentPath,
            AssignedDocumentPath.document_id == AssignedDocument.id,
        ).outerjoin(
            Submission,
            Submission.assigned_document_id == AssignedDocument.id
        ).filter(
            AssignedDocumentFolder.folder_group == folder_path,
        ).order_by(
            AssignedDocumentPath.relative_path,
            AssignedDocument.created_at,
            AssignedDocument.id,
        ).all()

    def metadata_backfill_rows(self) -> list[tuple]:
        return self.session.query(
            AssignedDocument.id,
            AssignedDocument.assigned_to_user_id,
            AssignedDocument.uuid_filename,
            AssignedDocument.original_filename,
            AssignedDocumentFolder.folder_group,
        ).outerjoin(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).order_by(
            AssignedDocument.created_at.desc(),
            AssignedDocument.id.desc(),
        ).all()

    def _legacy_pdf_sets(self) -> tuple[set[str], set[str]]:
        """Parse legacy submissions (no assigned_document_id) and return
        sets of (_pdf_uuid values, _pdf_filename values) for O(1) lookup."""
        import json as _json
        legacy_subs = self.session.query(Submission.data_json).filter(
            Submission.assigned_document_id.is_(None)
        ).all()
        legacy_uuids: set[str] = set()
        legacy_filenames: set[str] = set()
        for (data_json,) in legacy_subs:
            try:
                data = _json.loads(data_json)
            except (TypeError, ValueError):
                continue
            pdf_uuid = data.get("_pdf_uuid")
            pdf_filename = data.get("_pdf_filename")
            if pdf_uuid:
                legacy_uuids.add(str(pdf_uuid))
            if pdf_filename:
                legacy_filenames.add(str(pdf_filename))
        return legacy_uuids, legacy_filenames

    def list_input_queue(self, user_id: int) -> list[tuple]:
        all_docs = self.session.query(
            AssignedDocument,
            Template.name,
            AssignedDocumentPath.relative_path,
            AssignedDocumentFolder.folder_group,
        ).outerjoin(
            Template,
            AssignedDocument.template_id == Template.id,
        ).outerjoin(
            AssignedDocumentPath,
            AssignedDocumentPath.document_id == AssignedDocument.id,
        ).outerjoin(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).filter(
            AssignedDocument.assigned_to_user_id == user_id,
            AssignedDocument.status.in_(["pending", "completed"]),
        ).order_by(
            AssignedDocument.template_id,
            AssignedDocumentPath.relative_path,
            AssignedDocument.created_at,
        ).all()

        return all_docs

    def linked_pdf_uuids(self, user_id: int) -> set[str]:
        all_docs = self.session.query(
            AssignedDocument.id,
            AssignedDocument.uuid_filename,
            AssignedDocument.original_filename
        ).filter(
            AssignedDocument.assigned_to_user_id == user_id
        ).all()

        if not all_docs:
            return set()

        doc_ids = [d.id for d in all_docs]
        
        subs_by_id = self.session.query(Submission.assigned_document_id).filter(
            Submission.assigned_document_id.in_(doc_ids)
        ).all()
        submitted_doc_ids = {s.assigned_document_id for s in subs_by_id}

        legacy_uuids, legacy_filenames = self._legacy_pdf_sets()

        result = set()
        for doc_id, uuid_filename, original_filename in all_docs:
            if doc_id in submitted_doc_ids:
                result.add(uuid_filename)
            elif uuid_filename and uuid_filename in legacy_uuids:
                result.add(uuid_filename)
            elif original_filename and original_filename in legacy_filenames:
                result.add(uuid_filename)
                
        return result

    def is_direct_reviewer(self, document_id: int, user_id: int) -> bool:
        return self.session.query(AssignedDocumentReviewAssignment.document_id).filter(
            AssignedDocumentReviewAssignment.document_id == document_id,
            AssignedDocumentReviewAssignment.reviewer_user_id == user_id,
        ).first() is not None

    def is_folder_reviewer(self, folder_path: str, user_id: int) -> bool:
        return self.session.query(AssignedDocumentReviewAssignment.document_id).join(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id
            == AssignedDocumentReviewAssignment.document_id,
        ).filter(
            AssignedDocumentFolder.folder_group == folder_path,
            AssignedDocumentReviewAssignment.reviewer_user_id == user_id,
        ).first() is not None

    def list_pending_for_user(self, user_id: int) -> list[AssignedDocument]:
        return self.session.query(AssignedDocument).filter(
            AssignedDocument.assigned_to_user_id == user_id,
            AssignedDocument.status == "pending",
        ).all()

    def unassign_documents(self, document_ids: list[int]) -> int:
        if not document_ids:
            return 0
        return self.session.query(AssignedDocument).filter(
            AssignedDocument.id.in_(document_ids)
        ).update(
            {AssignedDocument.assigned_to_user_id: None},
            synchronize_session=False,
        )

    def active_reviewer_folder_rows(self) -> list[tuple]:
        return self.session.query(
            AssignedDocument,
            AssignedDocumentFolder.folder_group,
            AssignedDocumentReviewAssignment,
        ).join(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).outerjoin(
            AssignedDocumentReviewAssignment,
            AssignedDocumentReviewAssignment.document_id == AssignedDocument.id,
        ).filter(
            AssignedDocument.assigned_to_user_id.is_not(None),
        ).order_by(
            AssignedDocumentFolder.folder_group,
            AssignedDocument.id,
        ).all()

    def add_review_assignment(
        self,
        assignment: AssignedDocumentReviewAssignment,
    ) -> AssignedDocumentReviewAssignment:
        self.session.add(assignment)
        return assignment

    def find_import_by_upload_id(self, upload_id: str) -> tuple | None:
        return self.session.query(
            AssignedDocumentPath,
            AssignedDocument,
            AssignedDocumentFolder,
        ).join(
            AssignedDocument,
            AssignedDocument.id == AssignedDocumentPath.document_id,
        ).outerjoin(
            AssignedDocumentFolder,
            AssignedDocumentFolder.document_id == AssignedDocument.id,
        ).filter(
            AssignedDocumentPath.upload_id == upload_id
        ).first()

    def add_path(self, path: AssignedDocumentPath) -> AssignedDocumentPath:
        self.session.add(path)
        return path

    def add_folder(self, folder: AssignedDocumentFolder) -> AssignedDocumentFolder:
        self.session.add(folder)
        return folder

    def user_document_counts(self) -> dict[int, dict[str, int]]:
        rows = self.session.query(
            AssignedDocument.assigned_to_user_id,
            func.sum(case((AssignedDocument.status == "pending", 1), else_=0)),
            func.sum(case((AssignedDocument.status == "completed", 1), else_=0)),
        ).filter(
            AssignedDocument.assigned_to_user_id.isnot(None)
        ).group_by(AssignedDocument.assigned_to_user_id).all()
        return {
            user_id: {
                "pending": int(pending or 0),
                "completed": int(completed or 0),
            }
            for user_id, pending, completed in rows
        }

    def reviewer_reservation_counts(self) -> dict[int, int]:
        rows = self.session.query(
            AssignedDocumentReviewAssignment.reviewer_user_id,
            func.count(AssignedDocumentReviewAssignment.document_id),
        ).join(
            AssignedDocument,
            AssignedDocument.id == AssignedDocumentReviewAssignment.document_id,
        ).filter(
            AssignedDocument.status == "pending",
        ).group_by(
            AssignedDocumentReviewAssignment.reviewer_user_id
        ).all()
        return {reviewer_id: count for reviewer_id, count in rows}

    def get_inventory_folders(self) -> list[dict]:
        from server.models import AssignedDocumentFolder, AssignedDocumentPath
        from sqlalchemy import func
        rows = self.session.query(
            AssignedDocumentFolder.folder_group,
            func.count(AssignedDocumentFolder.document_id).label("document_count")
        ).group_by(AssignedDocumentFolder.folder_group).all()
        
        folders = []
        for folder_group, count in rows:
            path = folder_group or "__NO_FOLDER__"
            name = path.split("/")[-1] if path and path != "__ROOT__" and path != "__NO_FOLDER__" else path
            folders.append({
                "folder_path": path,
                "folder_name": name,
                "document_count": count
            })
        return folders

    def get_inventory_documents(self, folder_path: str = None, page: int = 1, page_size: int = 20) -> tuple[list, int]:
        from server.models import User, Submission
        query = self.session.query(
            AssignedDocument,
            AssignedDocumentPath.relative_path,
            AssignedDocumentFolder.folder_group,
            User.username.label("assigned_username"),
            Submission.status.label("submission_status")
        ).outerjoin(
            AssignedDocumentPath, AssignedDocumentPath.document_id == AssignedDocument.id
        ).outerjoin(
            AssignedDocumentFolder, AssignedDocumentFolder.document_id == AssignedDocument.id
        ).outerjoin(
            User, User.id == AssignedDocument.assigned_to_user_id
        ).outerjoin(
            Submission, Submission.assigned_document_id == AssignedDocument.id
        )

        if folder_path and folder_path != "__NO_FOLDER__":
            query = query.filter(AssignedDocumentFolder.folder_group == folder_path)
        elif folder_path == "__NO_FOLDER__":
            query = query.filter(AssignedDocumentFolder.folder_group == None)

        total = query.count()
        rows = query.order_by(AssignedDocument.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return rows, total
