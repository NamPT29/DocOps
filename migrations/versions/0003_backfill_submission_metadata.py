"""Backfill indexed submission metadata once.

Revision ID: 0003_submission_metadata
Revises: 0002_review_confirmation_fk

This migration deliberately freezes the legacy matching and normalization
rules.  It must not import application services whose behavior can change
after this revision ships.
"""

from __future__ import annotations

import hashlib
import json
import os

from alembic import op
from sqlalchemy import text


revision = "0003_submission_metadata"
down_revision = "0002_review_confirmation_fk"
branch_labels = None
depends_on = None

_NO_FOLDER_SENTINEL = "__NO_FOLDER__"
_BATCH_SIZE = 500


def _normalize_folder_path(folder_path: object) -> str:
    return str(folder_path or "").replace("\\", "/").strip("/")


def _folder_path_key(folder_path: object) -> str:
    normalized = _normalize_folder_path(folder_path) or _NO_FOLDER_SENTINEL
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _document_metadata_maps(bind) -> tuple[dict, dict, dict]:
    rows = bind.execute(text("""
        SELECT
            document.id,
            document.assigned_to_user_id,
            document.uuid_filename,
            document.original_filename,
            folder.folder_group
        FROM assigned_documents AS document
        LEFT JOIN assigned_document_folders AS folder
          ON folder.document_id = document.id
        ORDER BY document.created_at DESC, document.id DESC
    """)).all()

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
        folders[document_id] = _normalize_folder_path(folder_path)
    return by_uuid, by_filename, folders


def _backfill(bind, *, batch_size: int = _BATCH_SIZE) -> int:
    by_uuid, by_filename, document_folders = _document_metadata_maps(bind)
    updated = 0
    last_id = 0

    while True:
        rows = bind.execute(text("""
            SELECT id, data_json, created_by_user_id
            FROM submissions
            WHERE id > :last_id AND folder_path_key IS NULL
            ORDER BY id
            LIMIT :batch_size
        """), {"last_id": last_id, "batch_size": batch_size}).all()
        if not rows:
            break

        for submission_id, data_json, owner_id in rows:
            last_id = submission_id
            try:
                data = json.loads(data_json)
                if not isinstance(data, dict):
                    data = {}
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}

            uuid_filename = os.path.basename(str(data.get("_pdf_uuid") or ""))
            original_filename = data.get("_pdf_filename")
            document_id = None
            if uuid_filename:
                document_id = by_uuid.get((owner_id, uuid_filename))
            if document_id is None and original_filename:
                document_id = by_filename.get((owner_id, original_filename))

            folder_path = document_folders.get(document_id)
            if not folder_path:
                folder_path = _normalize_folder_path(data.get("_folder_path"))

            bind.execute(text("""
                UPDATE submissions
                SET assigned_document_id = :document_id,
                    folder_path = :folder_path,
                    folder_path_key = :folder_path_key
                WHERE id = :submission_id AND folder_path_key IS NULL
            """), {
                "document_id": document_id,
                "folder_path": folder_path or None,
                "folder_path_key": _folder_path_key(folder_path),
                "submission_id": submission_id,
            })
            updated += 1

    return updated


def upgrade() -> None:
    _backfill(op.get_bind())


def downgrade() -> None:
    # The original values cannot be distinguished from metadata written by
    # normal create/update paths, so reverting this data migration is unsafe.
    pass
