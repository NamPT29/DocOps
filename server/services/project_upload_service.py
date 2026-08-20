import hashlib
import os
import secrets
import uuid
from pathlib import Path

from fastapi import HTTPException

from server.models import (
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    ProjectUploadFile,
    ProjectUploadSession,
)
from server.repositories.project_upload_repository import ProjectUploadRepository
from server.services.project_assignment_service import assign_unassigned_project_cases
from server.services.project_manifest_service import (
    ProjectManifestError,
    derive_project_group_keys,
    prepare_project_manifest,
    select_required_project_uploads,
)


DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 16 * 1024 * 1024


def _configured_chunk_bytes():
    try:
        value = int(os.getenv("PROJECT_UPLOAD_CHUNK_BYTES", str(DEFAULT_CHUNK_BYTES)))
    except ValueError:
        value = DEFAULT_CHUNK_BYTES
    return max(1024 * 1024, min(value, MAX_CHUNK_BYTES))


def _configured_concurrency():
    try:
        value = int(os.getenv("PROJECT_UPLOAD_CONCURRENCY", "4"))
    except ValueError:
        value = 4
    return max(1, min(value, 8))


def _storage_root():
    return Path(os.getenv("PDF_STORAGE_PATH", "uploads")).resolve()


def _staging_path(session, upload_file):
    filename = os.path.basename(upload_file.staging_filename or "")
    if not filename or filename != upload_file.staging_filename:
        raise HTTPException(status_code=500, detail="Tên file tạm không hợp lệ")
    return _storage_root() / ".project_uploads" / session.id / filename


def serialize_upload_session(db, session):
    files = ProjectUploadRepository(db).list_session_files(session.id)
    return {
        "id": session.id,
        "project_id": session.project_id,
        "state": session.status,
        "manifest_digest": session.manifest_digest,
        "total_files": session.total_files,
        "requested_files": session.requested_files,
        "completed_files": session.completed_files,
        "failed_files": session.failed_files,
        "chunk_size_bytes": _configured_chunk_bytes(),
        "concurrency": _configured_concurrency(),
        "files": [
            {
                "file_id": item.id,
                "relative_path": item.relative_path,
                "size": item.expected_size,
                "sha256": item.expected_sha256,
                "next_offset": item.next_offset,
                "state": item.status,
                "error_message": item.error_message,
            }
            for item in files
        ],
    }


def create_or_resume_upload_session(
    db,
    *,
    project_id,
    created_by_user_id,
    client_session_key,
    raw_items,
):
    repository = ProjectUploadRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    try:
        prepared = prepare_project_manifest(
            raw_items,
            case_level=project.case_level,
            report_mode=project.report_mode,
            report_level=project.report_level,
        )
    except ProjectManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session_key = str(client_session_key or "").strip()
    if not session_key or len(session_key) > 100:
        raise HTTPException(status_code=400, detail="Khóa phiên tải không hợp lệ")

    existing_session = repository.find_session_by_client_key(project.id, session_key)
    if existing_session:
        if existing_session.manifest_digest != prepared["manifest_digest"]:
            raise HTTPException(
                status_code=409,
                detail="Khóa phiên đã được dùng cho một manifest khác",
            )
        return serialize_upload_session(db, existing_session)

    assets = repository.asset_identities(project.id)
    existing_assets = [
        {
            "normalized_relative_path": row[0],
            "content_sha256": row[1],
            "byte_size": row[2],
            "status": row[3],
        }
        for row in assets
    ]
    required_items = select_required_project_uploads(prepared["items"], existing_assets)

    session = ProjectUploadSession(
        id=secrets.token_hex(24),
        project_id=project.id,
        created_by_user_id=created_by_user_id,
        client_session_key=session_key,
        manifest_digest=prepared["manifest_digest"],
        status="created",
        total_files=prepared["total_files"],
        requested_files=len(required_items),
    )
    db.add(session)
    db.flush()
    for item in required_items:
        upload_file = ProjectUploadFile(
            session_id=session.id,
            relative_path=item["relative_path"],
            normalized_relative_path=item["normalized_relative_path"],
            expected_sha256=item["sha256"],
            expected_size=item["size"],
            client_last_modified=(
                str(item["last_modified"])
                if item.get("last_modified") is not None
                else None
            ),
        )
        db.add(upload_file)
        db.flush()
        upload_file.staging_filename = f"{upload_file.id}-{upload_file.expected_sha256}.part"
    project.status = "importing" if required_items else project.status
    db.commit()
    db.refresh(session)
    return serialize_upload_session(db, session)


