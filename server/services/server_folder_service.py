import hashlib
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from server.database import SessionLocal, get_utc_now

from server.models import ServerFolderImportJob
from typing import List

from server.models import (
    AssignedDocument,
    AssignedDocumentFolder,
    AssignedDocumentPath,
    AssignedDocumentReviewAssignment,
)
from server.services.upload_service import DOCUMENT_EXTENSIONS, save_validated_upload
from server.repositories import (
    DocumentRepository,
    ReviewRepository,
    ServerFolderRepository,
    TemplateRepository,
    UserRepository,
)


MAX_SCAN_FILES = 100_000
PREVIEW_FILE_LIMIT = 300


@dataclass(frozen=True)
class ServerSourceDocument:
    source_path: Path
    relative_path: str
    grouping_prefix: tuple[str, ...]
    grouping_parts: tuple[str, ...]


def get_document_source_root() -> Path:
    configured = os.getenv("DOCUMENT_SOURCE_ROOT", "source_documents").strip()
    if not configured:
        configured = "source_documents"
    root = Path(configured).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise HTTPException(status_code=500, detail="Thư mục nguồn tài liệu không hợp lệ")
    return root


def resolve_server_source_directory(relative_path: str = "") -> tuple[Path, Path, str]:
    root = get_document_source_root()
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if normalized in {"", "."}:
        return root, root, ""
    if normalized.startswith("/") or ":" in normalized:
        raise HTTPException(status_code=400, detail="Đường dẫn nguồn không hợp lệ")

    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="Đường dẫn nguồn không hợp lệ")
    selected = root.joinpath(*parts).resolve()
    try:
        selected.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn nằm ngoài thư mục nguồn cho phép")
    if not selected.is_dir():
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục nguồn")
    return root, selected, selected.relative_to(root).as_posix()


def list_server_source_folders(relative_path: str = "") -> dict:
    root, selected, selected_relative = resolve_server_source_directory(relative_path)
    directories = []
    try:
        children = sorted(selected.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        raise HTTPException(status_code=403, detail="Không thể đọc thư mục nguồn")

    for child in children:
        try:
            resolved = child.resolve()
            resolved.relative_to(root)
            if not resolved.is_dir():
                continue
        except (OSError, ValueError):
            continue
        directories.append(
            {
                "name": child.name,
                "relative_path": resolved.relative_to(root).as_posix(),
            }
        )

    parent_relative = None
    if selected != root:
        parent = selected.parent
        parent_relative = "" if parent == root else parent.relative_to(root).as_posix()
    return {
        "root_path": str(root),
        "current_path": str(selected),
        "current_relative_path": selected_relative,
        "parent_relative_path": parent_relative,
        "directories": directories,
    }


def scan_server_source_documents(relative_path: str = "") -> tuple[dict, list[ServerSourceDocument]]:
    root, selected, selected_relative = resolve_server_source_directory(relative_path)
    managed_storage = Path(os.getenv("PDF_STORAGE_PATH", "uploads")).resolve()
    documents = []
    try:
        candidates = selected.rglob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in DOCUMENT_EXTENSIONS:
                continue
            resolved = candidate.resolve()
            try:
                resolved.relative_to(managed_storage)
                continue
            except ValueError:
                pass
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            local_relative = resolved.relative_to(selected)
            documents.append(
                ServerSourceDocument(
                    source_path=resolved,
                    relative_path=resolved.relative_to(root).as_posix(),
                    grouping_prefix=tuple(PurePosixPath(selected_relative).parts)
                    if selected_relative
                    else (),
                    grouping_parts=tuple(local_relative.parent.parts)
                    if local_relative.parent != Path(".")
                    else (),
                )
            )
            if len(documents) > MAX_SCAN_FILES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Thư mục vượt quá giới hạn {MAX_SCAN_FILES} tài liệu",
                )
    except HTTPException:
        raise
    except OSError:
        raise HTTPException(status_code=403, detail="Không thể quét thư mục nguồn")

    documents.sort(key=lambda item: item.relative_path.casefold())
    max_depth = max((len(item.grouping_parts) for item in documents), default=0)
    maximum_selectable_level = max(1, max_depth)
    grouping_levels = []
    for level in range(1, maximum_selectable_level + 1):
        groups = sorted({folder_group_for_level(item, level) for item in documents})
        grouping_levels.append(
            {
                "level": level,
                "group_count": len(groups),
                "examples": groups[:5],
            }
        )

    summary = {
        "root_path": str(root),
        "selected_path": str(selected),
        "selected_relative_path": selected_relative,
        "total_files": len(documents),
        "max_folder_depth": max_depth,
        "grouping_levels": grouping_levels,
        "preview": [item.relative_path for item in documents[:PREVIEW_FILE_LIMIT]],
        "preview_truncated": len(documents) > PREVIEW_FILE_LIMIT,
    }
    return summary, documents


