import hashlib
import json
import os

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from server.models import AssignedDocument, Submission


NO_FOLDER_SENTINEL = "__NO_FOLDER__"
_SUBMISSION_COLUMNS = {
    "assigned_document_id": "INTEGER NULL",
    "folder_path": "VARCHAR(1024) NULL",
    "folder_path_key": "VARCHAR(64) NULL",
}
_SUBMISSION_INDEXES = {
    "ix_submissions_assigned_document_id": "assigned_document_id",
    "ix_submissions_folder_path_key": "folder_path_key",
}


def normalize_folder_path(folder_path: object) -> str:
    return str(folder_path or "").replace("\\", "/").strip("/")


def folder_path_key(folder_path: object) -> str:
    normalized = normalize_folder_path(folder_path) or NO_FOLDER_SENTINEL
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def apply_submission_metadata(
    submission: Submission,
    data: dict,
    *,
    document: AssignedDocument | None = None,
    folder_path: object = None,
) -> None:
    normalized_folder = normalize_folder_path(
        folder_path if folder_path is not None else data.get("_folder_path")
    )
    submission.assigned_document_id = getattr(document, "id", None)
    submission.folder_path = normalized_folder or None
    submission.folder_path_key = folder_path_key(normalized_folder)


def ensure_submission_metadata_schema(engine) -> None:
    """Add metadata columns/indexes without replacing or rewriting the table."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "submissions" not in table_names:
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("submissions")
    }
    with engine.begin() as connection:
        for column_name, column_ddl in _SUBMISSION_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(text(
                    f"ALTER TABLE submissions ADD COLUMN {column_name} {column_ddl}"
                ))

    inspector = inspect(engine)
    existing_indexes = {
        index["name"] for index in inspector.get_indexes("submissions")
    }
    with engine.begin() as connection:
        for index_name, column_name in _SUBMISSION_INDEXES.items():
            if index_name not in existing_indexes:
                connection.execute(text(
                    f"CREATE INDEX {index_name} ON submissions ({column_name})"
                ))


def _document_metadata_maps(db: Session) -> tuple[dict, dict, dict]:
    from server.repositories.document_repository import DocumentRepository

    rows = DocumentRepository(db).metadata_backfill_rows()

    by_uuid = {}
    by_filename = {}
    folders = {}
    for document_id, owner_id, uuid_filename, original_filename, folder_path in rows:
        if uuid_filename:
            by_uuid.setdefault(
                (owner_id, os.path.basename(str(uuid_filename))),
                document_id,
            )
        if original_filename:
            by_filename.setdefault((owner_id, original_filename), document_id)
        folders[document_id] = normalize_folder_path(folder_path)
    return by_uuid, by_filename, folders


def backfill_submission_metadata(db: Session, *, batch_size: int = 500) -> dict:
    """Backfill only missing metadata; never mutates the stored form JSON."""
    from server.repositories.submission_repository import SubmissionRepository

    repository = SubmissionRepository(db)
    if not repository.has_missing_metadata():
        return {"updated": 0, "unresolved_documents": 0, "invalid_json": 0}

    by_uuid, by_filename, document_folders = _document_metadata_maps(db)
    stats = {"updated": 0, "unresolved_documents": 0, "invalid_json": 0}
    last_id = 0
    while True:
        batch = repository.missing_metadata_batch(last_id, batch_size)
        if not batch:
            break

        for submission in batch:
            last_id = submission.id
            try:
                data = json.loads(submission.data_json)
                if not isinstance(data, dict):
                    data = {}
                    stats["invalid_json"] += 1
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
                stats["invalid_json"] += 1

            owner_id = submission.created_by_user_id
            uuid_filename = os.path.basename(str(data.get("_pdf_uuid") or ""))
            original_filename = data.get("_pdf_filename")
            document_id = None
            if uuid_filename:
                document_id = by_uuid.get((owner_id, uuid_filename))
            if document_id is None and original_filename:
                document_id = by_filename.get((owner_id, original_filename))

            folder_path = document_folders.get(document_id)
            if not folder_path:
                folder_path = normalize_folder_path(data.get("_folder_path"))
            submission.assigned_document_id = document_id
            submission.folder_path = folder_path or None
            submission.folder_path_key = folder_path_key(folder_path)
            stats["updated"] += 1
            if (uuid_filename or original_filename) and document_id is None:
                stats["unresolved_documents"] += 1

        db.commit()
    return stats