def get_upload_session(db, *, session_id):
    session = ProjectUploadRepository(db).get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên tải")
    return serialize_upload_session(db, session)


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_upload_chunk(db, *, session_id, file_id, offset, chunk):
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise HTTPException(status_code=400, detail="Offset không hợp lệ")
    if not chunk:
        raise HTTPException(status_code=400, detail="Chunk rỗng")
    if len(chunk) > _configured_chunk_bytes():
        raise HTTPException(status_code=413, detail="Chunk vượt quá giới hạn")

    repository = ProjectUploadRepository(db)
    session = repository.lock_session(session_id)
    upload_file = repository.lock_session_file(session_id, file_id)
    if not session or not upload_file:
        raise HTTPException(status_code=404, detail="Không tìm thấy file trong phiên tải")
    if session.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Phiên tải đã kết thúc")

    staging_path = _staging_path(session, upload_file)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    actual_size = staging_path.stat().st_size if staging_path.exists() else 0
    if actual_size > upload_file.next_offset:
        with staging_path.open("r+b") as output:
            output.truncate(upload_file.next_offset)
        actual_size = upload_file.next_offset
    if actual_size < upload_file.next_offset:
        upload_file.next_offset = actual_size
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={"message": "File tạm bị thiếu dữ liệu", "next_offset": actual_size},
        )

    if offset < upload_file.next_offset:
        if offset + len(chunk) > upload_file.next_offset or not staging_path.exists():
            raise HTTPException(
                status_code=409,
                detail={"message": "Chunk chồng lấn không hợp lệ", "next_offset": upload_file.next_offset},
            )
        with staging_path.open("rb") as source:
            source.seek(offset)
            stored = source.read(len(chunk))
        if stored != chunk:
            raise HTTPException(
                status_code=409,
                detail={"message": "Nội dung chunk gửi lại không khớp", "next_offset": upload_file.next_offset},
            )
        return {
            "status": "ok",
            "file_id": upload_file.id,
            "next_offset": upload_file.next_offset,
            "state": upload_file.status,
        }
    if offset > upload_file.next_offset:
        raise HTTPException(
            status_code=409,
            detail={"message": "Chunk đến sai thứ tự", "next_offset": upload_file.next_offset},
        )
    if offset + len(chunk) > upload_file.expected_size:
        raise HTTPException(status_code=400, detail="Chunk vượt quá dung lượng khai báo")
    if offset == 0 and not chunk.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Nội dung không phải PDF")

    mode = "r+b" if staging_path.exists() else "xb"
    with staging_path.open(mode) as output:
        output.seek(offset)
        output.write(chunk)
        output.flush()
        os.fsync(output.fileno())

    upload_file.next_offset = offset + len(chunk)
    upload_file.status = "uploading"
    upload_file.error_message = None
    session.status = "uploading"
    if upload_file.next_offset == upload_file.expected_size:
        actual_sha256 = _hash_file(staging_path)
        if actual_sha256 != upload_file.expected_sha256:
            upload_file.status = "failed"
            upload_file.error_message = "SHA-256 không khớp"
            upload_file.next_offset = 0
            session.failed_files = repository.count_session_files_by_status(
                session.id,
                "failed",
            )
            db.commit()
            staging_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="SHA-256 của file không khớp")
        upload_file.status = "uploaded"

    db.flush()
    session.completed_files = repository.count_session_files_by_status(
        session.id,
        "uploaded",
    )
    session.failed_files = repository.count_session_files_by_status(
        session.id,
        "failed",
    )
    db.commit()
    return {
        "status": "ok",
        "file_id": upload_file.id,
        "next_offset": upload_file.next_offset,
        "state": upload_file.status,
    }


