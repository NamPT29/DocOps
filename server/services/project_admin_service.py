import os
import uuid
from pathlib import Path

from fastapi import HTTPException

from server.repositories.project_admin_repository import ProjectAdminRepository
from server.services.project_service import _validate_project_members
from server.services.project_workspace_service import sync_project_assets_to_documents


def _least_loaded(eligible_user_ids, counts):
    if not eligible_user_ids:
        return None
    return min(eligible_user_ids, key=lambda user_id: (counts[user_id], user_id))


def update_project_members(
    db,
    *,
    project_id,
    input_user_ids,
    reviewer_user_ids,
    changed_by_user_id,
):
    repository = ProjectAdminRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    input_ids, reviewer_ids = _validate_project_members(
        db,
        input_user_ids,
        reviewer_user_ids,
    )
    repository.set_active_members(
        project.id,
        input_user_ids=input_ids,
        reviewer_user_ids=reviewer_ids,
    )
    cases = repository.lock_cases(project.id)
    input_counts, reviewer_counts = repository.assignment_counts(
        cases,
        input_user_ids=input_ids,
        reviewer_user_ids=reviewer_ids,
    )
    result = {
        "input_cases_transferred": 0,
        "reviewer_cases_transferred": 0,
        "submissions_transferred": 0,
        "submission_reviews_transferred": 0,
    }

    try:
        for case_row in cases:
            previous_input_id = case_row.assigned_input_user_id
            if previous_input_id not in input_ids:
                next_input_id = _least_loaded(input_ids, input_counts)
                case_row.assigned_input_user_id = next_input_id
                if next_input_id is not None:
                    input_counts[next_input_id] += 1
                result["submissions_transferred"] += (
                    repository.transfer_case_submission_owner(case_row.id, next_input_id)
                )
                repository.add_assignment_history(
                    project_id=project.id,
                    case_id=case_row.id,
                    assignment_role="input",
                    from_user_id=previous_input_id,
                    to_user_id=next_input_id,
                    changed_by_user_id=changed_by_user_id,
                    reason="member_configuration",
                )
                result["input_cases_transferred"] += 1

            previous_reviewer_id = case_row.assigned_reviewer_user_id
            reviewer_is_invalid = (
                previous_reviewer_id not in reviewer_ids
                or previous_reviewer_id == case_row.assigned_input_user_id
            )
            if reviewer_is_invalid:
                if (
                    previous_reviewer_id in reviewer_ids
                    and reviewer_counts[previous_reviewer_id] > 0
                ):
                    reviewer_counts[previous_reviewer_id] -= 1
                eligible_reviewers = [
                    user_id
                    for user_id in reviewer_ids
                    if user_id != case_row.assigned_input_user_id
                ]
                next_reviewer_id = _least_loaded(eligible_reviewers, reviewer_counts)
                case_row.assigned_reviewer_user_id = next_reviewer_id
                if next_reviewer_id is not None:
                    reviewer_counts[next_reviewer_id] += 1
                result["submission_reviews_transferred"] += (
                    repository.sync_case_submission_reviewer(
                        case_row.id,
                        next_reviewer_id,
                    )
                )
                repository.add_assignment_history(
                    project_id=project.id,
                    case_id=case_row.id,
                    assignment_role="reviewer",
                    from_user_id=previous_reviewer_id,
                    to_user_id=next_reviewer_id,
                    changed_by_user_id=changed_by_user_id,
                    reason="member_configuration",
                )
                result["reviewer_cases_transferred"] += 1

        workspace_counts = sync_project_assets_to_documents(
            db,
            project_id=project.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    result["workspace_counts"] = workspace_counts
    result["input_user_ids"] = input_ids
    result["reviewer_user_ids"] = reviewer_ids
    return result


def list_project_assets(db, *, project_id):
    repository = ProjectAdminRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    rows, submission_counts = repository.list_project_assets(project.id)
    return [
        {
            "id": asset.id,
            "relative_path": asset.relative_path,
            "original_filename": asset.original_filename,
            "byte_size": asset.byte_size,
            "case_id": case_row.id,
            "case_name": case_row.display_name,
            "report_unit_id": report.id,
            "report_name": report.display_name,
            "assigned_input_user_id": case_row.assigned_input_user_id,
            "assigned_reviewer_user_id": case_row.assigned_reviewer_user_id,
            "submission_count": submission_counts.get(
                document.id if document else None,
                0,
            ),
        }
        for asset, case_row, report, document in rows
    ]


def _pdf_storage_path(storage_filename):
    safe_name = os.path.basename(str(storage_filename or ""))
    if not safe_name or safe_name != storage_filename:
        raise HTTPException(status_code=400, detail="Tên file lưu trữ không hợp lệ")
    storage_root = Path(os.getenv("PDF_STORAGE_PATH", "uploads")).resolve()
    path = (storage_root / safe_name).resolve()
    try:
        path.relative_to(storage_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn PDF không hợp lệ")
    return path


def hard_delete_project_pdf(db, *, project_id, asset_id, deleted_by_user_id):
    repository = ProjectAdminRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    asset = repository.lock_asset(project.id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Không tìm thấy PDF trong dự án")
    submission_count = repository.submission_count_for_document(asset.assigned_document_id)
    if submission_count:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_pdf_has_submission",
                "message": "PDF đã có dữ liệu nhập nên không thể xóa cứng",
                "submission_count": submission_count,
            },
        )

    source_path = _pdf_storage_path(asset.storage_filename)
    tombstone_path = source_path.with_name(
        f".{source_path.name}.deleting-{uuid.uuid4().hex}"
    )
    file_was_present = source_path.is_file()
    if file_was_present:
        os.replace(source_path, tombstone_path)

    try:
        repository.add_pdf_deletion_audit(asset, deleted_by_user_id)
        relative_path = asset.relative_path
        repository.delete_asset_graph(asset)
        db.commit()
    except Exception:
        db.rollback()
        if tombstone_path.is_file() and not source_path.exists():
            os.replace(tombstone_path, source_path)
        raise

    file_removed = True
    if tombstone_path.is_file():
        try:
            tombstone_path.unlink()
        except OSError:
            file_removed = False
    return {
        "deleted_asset_id": asset_id,
        "relative_path": relative_path,
        "file_was_present": file_was_present,
        "file_removed": file_removed,
    }
