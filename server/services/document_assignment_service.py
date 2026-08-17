import json
from fastapi import HTTPException
from sqlalchemy.orm import Session

from server.database import get_utc_now
from server.models import Submission, AssignedDocumentReviewAssignment
from server.repositories import (
    DocumentRepository,
    ReviewRepository,
    SubmissionRepository,
    UserRepository,
)
from server.services.submission_metadata_service import backfill_submission_metadata
from server.utils.folder_utils import NO_FOLDER_SENTINEL, normalize_folder_path


def _find_submission_document(db: Session, submission: Submission):
    try:
        data = json.loads(submission.data_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    uuid_filename = data.get("_pdf_uuid")
    original_filename = data.get("_pdf_filename")
    if not uuid_filename and not original_filename:
        return None

    return DocumentRepository(db).resolve_reference(
        owner_id=submission.created_by_user_id,
        uuid_filename=uuid_filename,
        original_filename=original_filename,
    )


def get_user_pending_assignment_folders(db: Session, user_id: int) -> list[dict]:
    document_repository = DocumentRepository(db)
    documents = document_repository.list_pending_for_user(user_id)
    candidate_ids = {document.id for document in documents}
    metadata = document_repository.metadata_map(candidate_ids)
    group_document_ids: dict[str, list[int]] = {}
    document_group_paths = {}
    for document in documents:
        folder_path = normalize_folder_path(
            metadata.get(document.id, {}).get("folder_path")
        ) or NO_FOLDER_SENTINEL
        group_document_ids.setdefault(folder_path, []).append(document.id)
        document_group_paths[document.id] = folder_path

    real_folder_paths = {
        folder_path
        for folder_path in group_document_ids
        if folder_path != NO_FOLDER_SENTINEL
    }
    submission_rows = SubmissionRepository(
        db
    ).list_assignment_submission_references(
        candidate_ids,
        real_folder_paths,
    )
    submission_counts = {folder_path: 0 for folder_path in group_document_ids}
    for assigned_document_id, submission_folder_path in submission_rows:
        folder_path = document_group_paths.get(assigned_document_id)
        if not folder_path:
            normalized = normalize_folder_path(submission_folder_path)
            folder_path = normalized if normalized in real_folder_paths else None
        if folder_path:
            submission_counts[folder_path] += 1

    groups = []
    for folder_path, document_ids in group_document_ids.items():
        if folder_path == NO_FOLDER_SENTINEL:
            folder_name = "Tài liệu chưa có folder"
        elif folder_path == "__ROOT__":
            folder_name = "Thư mục gốc"
        else:
            folder_name = folder_path.rstrip("/").rsplit("/", 1)[-1]
        groups.append({
            "folder_path": folder_path,
            "folder_name": folder_name,
            "document_ids": document_ids,
            "document_count": len(document_ids),
            "submission_count": submission_counts[folder_path],
        })
    return sorted(groups, key=lambda item: item["folder_path"].casefold())


def execute_revoke_user_assignments(db: Session, target_user_id: int, assignment_type: str, folder_path: str, current_user_id: int) -> dict:
    result = {
        "input_revoked": 0,
        "input_folders_revoked": 0,
        "input_folders_blocked": 0,
        "drafts_blocked": 0,
        "review_reservations_revoked": 0,
        "reviews_transferred_to_admin": 0,
        "reviews_blocked": 0,
    }
    
    document_repository = DocumentRepository(db)
    review_repository = ReviewRepository(db)
    if assignment_type == "input":
        target_folder_path = normalize_folder_path(folder_path)
        if not target_folder_path:
            raise HTTPException(
                status_code=400,
                detail="Vui lòng chọn folder cần thu hồi",
            )
        backfill_submission_metadata(db)
        groups = get_user_pending_assignment_folders(db, target_user_id)
        target_group = next(
            (
                group for group in groups
                if group["folder_path"] == target_folder_path
            ),
            None,
        )
        if not target_group:
            raise HTTPException(
                status_code=404,
                detail="Folder không còn được phân cho nhân viên này",
            )
        if target_group["submission_count"]:
            raise HTTPException(
                status_code=409,
                detail="Folder đã có hồ sơ nên không thể thu hồi",
            )

        revocable_ids = target_group["document_ids"]
        if revocable_ids:
            result["review_reservations_revoked"] = (
                review_repository.delete_document_assignments(revocable_ids)
            )
            result["input_revoked"] = document_repository.unassign_documents(
                revocable_ids
            )
        result["input_folders_revoked"] = 1
    else:
        pending_mappings = review_repository.pending_document_assignments(
            target_user_id
        )
        result["review_reservations_revoked"] = len(pending_mappings)
        for mapping in pending_mappings:
            review_repository.delete(mapping)

        active_reviews = review_repository.active_submission_assignments(
            target_user_id
        )
        for assignment, submission in active_reviews:
            if submission.created_by_user_id == current_user_id:
                result["reviews_blocked"] += 1
                continue
            assignment.reviewer_user_id = current_user_id
            assignment.assigned_at = get_utc_now()
            document = _find_submission_document(db, submission)
            if document:
                document_mapping = review_repository.get_document_assignment(
                    document.id
                )
                if document_mapping:
                    document_mapping.reviewer_user_id = current_user_id
                    document_mapping.assigned_at = get_utc_now()
                else:
                    document_repository.add_review_assignment(
                        AssignedDocumentReviewAssignment(
                            document_id=document.id,
                            reviewer_user_id=current_user_id,
                        )
                    )
            result["reviews_transferred_to_admin"] += 1

    return result