def folder_group_for_level(document: ServerSourceDocument, level: int) -> str:
    if level < 1:
        raise HTTPException(status_code=400, detail="Cấp folder phân việc phải từ 1 trở lên")
    selected_parts = document.grouping_parts[: min(level, len(document.grouping_parts))]
    full_group_parts = document.grouping_prefix + selected_parts
    return "/".join(full_group_parts) if full_group_parts else "__ROOT__"


def source_document_upload_id(document: ServerSourceDocument, template_id: int) -> str:
    stat = document.source_path.stat()
    identity = "\0".join(
        [
            str(document.source_path).casefold(),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            str(template_id),
        ]
    )
    return "server:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()



def _validate_import_job(job, user_ids, reviewer_ids, db):
    user_repository = UserRepository(db)
    valid_input_ids = user_repository.input_user_ids()
    valid_reviewer_ids = {user.id for user in user_repository.list_all()}
    if not set(user_ids).issubset(valid_input_ids):
        raise HTTPException(status_code=400, detail="Danh sách người nhập không hợp lệ")
    if not reviewer_ids or not set(reviewer_ids).issubset(valid_reviewer_ids):
        raise HTTPException(status_code=400, detail="Danh sách người kiểm tra không hợp lệ")
    if any(not (set(reviewer_ids) - {user_id}) for user_id in user_ids):
        raise HTTPException(
            status_code=400,
            detail="Mỗi người nhập phải có ít nhất một người kiểm tra khác mình",
        )
    if not TemplateRepository(db).get(job.template_id):
        raise HTTPException(status_code=404, detail="Biểu mẫu không tồn tại")


def _prepare_group_assignments(documents, job, user_ids, reviewer_ids) -> tuple[dict, dict]:
    groups = sorted(
        {folder_group_for_level(document, job.grouping_level) for document in documents},
        key=str.casefold,
    )
    group_assignees = {
        group: user_ids[index % len(user_ids)] for index, group in enumerate(groups)
    }
    
    group_reviewers = {}
    for group, assignee_id in group_assignees.items():
        reviewer_candidates = [rid for rid in reviewer_ids if rid != assignee_id]
        if not reviewer_candidates:
            raise HTTPException(
                status_code=400,
                detail=f"Folder {group} không có người kiểm tra khác người nhập",
            )
        group_reviewers[group] = secrets.choice(reviewer_candidates)
        
    return group_assignees, group_reviewers

def _process_existing_document(
    existing, group, group_assignees, group_reviewers, 
    review_repository, document_repository
):
    _, assigned_document, folder_metadata = existing
    if assigned_document.status == "pending":
        assignee_id = group_assignees[group]
        assigned_document.assigned_to_user_id = assignee_id
        reviewer_id = group_reviewers[group]
        review_assignment = review_repository.get_document_assignment(
            assigned_document.id
        )
        if review_assignment:
            review_assignment.reviewer_user_id = reviewer_id
            review_assignment.assigned_at = get_utc_now()
        else:
            document_repository.add_review_assignment(
                AssignedDocumentReviewAssignment(
                    document_id=assigned_document.id,
                    reviewer_user_id=reviewer_id,
                )
            )
        if folder_metadata:
            folder_metadata.folder_group = group
        else:
            document_repository.add_folder(
                AssignedDocumentFolder(
                    document_id=assigned_document.id,
                    folder_group=group,
                )
            )

def _import_new_document(
    document, group, upload_id, job, group_assignees, group_reviewers,
    storage_path, document_repository, db
):
    extension = document.source_path.suffix.lower()
    uuid_name = f"{uuid.uuid4()}{extension}"
    destination = storage_path / uuid_name
    try:
        with document.source_path.open("rb") as source_stream:
            upload = UploadFile(filename=document.source_path.name, file=source_stream)
            save_validated_upload(upload, str(destination), kind="document")
            
        assigned_document = AssignedDocument(
            original_filename=document.source_path.name,
            uuid_filename=uuid_name,
            assigned_to_user_id=group_assignees[group],
            template_id=job.template_id,
            status="pending",
        )
        document_repository.add(assigned_document)
        db.flush()
        
        document_repository.add_review_assignment(
            AssignedDocumentReviewAssignment(
                document_id=assigned_document.id,
                reviewer_user_id=group_reviewers[group],
            )
        )
        document_repository.add_path(
            AssignedDocumentPath(
                document_id=assigned_document.id,
                relative_path=document.relative_path,
                upload_id=upload_id,
            )
        )
        document_repository.add_folder(
            AssignedDocumentFolder(
                document_id=assigned_document.id,
                folder_group=group,
            )
        )
        return True, None
    except Exception as error:
        if destination.exists():
            destination.unlink()
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        detail = detail or error.__class__.__name__
        return False, detail

