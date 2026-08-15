import os
import json
import uuid
from typing import Literal, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import timedelta, datetime, timezone
from server.database import get_db
from server.models import (
    Submission,
    SubmissionReviewAssignment,
    AssignedDocument,
)
from server.routers.auth import (
    get_current_user,
    get_admin_user,
    get_input_user,
    get_reviewer_user,
)
from server.services.upload_service import save_validated_upload
from server.repositories import (
    DocumentRepository,
    LookupRepository,
    ReviewRepository,
    SubmissionRepository,
    SubmissionViewRepository,
)
from server.services.submission_metadata_service import (
    NO_FOLDER_SENTINEL,
    apply_submission_metadata,
    backfill_submission_metadata,
    normalize_folder_path,
)
from fastapi import HTTPException

router = APIRouter(prefix="/api", tags=["submissions"])
PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH", "uploads")
COMPLETED_WITHOUT_FOLDER = NO_FOLDER_SENTINEL


def _get_review_assignment(db: Session, submission_id: int):
    return ReviewRepository(db).get_submission_assignment(submission_id)


def _assign_submission_reviewer(
    submission: Submission,
    db: Session,
    *,
    document: AssignedDocument | None = None,
    required: bool = True,
):
    review_repository = ReviewRepository(db)
    lookup_repository = LookupRepository(db)
    assignment = review_repository.get_submission_assignment(submission.id)
    document_assignment = None
    if document:
        document_assignment = review_repository.get_document_assignment(document.id)
    reviewer_id = document_assignment.reviewer_user_id if document_assignment else None
    if reviewer_id:
        if not lookup_repository.user_exists(reviewer_id):
            reviewer_id = None
    elif assignment and assignment.reviewer_user_id != submission.created_by_user_id:
        if lookup_repository.user_exists(assignment.reviewer_user_id):
            return assignment
    if not reviewer_id or reviewer_id == submission.created_by_user_id:
        if required:
            raise HTTPException(
                status_code=409,
                detail="Tài liệu chưa được phân người kiểm tra phù hợp",
            )
        return None
    if assignment:
        assignment.reviewer_user_id = reviewer_id
        assignment.assigned_at = datetime.now()
    else:
        assignment = SubmissionReviewAssignment(
            submission_id=submission.id,
            reviewer_user_id=reviewer_id,
        )
        review_repository.add(assignment)
    return assignment


def _backfill_pending_review_assignments(db: Session) -> None:
    backfill_submission_metadata(db)
    review_repository = ReviewRepository(db)
    pending, assignments, document_reviewers = (
        review_repository.pending_assignment_context()
    )
    if not pending:
        return
    candidate_user_ids = set(document_reviewers.values()) | {
        assignment.reviewer_user_id
        for assignment in assignments.values()
        if assignment.reviewer_user_id is not None
    }
    valid_user_ids = LookupRepository(db).existing_user_ids(candidate_user_ids)

    changed = False
    for submission in pending:
        assignment = assignments.get(submission.id)
        reviewer_id = document_reviewers.get(submission.assigned_document_id)
        if (
            reviewer_id not in valid_user_ids
            or reviewer_id == submission.created_by_user_id
        ):
            reviewer_id = None
        if reviewer_id is None and assignment:
            existing_reviewer_id = assignment.reviewer_user_id
            if (
                existing_reviewer_id in valid_user_ids
                and existing_reviewer_id != submission.created_by_user_id
            ):
                continue
        if reviewer_id is None:
            continue
        if assignment:
            if assignment.reviewer_user_id == reviewer_id:
                continue
            assignment.reviewer_user_id = reviewer_id
            assignment.assigned_at = datetime.now()
        else:
            assignment = SubmissionReviewAssignment(
                submission_id=submission.id,
                reviewer_user_id=reviewer_id,
            )
            review_repository.add(assignment)
            assignments[submission.id] = assignment
        changed = True
    if changed:
        db.commit()


def _can_review_submission(submission: Submission, current_user: dict, db: Session) -> bool:
    if current_user.get('role') == 'admin':
        return True
    assignment = _get_review_assignment(db, submission.id)
    return bool(
        assignment
        and assignment.reviewer_user_id == current_user["id"]
        and submission.created_by_user_id != current_user["id"]
    )


def _require_assigned_reviewer(
    submission: Submission,
    current_user: dict,
    db: Session,
) -> SubmissionReviewAssignment:
    if current_user.get('role') == 'admin':
        return _get_review_assignment(db, submission.id)
    assignment = _get_review_assignment(db, submission.id)
    if (
        not assignment
        or assignment.reviewer_user_id != current_user["id"]
        or submission.created_by_user_id == current_user["id"]
    ):
        raise HTTPException(status_code=403, detail="Hồ sơ không được phân cho bạn kiểm tra")
    return assignment


def _pdf_url(uuid_filename: str) -> str:
    return f"/api/files/{quote(uuid_filename, safe='')}"


