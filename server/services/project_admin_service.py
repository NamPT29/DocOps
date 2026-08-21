import os
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException

from server.repositories.project_admin_repository import ProjectAdminRepository
from server.services import export_job_service
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


def _project_snapshot_path(snapshot_filename):
    normalized = str(snapshot_filename or "").replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) != 2 or parts[0] != "project_snapshots" or parts[1] in {".", ".."}:
        return None
    template_root = Path(os.getenv("TEMPLATE_STORAGE_PATH", "templates")).resolve()
    path = (template_root / parts[0] / parts[1]).resolve()
    try:
        path.relative_to(template_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn bản lưu biểu mẫu không hợp lệ")
    return path


def _project_upload_session_path(session_id):
    safe_session_id = os.path.basename(str(session_id or ""))
    if not safe_session_id or safe_session_id != session_id:
        raise HTTPException(status_code=400, detail="Mã phiên tải dự án không hợp lệ")
    storage_root = Path(os.getenv("PDF_STORAGE_PATH", "uploads")).resolve()
    staging_root = (storage_root / ".project_uploads").resolve()
    path = (staging_root / safe_session_id).resolve()
    try:
        path.relative_to(staging_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn phiên tải dự án không hợp lệ")
    return path


def _project_export_artifacts(project_id):
    paths = []
    job_ids = []
    active_job_ids = []
    scratch_root = export_job_service.EXPORT_SCRATCH_DIR
    if not scratch_root.is_dir():
        return paths, job_ids, active_job_ids
    for status_path in scratch_root.glob("export_job_*.json"):
        job_id = status_path.stem.removeprefix("export_job_")
        try:
            payload = export_job_service.read_export_job(job_id)
            belongs_to_project = int((payload or {}).get("project_id")) == int(project_id)
        except (TypeError, ValueError):
            continue
        if not belongs_to_project:
            continue
        job_ids.append(job_id)
        if payload.get("state") in {"queued", "running"}:
            active_job_ids.append(job_id)
            continue
        paths.extend([
            status_path,
            scratch_root / f"export_job_{job_id}.log",
            scratch_root / f"export_job_{job_id}.xlsx",
            scratch_root / f"export_job_{job_id}.xlsm",
        ])
    return paths, job_ids, active_job_ids


def _stage_project_paths(paths):
    staged = []
    token = uuid.uuid4().hex
    unique_paths = sorted({Path(path) for path in paths}, key=lambda path: str(path).casefold())
    try:
        for source_path in unique_paths:
            if not source_path.exists():
                continue
            tombstone_path = source_path.with_name(
                f".{source_path.name}.deleting-project-{token}"
            )
            os.replace(source_path, tombstone_path)
            staged.append((source_path, tombstone_path))
    except Exception:
        _restore_project_paths(staged)
        raise
    return staged


def _restore_project_paths(staged):
    for source_path, tombstone_path in reversed(staged):
        try:
            if tombstone_path.exists() and not source_path.exists():
                os.replace(tombstone_path, source_path)
        except OSError:
            pass


def _remove_project_tombstones(staged):
    removed = 0
    failed = 0
    for _source_path, tombstone_path in staged:
        try:
            if tombstone_path.is_dir():
                shutil.rmtree(tombstone_path)
            else:
                tombstone_path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            failed += 1
    return removed, failed


def delete_project(db, *, project_id):
    repository = ProjectAdminRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    manifest = repository.project_delete_manifest(project.id)
    export_paths, export_job_ids, active_export_job_ids = _project_export_artifacts(project.id)
    if active_export_job_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_export_in_progress",
                "message": "Dự án đang có tác vụ xuất. Vui lòng chờ tác vụ hoàn tất rồi xóa lại.",
                "job_ids": active_export_job_ids,
            },
        )

    snapshot_path = _project_snapshot_path(project.template_filename_snapshot)
    upload_session_paths = [
        _project_upload_session_path(session_id)
        for session_id in manifest["upload_session_ids"]
    ]
    file_paths = [
        _pdf_storage_path(filename)
        for filename in manifest["storage_filenames"]
    ]
    file_paths.extend(upload_session_paths)
    file_paths.extend(export_paths)
    if snapshot_path is not None:
        file_paths.append(snapshot_path)

    staged = _stage_project_paths(file_paths)
    project_name = project.name
    try:
        counts = repository.delete_project_graph(project, manifest)
        db.commit()
    except Exception:
        db.rollback()
        _restore_project_paths(staged)
        raise

    removed_paths, failed_paths = _remove_project_tombstones(staged)
    for job_id in export_job_ids:
        export_job_service.release_export_lock(job_id)
    for candidate in {
        *(path.parent for path in upload_session_paths),
        snapshot_path.parent if snapshot_path is not None else None,
    }:
        if candidate is None:
            continue
        try:
            candidate.rmdir()
        except OSError:
            pass

    return {
        "deleted_project_id": project_id,
        "deleted_project_name": project_name,
        "deleted": counts,
        "staged_paths": len(staged),
        "removed_paths": removed_paths,
        "file_cleanup_complete": failed_paths == 0,
    }


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