def _get_or_create_case(db, repository, project, grouping):
    case_row = repository.find_case(project.id, grouping["case_key"])
    if case_row:
        return case_row
    case_row = ProjectCase(
        project_id=project.id,
        case_key=grouping["case_key"],
        display_name=grouping["case_name"],
    )
    db.add(case_row)
    db.flush()
    return case_row


def _get_or_create_report(db, repository, project, case_row, grouping):
    report = repository.find_report(case_row.id, grouping["report_key"])
    if report:
        return report
    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case_row.id,
        report_key=grouping["report_key"],
        display_name=grouping["report_name"],
    )
    db.add(report)
    db.flush()
    return report


def finalize_upload_session(db, *, session_id):
    repository = ProjectUploadRepository(db)
    session = repository.lock_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên tải")
    if session.status == "completed":
        return serialize_upload_session(db, session)

    project = repository.lock_project(session.project_id)
    upload_files = repository.list_session_files(session.id)
    incomplete = [item.relative_path for item in upload_files if item.status != "uploaded"]
    if incomplete:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Chưa tải xong toàn bộ file",
                "remaining_files": len(incomplete),
            },
        )

    storage_root = _storage_root()
    storage_root.mkdir(parents=True, exist_ok=True)
    moved_files = []
    imported_files = 0
    reused_files = 0
    assignment_counts = {"input_assigned": 0, "reviewer_assigned": 0}
    try:
        for upload_file in upload_files:
            staging_path = _staging_path(session, upload_file)
            if not staging_path.is_file():
                raise HTTPException(
                    status_code=409,
                    detail=f"Không tìm thấy file tạm: {upload_file.relative_path}",
                )
            grouping = derive_project_group_keys(
                upload_file.relative_path,
                case_level=project.case_level,
                report_mode=project.report_mode,
                report_level=project.report_level,
            )
            case_row = _get_or_create_case(db, repository, project, grouping)
            report = _get_or_create_report(db, repository, project, case_row, grouping)

            exact_asset = repository.find_exact_asset(
                project.id,
                upload_file.normalized_relative_path,
                upload_file.expected_sha256,
                upload_file.expected_size,
            )
            if exact_asset:
                exact_asset.case_id = case_row.id
                exact_asset.report_unit_id = report.id
                exact_asset.status = "active"
                exact_asset.error_message = None
                staging_path.unlink(missing_ok=True)
                reused_files += 1
                continue

            repository.mark_other_active_path_assets_replaced(
                project.id,
                upload_file.normalized_relative_path,
            )
            storage_filename = f"project-{project.id}-{uuid.uuid4().hex}.pdf"
            destination = storage_root / storage_filename
            os.replace(staging_path, destination)
            moved_files.append((staging_path, destination))
            db.add(
                ProjectDocumentAsset(
                    project_id=project.id,
                    case_id=case_row.id,
                    report_unit_id=report.id,
                    relative_path=upload_file.relative_path,
                    normalized_relative_path=upload_file.normalized_relative_path,
                    original_filename=Path(upload_file.relative_path).name,
                    storage_filename=storage_filename,
                    content_sha256=upload_file.expected_sha256,
                    byte_size=upload_file.expected_size,
                    client_last_modified=upload_file.client_last_modified,
                    status="active",
                )
            )
            imported_files += 1

        assignment_counts = assign_unassigned_project_cases(
            db,
            project_id=project.id,
            changed_by_user_id=session.created_by_user_id,
        )
        session.status = "completed"
        session.completed_files = session.requested_files
        session.failed_files = 0
        project.status = "ready"
        db.commit()
    except Exception:
        db.rollback()
        for staging_path, destination in reversed(moved_files):
            try:
                if destination.exists():
                    staging_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, staging_path)
            except OSError:
                pass
        raise

    result = serialize_upload_session(db, session)
    result["imported_files"] = imported_files
    result["reused_files"] = reused_files
    result["assignment_counts"] = assignment_counts
    return result