def _folder_files_for_document(document: AssignedDocument | None, db: Session) -> list[dict]:
    if not document:
        return []
    repository = DocumentRepository(db)
    folder = repository.get_folder(document.id)
    if not folder or not folder.folder_group:
        return []
    rows = repository.list_folder_files(folder.folder_group)
    return [
        {
            "name": item.original_filename,
            "uuid": item.uuid_filename,
            "url": _pdf_url(item.uuid_filename),
            "relative_path": relative_path,
            "folder_group": folder.folder_group,
            "template_id": item.template_id,
        }
        for item, relative_path in rows
    ]


def _resolve_document(data: dict, db: Session, owner_id: int, pending_only: bool = False):
    uuid_filename = data.get("_pdf_uuid")
    original_filename = data.get("_pdf_filename")
    if not uuid_filename and not original_filename:
        return None

    return DocumentRepository(db).resolve_reference(
        owner_id=owner_id,
        uuid_filename=uuid_filename,
        original_filename=original_filename,
        pending_only=pending_only,
    )


def _enrich_pdf_reference(
    data: dict,
    db: Session,
    owner_id: int,
    pending_only: bool = False,
    allow_unregistered: bool = False,
):
    enriched = dict(data)
    document = _resolve_document(enriched, db, owner_id, pending_only)
    if document:
        enriched["_pdf_filename"] = document.original_filename
        enriched["_pdf_uuid"] = document.uuid_filename
        enriched["_pdf_url"] = _pdf_url(document.uuid_filename)
        relative_path, folder_group = DocumentRepository(db).get_path_and_folder(
            document.id
        )
        if relative_path:
            enriched["_pdf_relative_path"] = relative_path
        else:
            enriched.pop("_pdf_relative_path", None)
        if folder_group and folder_group != "__ROOT__":
            enriched["_folder_path"] = folder_group
        else:
            enriched.pop("_folder_path", None)
    elif enriched.get("_pdf_uuid"):
        uuid_filename = os.path.basename(str(enriched["_pdf_uuid"]))
        if not allow_unregistered:
            raise HTTPException(status_code=400, detail="File đính kèm không thuộc người dùng")
        enriched["_pdf_uuid"] = uuid_filename
        enriched["_pdf_url"] = _pdf_url(uuid_filename)
    elif enriched.get("_pdf_filename") and not allow_unregistered:
        raise HTTPException(status_code=400, detail="Không xác minh được file đính kèm")
    return enriched, document


def _sync_submission_metadata(
    submission: Submission,
    data: dict,
    document: AssignedDocument | None,
    db: Session,
) -> None:
    folder_path = normalize_folder_path(data.get("_folder_path"))
    if not folder_path and document:
        folder_metadata = DocumentRepository(db).get_folder(document.id)
        folder_path = normalize_folder_path(
            getattr(folder_metadata, "folder_group", None)
        )
    apply_submission_metadata(
        submission,
        data,
        document=document,
        folder_path=folder_path,
    )


def _load_submission_document_metadata(
    submissions: list[Submission],
    db: Session,
) -> dict[int, dict]:
    document_ids = {
        submission.assigned_document_id
        for submission in submissions
        if submission.assigned_document_id is not None
    }
    metadata = DocumentRepository(db).metadata_map(document_ids)
    for item in metadata.values():
        item["folder_path"] = normalize_folder_path(item["folder_path"])
    return metadata


class SubmitRequest(BaseModel):
    template_id: Optional[int] = None
    data: dict
    status: Optional[Literal["draft", "pending_review"]] = None

class ErrorSectionsRequest(BaseModel):
    wrong_sections: list[str]
    wrong_fields: Optional[list[str]] = None


class ReviewContentRequest(BaseModel):
    data: dict
    wrong_fields: Optional[list[str]] = None


def _normalize_wrong_fields(values: Optional[list[str]]) -> list[str]:
    normalized = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        field_name = value.strip()
        if not field_name or field_name.startswith("_") or field_name in normalized:
            continue
        normalized.append(field_name)
    return normalized


class BulkSubmissionActionRequest(BaseModel):
    submission_ids: list[int]
    action: Literal["delete", "submit_for_review"]