def process_server_folder_import(
    job_id: int,
    session_factory=SessionLocal,
) -> None:
    db: Session = session_factory()
    try:
        job_repository = ServerFolderRepository(db)
        document_repository = DocumentRepository(db)
        review_repository = ReviewRepository(db)
        job = job_repository.get(job_id)
        if not job:
            return
        job.status = "running"
        job.error_message = None
        db.commit()

        summary, documents = scan_server_source_documents(job.source_relative_path)
        user_ids = [int(value) for value in json.loads(job.user_ids_json)]
        reviewer_ids = job_repository.reviewer_ids(job.id)

        _validate_import_job(job, user_ids, reviewer_ids, db)
        group_assignees, group_reviewers = _prepare_group_assignments(documents, job, user_ids, reviewer_ids)
        
        job.total_files = summary["total_files"]
        db.commit()

        storage_path = Path(os.getenv("PDF_STORAGE_PATH", "uploads")).resolve()
        storage_path.mkdir(parents=True, exist_ok=True)

        for document in documents:
            job.current_path = document.relative_path
            group = folder_group_for_level(document, job.grouping_level)
            upload_id = source_document_upload_id(document, job.template_id)
            existing = document_repository.find_import_by_upload_id(upload_id)
            if existing:
                _process_existing_document(
                    existing, group, group_assignees, group_reviewers, 
                    review_repository, document_repository
                )
                job.skipped_files += 1
            else:
                success, error_detail = _import_new_document(
                    document, group, upload_id, job, group_assignees, group_reviewers,
                    storage_path, document_repository, db
                )
                if success:
                    job.imported_files += 1
                else:
                    db.rollback()
                    job = job_repository.get(job_id)
                    job.failed_files += 1
                    if not job.error_message:
                        job.error_message = f"{document.relative_path}: {error_detail}"[:1000]

            job.processed_files += 1
            db.commit()

        if job.failed_files and job.imported_files == 0 and job.skipped_files == 0:
            job.status = "failed"
        else:
            job.status = "completed" if job.failed_files == 0 else "completed_with_errors"
        job.current_path = None
        job.completed_at = get_utc_now()
        db.commit()
    except Exception as error:
        db.rollback()
        job = job_repository.get(job_id)
        if job:
            detail = error.detail if isinstance(error, HTTPException) else str(error)
            job.status = "failed"
            job.error_message = detail[:1000]
            job.completed_at = get_utc_now()
            db.commit()
    finally:
        db.close()


def create_server_folder_import_job(
    db: Session,
    template_id: int,
    input_user_ids: List[int],
    reviewer_user_ids: List[int],
    relative_path: str,
    grouping_level: int,
    current_user_id: int
) -> ServerFolderImportJob:
    input_user_ids = list(dict.fromkeys(input_user_ids))
    reviewer_user_ids = list(dict.fromkeys(reviewer_user_ids))
    if not input_user_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một người nhập")
    if not reviewer_user_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một người kiểm tra")
    summary, _ = scan_server_source_documents(relative_path)
    if summary["total_files"] == 0:
        raise HTTPException(status_code=400, detail="Thư mục không có tài liệu được hỗ trợ")
    maximum_level = max(1, summary["max_folder_depth"])
    if grouping_level < 1 or grouping_level > maximum_level:
        raise HTTPException(status_code=400, detail="Cấp folder phân việc không hợp lệ")
    if not TemplateRepository(db).get(template_id):
        raise HTTPException(status_code=404, detail="Biểu mẫu không tồn tại")
        
    user_repository = UserRepository(db)
    valid_input_ids = user_repository.input_user_ids()
    valid_reviewer_ids = {user.id for user in user_repository.list_all()}
    if not set(input_user_ids).issubset(valid_input_ids):
        raise HTTPException(status_code=400, detail="Danh sách người nhập không hợp lệ")
    if not set(reviewer_user_ids).issubset(valid_reviewer_ids):
        raise HTTPException(status_code=400, detail="Danh sách người kiểm tra không hợp lệ")
    if any(not (set(reviewer_user_ids) - {user_id}) for user_id in input_user_ids):
        raise HTTPException(
            status_code=400,
            detail="Mỗi người nhập phải có ít nhất một người kiểm tra khác mình",
        )

    job = ServerFolderImportJob(
        created_by_user_id=current_user_id,
        template_id=template_id,
        source_relative_path=summary["selected_relative_path"],
        grouping_level=grouping_level,
        user_ids_json=json.dumps(input_user_ids),
        status="queued",
        total_files=summary["total_files"],
    )
    repository = ServerFolderRepository(db)
    repository.add(job)
    db.flush()
    repository.add_reviewers(job.id, reviewer_user_ids)
    db.commit()
    db.refresh(job)
    return job