@router.post("/submit")
def api_submit(req: SubmitRequest, current_user: dict = Depends(get_input_user), db: Session = Depends(get_db)):
    try:
        repository = SubmissionRepository(db)
        data_dict, document = _enrich_pdf_reference(
            req.data, db, current_user["id"], pending_only=True
        )
        sub = Submission(
            data_json=json.dumps(data_dict, ensure_ascii=False),
            created_by_user_id=current_user["id"],
            template_id=req.template_id,
            status=req.status or "draft"
        )
        _sync_submission_metadata(sub, data_dict, document, db)
        repository.add(sub)
        if hasattr(db, "flush"):
            repository.flush()
        if req.status == "pending_review" and sub.id is not None:
            _assign_submission_reviewer(sub, db, document=document)
        if document and req.status == "pending_review":
            document.status = "completed"

        db.commit()
        return {"status": "ok"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.get("/submissions")
def api_get_submissions(
    template_id: int = None,
    start_date: str = None,
    end_date: str = None,
    status: str = None,
    folder_path: str = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if page < 1:
            raise HTTPException(status_code=400, detail="Số trang phải lớn hơn hoặc bằng 1")
        if page_size < 1 or page_size > 100:
            raise HTTPException(status_code=400, detail="Số hồ sơ mỗi trang phải từ 1 đến 100")
        backfill_submission_metadata(db)
        repository = SubmissionRepository(db)
        submissions, total, total_pages, current_page = repository.paginate(
            owner_id=(
                None if current_user["role"] == "admin" else current_user["id"]
            ),
            status=status,
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            folder_path=folder_path,
            page=page,
            page_size=page_size,
        )

        document_metadata = _load_submission_document_metadata(submissions, db)
        assignment_map = ReviewRepository(db).assignment_map(submissions)
        user_ids = {
            submission.created_by_user_id
            for submission in submissions
            if submission.created_by_user_id is not None
        } | {
            reviewer_id for reviewer_id in assignment_map.values()
            if reviewer_id is not None
        }
        lookup_repository = LookupRepository(db)
        user_map = lookup_repository.username_map(user_ids)
        template_ids = {
            submission.template_id
            for submission in submissions
            if submission.template_id is not None
        }
        template_map = lookup_repository.template_name_map(template_ids)
            
        results = []
        for index, sub in enumerate(submissions):
            data_dict = json.loads(sub.data_json)
            metadata = document_metadata.get(sub.assigned_document_id)
            if metadata:
                document = metadata["document"]
                data_dict["_pdf_filename"] = document.original_filename
                data_dict["_pdf_uuid"] = document.uuid_filename
                data_dict["_pdf_url"] = _pdf_url(document.uuid_filename)
                if metadata["relative_path"]:
                    data_dict["_pdf_relative_path"] = metadata["relative_path"]
            elif data_dict.get("_pdf_uuid"):
                uuid_filename = os.path.basename(str(data_dict["_pdf_uuid"]))
                data_dict["_pdf_uuid"] = uuid_filename
                data_dict["_pdf_url"] = _pdf_url(uuid_filename)
            submission_folder = normalize_folder_path(sub.folder_path)
            if not submission_folder:
                submission_folder = COMPLETED_WITHOUT_FOLDER
            ho_ten = data_dict.get("col_8", "") or data_dict.get("col_25", "") or "(Chưa có tên)"
            so_giay_to = data_dict.get("col_13", "") or data_dict.get("col_30", "") or "(Chưa có CMND)"
            template_name = template_map.get(sub.template_id, "Unknown") if sub.template_id else "Unknown"
            result_folder_path = (
                "" if submission_folder == COMPLETED_WITHOUT_FOLDER else submission_folder
            )
                
            results.append({
                "id": sub.id,
                "serial_number": (current_page - 1) * page_size + index + 1,
                "ho_ten": ho_ten,
                "so_giay_to": so_giay_to,
                "created_at": (sub.created_at + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S") if sub.created_at else "",
                "template": template_name,
                "template_id": sub.template_id,
                "pdf_filename": data_dict.get("_pdf_filename", ""),
                "pdf_relative_path": data_dict.get("_pdf_relative_path", ""),
                "folder_path": result_folder_path,
                "folder_name": "Thư mục gốc" if result_folder_path == "__ROOT__" else result_folder_path.rstrip("/").rsplit("/", 1)[-1] if result_folder_path else "",
                "is_checked": sub.is_checked,
                "status": sub.status,
                "has_errors": (
                    sub.status == "rejected"
                    or bool(data_dict.get("_wrong_sections", []))
                    or bool(data_dict.get("_wrong_fields", []))
                ),
                "creator_name": user_map.get(sub.created_by_user_id, "Unknown"),
                "reviewer_name": user_map.get(assignment_map.get(sub.id), "Chưa phân công"),
            })
        first_item = (current_page - 1) * page_size + 1 if total else 0
        return {
            "status": "ok",
            "data": results,
            "pagination": {
                "page": current_page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "from": first_item,
                "to": first_item + len(results) - 1 if results else 0,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/completed-folders")
def api_get_completed_folders(
    template_id: int = None,
    start_date: str = None,
    end_date: str = None,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    backfill_submission_metadata(db)
    count_rows, input_rows, template_rows = (
        SubmissionRepository(db).completed_folder_groups(
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
        )
    )

    groups: dict[tuple[str | None, str], dict] = {}
    for folder_path, folder_key, approved_count in count_rows:
        response_path = folder_path or COMPLETED_WITHOUT_FOLDER
        group_key = (folder_path, folder_key)
        groups[group_key] = (
            {
                "folder_path": response_path,
                "folder_name": (
                    "Chưa xác định folder"
                    if not folder_path
                    else "Thư mục gốc"
                    if folder_path == "__ROOT__"
                    else folder_path.rsplit("/", 1)[-1]
                ),
                "approved_count": approved_count,
                "input_names": set(),
                "template_names": set(),
            }
        )

    for folder_path, folder_key, username in input_rows:
        groups[(folder_path, folder_key)]["input_names"].add(
            username or "Không xác định"
        )

    for folder_path, folder_key, template_name in template_rows:
        groups[(folder_path, folder_key)]["template_names"].add(
            template_name or "Không xác định"
        )

    data = []
    for group_key in sorted(
        groups,
        key=lambda value: (
            value[0] is None,
            (value[0] or "").lower(),
        ),
    ):
        group = groups[group_key]
        group["input_names"] = sorted(group["input_names"], key=str.lower)
        group["template_names"] = sorted(group["template_names"], key=str.lower)
        data.append(group)
    return {"status": "ok", "data": data}


def _review_submission_payload(
    submission: Submission,
    document_metadata: dict | None,
    user_map: dict[int, str],
    template_map: dict[int, str],
    viewer_map: dict[int, dict] | None = None,
) -> dict:
    data_dict = json.loads(submission.data_json)
    viewer = (viewer_map or {}).get(submission.id)
    if document_metadata:
        document = document_metadata["document"]
        data_dict["_pdf_filename"] = document.original_filename
        data_dict["_pdf_uuid"] = document.uuid_filename
        data_dict["_pdf_url"] = _pdf_url(document.uuid_filename)
        if document_metadata["relative_path"]:
            data_dict["_pdf_relative_path"] = document_metadata["relative_path"]
    elif data_dict.get("_pdf_uuid"):
        uuid_filename = os.path.basename(str(data_dict["_pdf_uuid"]))
        data_dict["_pdf_uuid"] = uuid_filename
        data_dict["_pdf_url"] = _pdf_url(uuid_filename)
    folder_path = normalize_folder_path(submission.folder_path)
    return {
        'viewing_user_id': viewer.get('user_id') if viewer else None,
        'viewing_user_name': viewer.get('username') if viewer else None,
        'is_being_viewed': bool(viewer),
        "id": submission.id,
        "ho_ten": data_dict.get("col_8", "") or data_dict.get("col_25", "") or "(Chưa có tên)",
        "so_giay_to": data_dict.get("col_13", "") or data_dict.get("col_30", "") or "(Chưa có CMND)",
        "created_at": (submission.created_at + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S") if submission.created_at else "",
        "template": template_map.get(submission.template_id, "Unknown") if submission.template_id else "Unknown",
        "template_id": submission.template_id,
        "pdf_filename": data_dict.get("_pdf_filename", ""),
        "pdf_relative_path": data_dict.get("_pdf_relative_path", ""),
        "folder_path": folder_path,
        "folder_name": folder_path.rstrip("/").rsplit("/", 1)[-1] if folder_path else "",
        "is_checked": submission.is_checked,
        "status": submission.status,
        "has_errors": (
            submission.status == "rejected"
            or bool(data_dict.get("_wrong_sections", []))
            or bool(data_dict.get("_wrong_fields", []))
        ),
        "creator_name": user_map.get(submission.created_by_user_id, "Unknown"),
    }


def _get_admin_review_folder_groups(
    db: Session,
    template_id: int | None,
) -> list[dict]:
    submissions = SubmissionRepository(db).list_active_review_submissions(
        template_id=template_id,
    )
    user_ids = {
        submission.created_by_user_id
        for submission in submissions
        if submission.created_by_user_id is not None
    }
    template_ids = {
        submission.template_id
        for submission in submissions
        if submission.template_id is not None
    }
    lookup_repository = LookupRepository(db)
    user_map = lookup_repository.username_map(user_ids)
    template_map = lookup_repository.template_name_map(template_ids)
    groups: dict[str, dict] = {}
    for submission in submissions:
        folder_path = normalize_folder_path(submission.folder_path) or COMPLETED_WITHOUT_FOLDER
        group = groups.setdefault(
            folder_path,
            {
                'folder_path': folder_path,
                'folder_name': (
                    'Chưa xác định folder'
                    if folder_path == COMPLETED_WITHOUT_FOLDER
                    else 'Thư mục gốc'
                    if folder_path == '__ROOT__'
                    else folder_path.rstrip('/').rsplit('/', 1)[-1]
                ),
                'submitted_count': 0,
                'document_keys': set(),
                'input_names': set(),
                'template_names': set(),
            },
        )
        group['submitted_count'] += 1
        group['document_keys'].add(
            submission.assigned_document_id or f'submission:{submission.id}'
        )
        group['input_names'].add(
            user_map.get(submission.created_by_user_id, 'Unknown')
        )
        group['template_names'].add(
            template_map.get(submission.template_id, 'Unknown')
        )

    result = []
    for folder_path in sorted(groups, key=str.casefold):
        group = groups[folder_path]
        group['total_documents'] = len(group.pop('document_keys'))
        group['input_names'] = sorted(group['input_names'], key=str.casefold)
        group['template_names'] = sorted(group['template_names'], key=str.casefold)
        result.append(group)
    return result


@router.get('/review-folders')
def api_get_review_folders(
    template_id: int = None,
    current_user: dict = Depends(get_reviewer_user),
    db: Session = Depends(get_db),
):
    _backfill_pending_review_assignments(db)
    if current_user.get('role') == 'admin':
        return {
            'status': 'ok',
            'data': _get_admin_review_folder_groups(db, template_id),
        }
    repository = ReviewRepository(db)

    groups: dict[str, dict] = {}
    for document, folder_path, input_name, template_name in (
        repository.reviewer_folder_rows(current_user["id"], template_id)
    ):
        group = groups.setdefault(
            folder_path,
            {
                "folder_path": folder_path,
                "folder_name": "Thư mục gốc" if folder_path == "__ROOT__" else folder_path.rstrip("/").rsplit("/", 1)[-1],
                "total_documents": 0,
                "submitted_count": 0,
                "input_names": set(),
                "template_names": set(),
            },
        )
        group["total_documents"] += 1
        group["input_names"].add(input_name)
        if template_name:
            group["template_names"].add(template_name)
    submitted_counts = repository.reviewer_submitted_counts(
        current_user["id"],
        template_id,
    )
    for folder_path, submitted_count in submitted_counts:
        if folder_path in groups:
            groups[folder_path]["submitted_count"] = submitted_count

    data = []
    for folder_path in sorted(groups, key=lambda value: value.lower()):
        group = groups[folder_path]
        group["input_names"] = sorted(group["input_names"], key=str.lower)
        group["template_names"] = sorted(group["template_names"], key=str.lower)
        data.append(group)
    return {"status": "ok", "data": data}


@router.get("/review-folder-submissions")
def api_get_review_folder_submissions(
    folder_path: str,
    template_id: int = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_reviewer_user),
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="Số trang phải lớn hơn hoặc bằng 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="Số hồ sơ mỗi trang phải từ 1 đến 100")
    backfill_submission_metadata(db)
    _backfill_pending_review_assignments(db)
    review_repository = ReviewRepository(db)
    if current_user.get('role') != 'admin' and not review_repository.reviewer_has_folder(
        current_user["id"],
        folder_path,
        template_id,
    ):
        raise HTTPException(status_code=403, detail="Folder không được phân cho bạn kiểm tra")

    submission_repository = SubmissionRepository(db)
    if current_user.get('role') == 'admin':
        submissions_in_folder, total, total_pages, current_page = submission_repository.paginate(
            owner_id=None,
            status='pending_review,rejected',
            template_id=template_id,
            start_date=None,
            end_date=None,
            folder_path=folder_path,
            page=page,
            page_size=page_size,
        )
    else:
        all_submissions_in_folder = review_repository.reviewer_folder_submissions(
            current_user["id"],
            folder_path,
            template_id,
        )
        total = len(all_submissions_in_folder)
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        start_index = (current_page - 1) * page_size
        submissions_in_folder = all_submissions_in_folder[start_index:start_index + page_size]

    document_metadata = _load_submission_document_metadata(submissions_in_folder, db)
    user_ids = {
        submission.created_by_user_id
        for submission in submissions_in_folder
        if submission.created_by_user_id is not None
    }
    template_ids = {
        submission.template_id
        for submission in submissions_in_folder
        if submission.template_id is not None
    }
    lookup_repository = LookupRepository(db)
    user_map = lookup_repository.username_map(user_ids)
    template_map = lookup_repository.template_name_map(template_ids)
    viewer_map = SubmissionViewRepository(db).active_map(
        [submission.id for submission in submissions_in_folder]
    )
    return {
        "status": "ok",
        "folder_path": folder_path,
        "data": [
            _review_submission_payload(
                submission,
                document_metadata.get(submission.assigned_document_id),
                user_map,
                template_map,
                viewer_map,
            )
            for submission in submissions_in_folder
        ],
        "pagination": {
            "page": current_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "from": (current_page - 1) * page_size + 1 if total else 0,
            "to": (current_page - 1) * page_size + len(submissions_in_folder) if total else 0,
        },
    }

@router.get("/submissions/{sub_id}")
def api_get_submission(sub_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
        can_review = _can_review_submission(sub, current_user, db)
        if (
            current_user["role"] != "admin"
            and sub.created_by_user_id != current_user["id"]
            and not can_review
        ):
            return {"status": "error", "message": "Không có quyền truy cập hồ sơ này."}
        data_dict, document = _enrich_pdf_reference(
            json.loads(sub.data_json),
            db,
            sub.created_by_user_id,
            allow_unregistered=True,
        )
        return {
            "status": "ok",
            "data": data_dict,
            "template_id": sub.template_id,
            "is_checked": sub.is_checked,
            "submission_status": sub.status,
            "can_review": can_review,
            # Every user who is authorized to open this submission needs the
            # complete source folder for comparison. `can_review` remains the
            # separate authority for approving or rejecting the submission.
            "folder_files": _folder_files_for_document(document, db),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.put('/submissions/{sub_id}/view')
def api_claim_submission_view(
    sub_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = SubmissionRepository(db).get(sub_id)
    if not submission:
        raise HTTPException(status_code=404, detail='Không tìm thấy hồ sơ')
    if (
        current_user.get('role') != 'admin'
        and submission.created_by_user_id != current_user.get('id')
        and not _can_review_submission(submission, current_user, db)
    ):
        raise HTTPException(status_code=403, detail='Không có quyền xem hồ sơ này')

    presence = SubmissionViewRepository(db).claim(submission.id, current_user['id'])
    db.commit()
    viewer_name = LookupRepository(db).username_map({presence.viewer_user_id}).get(
        presence.viewer_user_id,
        'Người dùng khác',
    )
    return {
        'status': 'ok',
        'is_being_viewed': True,
        'viewing_user_id': presence.viewer_user_id,
        'viewing_user_name': viewer_name,
        'viewer_is_current_user': presence.viewer_user_id == current_user['id'],
    }


@router.delete('/submissions/{sub_id}/view')
def api_release_submission_view(
    sub_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    removed = SubmissionViewRepository(db).release(sub_id, current_user['id'])
    db.commit()
    return {'status': 'ok', 'released': removed}


@router.put('/submissions/{sub_id}')
def api_update_submission(sub_id: int, req: SubmitRequest, current_user: dict = Depends(get_input_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
            
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Bạn không có quyền sửa hồ sơ này.")
        if current_user["role"] != "admin" and sub.status not in {"draft", "rejected"}:
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ đã nộp duyệt nên không thể chỉnh sửa",
            )
        
        data_dict, document = _enrich_pdf_reference(
            req.data, db, sub.created_by_user_id
        )
        sub.data_json = json.dumps(data_dict, ensure_ascii=False)
        _sync_submission_metadata(sub, data_dict, document, db)
        sub.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if req.status:
            sub.status = req.status
        if req.status == "pending_review":
            _assign_submission_reviewer(sub, db, document=document)
        if document and req.status == "pending_review":
            document.status = "completed"
            
        # Nộp lại hồ sơ sau khi báo lỗi thì xóa lỗi đi
        if req.status == "pending_review":
            if "_wrong_sections" in data_dict:
                data_dict["_wrong_sections"] = []
                sub.data_json = json.dumps(data_dict, ensure_ascii=False)
                
        db.commit()
        return {"status": "ok"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.put("/submissions/{sub_id}/review-content")
def api_update_review_content(
    sub_id: int,
    req: ReviewContentRequest,
    current_user: dict = Depends(get_reviewer_user),
    db: Session = Depends(get_db),
):
    try:
        submission = SubmissionRepository(db).get(sub_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
        _require_assigned_reviewer(submission, current_user, db)
        if submission.status not in {"pending_review", "rejected"}:
            raise HTTPException(status_code=409, detail="Hồ sơ không còn ở bước kiểm tra")

        stored_data = json.loads(submission.data_json)
        for key, value in req.data.items():
            if not key.startswith("_"):
                stored_data[key] = value
        if req.wrong_fields is not None:
            stored_data["_wrong_fields"] = _normalize_wrong_fields(req.wrong_fields)
        # Legacy records may already be in `rejected`. Once the assigned
        # reviewer corrects them, keep them in the review queue instead of
        # sending them back to the input user.
        if submission.status == "rejected":
            submission.status = "pending_review"
        submission.is_checked = False
        submission.data_json = json.dumps(stored_data, ensure_ascii=False)
        db.commit()
        return {
            "status": "ok",
            "submission_status": submission.status,
            "wrong_fields": stored_data.get("_wrong_fields", []),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.put("/submissions/{sub_id}/toggle_check")
def api_toggle_check(sub_id: int, current_user: dict = Depends(get_reviewer_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
        _require_assigned_reviewer(sub, current_user, db)
        if sub.status != "pending_review":
            raise HTTPException(status_code=409, detail="Hồ sơ không ở trạng thái chờ duyệt")
        sub.is_checked = True
        sub.status = "approved"
        
        db.commit()
        return {"status": "ok", "is_checked": sub.is_checked, "new_status": sub.status}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.put("/submissions/{sub_id}/reopen-review")
def api_reopen_submission_review(
    sub_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Chỉ admin được chuyển hồ sơ về chờ duyệt",
        )

    submission = SubmissionRepository(db).get(sub_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
    if submission.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="Chỉ hồ sơ đã duyệt mới có thể chuyển về chờ duyệt",
        )

    submission.status = "pending_review"
    submission.is_checked = False
    db.commit()
    return {
        "status": "ok",
        "new_status": submission.status,
        "is_checked": submission.is_checked,
    }

@router.put("/submissions/{sub_id}/errors")
def api_update_errors(sub_id: int, req: ErrorSectionsRequest, current_user: dict = Depends(get_reviewer_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
        _require_assigned_reviewer(sub, current_user, db)
        if sub.status not in {"pending_review", "rejected"}:
            raise HTTPException(status_code=409, detail="Hồ sơ không ở trạng thái kiểm tra")
            
        data_dict = json.loads(sub.data_json)
        data_dict["_wrong_sections"] = req.wrong_sections
        if req.wrong_fields is not None:
            data_dict["_wrong_fields"] = _normalize_wrong_fields(req.wrong_fields)
        sub.data_json = json.dumps(data_dict, ensure_ascii=False)
        # Error markers are review metadata. They never return the report to
        # the input user; the reviewer corrects the marked fields directly.
        if sub.status == "rejected":
            sub.status = "pending_review"
        sub.is_checked = False
        db.commit()
        return {
            "status": "ok",
            "submission_status": sub.status,
            "wrong_fields": data_dict.get("_wrong_fields", []),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.delete("/submissions/{sub_id}")
def api_delete_submission(sub_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        submission_repository = SubmissionRepository(db)
        sub = submission_repository.get(sub_id)
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}

        if current_user["role"] != "admin":
            if sub.created_by_user_id != current_user["id"]:
                raise HTTPException(status_code=403, detail="Bạn không có quyền xóa hồ sơ này")
            if sub.status != "draft":
                raise HTTPException(status_code=409, detail="Nhân viên chỉ có thể xóa hồ sơ đang lưu nháp")

        ReviewRepository(db).delete_for_submissions([sub_id])
        submission_repository.delete(sub)
        db.commit()
        return {"status": "ok"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.post("/submissions/bulk-action")
def api_bulk_submission_action(
    req: BulkSubmissionActionRequest,
    current_user: dict = Depends(get_input_user),
    db: Session = Depends(get_db),
):
    submission_ids = list(dict.fromkeys(req.submission_ids))
    if not submission_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một hồ sơ")
    if len(submission_ids) > 100:
        raise HTTPException(status_code=400, detail="Mỗi lần chỉ xử lý tối đa 100 hồ sơ")

    try:
        submission_repository = SubmissionRepository(db)
        selected = submission_repository.list_by_ids(submission_ids)
        if len(selected) != len(submission_ids):
            raise HTTPException(status_code=404, detail="Có hồ sơ không tồn tại")
        if current_user["role"] != "admin" and any(
            submission.created_by_user_id != current_user["id"]
            for submission in selected
        ):
            raise HTTPException(status_code=403, detail="Bạn không có quyền xử lý một hoặc nhiều hồ sơ đã chọn")

        if req.action == "delete":
            invalid = [submission.id for submission in selected if submission.status != "draft"]
            if invalid:
                raise HTTPException(
                    status_code=409,
                    detail="Chỉ có thể xóa hàng loạt các hồ sơ đang lưu nháp",
                )
            ReviewRepository(db).delete_for_submissions(submission_ids)
            for submission in selected:
                submission_repository.delete(submission)
        else:
            invalid = [
                submission.id
                for submission in selected
                if submission.status not in {"draft", "rejected"}
            ]
            if invalid:
                raise HTTPException(
                    status_code=409,
                    detail="Chỉ hồ sơ lưu nháp hoặc bị báo lỗi mới có thể nộp duyệt",
                )

            submitted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            for submission in selected:
                data_dict, document = _enrich_pdf_reference(
                    json.loads(submission.data_json),
                    db,
                    submission.created_by_user_id,
                )
                _assign_submission_reviewer(submission, db, document=document)
                data_dict.pop("_wrong_sections", None)
                submission.data_json = json.dumps(data_dict, ensure_ascii=False)
                _sync_submission_metadata(submission, data_dict, document, db)
                submission.status = "pending_review"
                submission.created_at = submitted_at
                if document:
                    document.status = "completed"

        db.commit()
        return {
            "status": "ok",
            "action": req.action,
            "processed_count": len(selected),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.post("/submissions/{sub_id}/copy")
def api_copy_submission(sub_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        repository = SubmissionRepository(db)
        sub = repository.get(sub_id)
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
            
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Bạn không có quyền nhân bản hồ sơ này.")
        
        new_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        new_sub = Submission(
            data_json=sub.data_json,
            template_id=sub.template_id,
            created_at=new_created_at,
            created_by_user_id=current_user["id"],  # Mới: Người copy sẽ là người tạo
            assigned_document_id=sub.assigned_document_id,
            folder_path=sub.folder_path,
            folder_path_key=sub.folder_path_key,
        )
        repository.add(new_sub)
        db.commit()
        db.refresh(new_sub)
        return {"status": "ok", "new_id": new_sub.id}
    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

from fastapi.concurrency import run_in_threadpool

@router.get("/export")
async def api_export(
    template_id: int,
    background_tasks: BackgroundTasks,
    folder_path: str = None,
    start_date: str = None,
    end_date: str = None,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        template = LookupRepository(db).get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Không tìm thấy template mẫu.")
            
        template_file_path = os.path.join("templates", template.filename)
        template_extension = os.path.splitext(template.filename)[1].lower()
        if template_extension not in {".xlsx", ".xlsm"}:
            raise HTTPException(status_code=400, detail="Định dạng file mẫu không được hỗ trợ.")
        
        os.makedirs("scratch", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"BaoCao_{template_id}_{timestamp}{template_extension}"
        download_path = os.path.join("scratch", download_filename)
        
        from server.services.excel_service import export_submissions_to_excel
        
        backfill_submission_metadata(db)
        submissions = SubmissionRepository(db).approved_for_export(
            template_id=template_id,
            folder_path=folder_path,
            start_date=start_date,
            end_date=end_date,
        )
        if not submissions:
            raise HTTPException(
                status_code=404,
                detail="Không có hồ sơ đã duyệt để xuất báo cáo cho biểu mẫu này.",
            )
            
        await run_in_threadpool(export_submissions_to_excel, template_file_path, submissions, download_path)
        
        def remove_file(path):
            try:
                os.remove(path)
            except:
                pass
        
        background_tasks.add_task(remove_file, download_path)
        
        return FileResponse(download_path, filename=download_filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể xuất báo cáo: {e}")

@router.post("/upload-pdf")
async def api_upload_pdf(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filepath = None
    try:
        os.makedirs(PDF_STORAGE_PATH, exist_ok=True)
        original_filename = os.path.basename(file.filename or "")
        if not original_filename:
            raise HTTPException(status_code=400, detail="Tên file không hợp lệ")
        new_filename = f"{uuid.uuid4()}_{original_filename}"
        filepath = os.path.join(PDF_STORAGE_PATH, new_filename)

        save_validated_upload(file, filepath, kind="document")
        document = AssignedDocument(
            original_filename=original_filename,
            uuid_filename=new_filename,
            assigned_to_user_id=current_user["id"],
            template_id=None,
            status="pending",
        )
        db.add(document)
        db.commit()

        return {
            "status": "ok",
            "name": original_filename,
            "uuid": new_filename,
            "url": _pdf_url(new_filename)
        }
    except HTTPException:
        db.rollback()
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        raise
    except Exception:
        db.rollback()
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(status_code=500, detail="Không thể lưu file")


@router.get("/files/{uuid_filename}")
def api_get_pdf_file(
    uuid_filename: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    safe_filename = os.path.basename(uuid_filename)
    if not safe_filename or safe_filename != uuid_filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ")

    document_repository = DocumentRepository(db)
    review_repository = ReviewRepository(db)
    submission_repository = SubmissionRepository(db)
    document = document_repository.get_by_uuid(safe_filename)
    original_filename = document.original_filename if document else safe_filename

    if document:
        if current_user["role"] != "admin":
            # A document can be reviewed by a user who is not its input/owner
            # (`assigned_to_user_id`).  The review assignment is the authority
            # for opening the source PDF in that workflow.
            is_assigned_reviewer = document_repository.is_direct_reviewer(
                document.id,
                current_user["id"],
            )
            folder_metadata = document_repository.get_folder(document.id)
            is_folder_reviewer = False
            if folder_metadata and folder_metadata.folder_group:
                is_folder_reviewer = document_repository.is_folder_reviewer(
                    folder_metadata.folder_group,
                    current_user["id"],
                )
            is_submission_reviewer = review_repository.reviewer_has_linked_submission(
                current_user["id"],
                document.id,
                safe_filename,
            )
            if (
                document.assigned_to_user_id != current_user["id"]
                and not is_assigned_reviewer
                and not is_folder_reviewer
                and not is_submission_reviewer
            ):
                raise HTTPException(status_code=403, detail="Không có quyền truy cập file")
    else:
        legacy_submission = submission_repository.latest_legacy_pdf_submission(
            safe_filename,
            None if current_user["role"] == "admin" else current_user["id"],
        )
        if not legacy_submission:
            raise HTTPException(status_code=404, detail="File không tồn tại")
        legacy_data = json.loads(legacy_submission.data_json)
        if os.path.basename(str(legacy_data.get("_pdf_uuid", ""))) != safe_filename:
            raise HTTPException(status_code=404, detail="File không tồn tại")
        original_filename = legacy_data.get("_pdf_filename") or safe_filename

    filepath = os.path.join(PDF_STORAGE_PATH, safe_filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File không tồn tại")

    extension = os.path.splitext(safe_filename)[1].lower()
    media_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_types.get(extension)
    if not media_type:
        raise HTTPException(status_code=415, detail="Định dạng file không được hỗ trợ")

    encoded_name = quote(str(original_filename), safe="")
    return FileResponse(
        filepath,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
        },
    )

