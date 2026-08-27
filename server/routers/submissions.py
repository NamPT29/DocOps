from server.services.review_workflow_service import ReviewWorkflowService
import os
import json
import uuid
from typing import Literal, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File
from fastapi.concurrency import run_in_threadpool
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
from server.settings import settings
from server.repositories import (
    DocumentRepository,
    LookupRepository,
    ReviewRepository,
    SubmissionRepository,
    SubmissionViewRepository,
    TemplateRepository,
)
from server.repositories.project_reporting_repository import ProjectReportingRepository
from server.services.submission_metadata_service import (
    apply_submission_metadata,
    backfill_submission_metadata,
)
from server.services.submission_service import COMPLETED_WITHOUT_FOLDER, SubmissionService, _load_submission_document_metadata, _pdf_url
from server.services.export_job_service import (
    ExportJobBusyError,
    cleanup_export_job,
    export_job_output_path,
    public_export_job,
    read_export_job,
    start_export_job,
)
from server.services.api_rate_limit_service import enforce_heavy_api_rate_limit
from server.utils.folder_utils import (
    NO_FOLDER_SENTINEL,
    normalize_folder_path,
)
from fastapi import HTTPException

router = APIRouter(prefix="/api", tags=["submissions"])
PDF_STORAGE_PATH = str(settings.pdf_storage_path)
DOCUMENT_UPLOAD_MAX_BYTES = settings.document_upload_max_bytes
COMPLETED_WITHOUT_FOLDER = NO_FOLDER_SENTINEL












class SubmitRequest(BaseModel):
    template_id: Optional[int] = None
    data: dict
    status: Optional[Literal["draft", "pending_review"]] = None
    sync_cover: Optional[bool] = False

class ErrorSectionsRequest(BaseModel):
    wrong_sections: list[str]
    wrong_fields: Optional[list[str]] = None


class ReviewContentRequest(BaseModel):
    data: dict
    wrong_fields: Optional[list[str]] = None






class BulkSubmissionActionRequest(BaseModel):
    submission_ids: list[int]
    action: Literal["delete", "submit_for_review"]

@router.post("/submit")
def api_submit(req: SubmitRequest, current_user: dict = Depends(get_input_user), db: Session = Depends(get_db)):
    try:
        if req.status not in {None, "draft"}:
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ mới chỉ được lưu nháp. Hãy mở hồ sơ đã nhập để nộp duyệt.",
            )
        repository = SubmissionRepository(db)
        data_dict, document = SubmissionService.enrich_pdf_reference(
            req.data, db, current_user["id"], pending_only=True
        )
        sub = Submission(
            data_json=json.dumps(data_dict, ensure_ascii=False),
            created_by_user_id=current_user["id"],
            template_id=req.template_id,
            status="draft"
        )
        SubmissionService.sync_submission_metadata(sub, data_dict, document, db)
        repository.add(sub)
        if hasattr(db, "flush"):
            repository.flush()
        if document:
            document.status = "completed"

        if req.sync_cover:
            SubmissionService.sync_cover_data(sub, req.template_id, data_dict, db)

        db.commit()
        return {"status": "ok"}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

@router.get("/submissions")
def api_get_submissions(
    template_id: int = None,
    start_date: str = None,
    end_date: str = None,
    status: str = None,
    folder_path: str = None,
    page: int = 1,
    page_size: int = 20,
    duplicate_only: bool = False,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if page < 1:
            raise HTTPException(status_code=400, detail="Số trang phải lớn hơn hoặc bằng 1")
        if page_size < 1 or page_size > 100:
            raise HTTPException(status_code=400, detail="Số hồ sơ mỗi trang phải từ 1 đến 100")
            
        backfill_submission_metadata(db)
        
        return SubmissionService.get_paginated_submissions_payload(
            db=db,
            current_user=current_user,
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            folder_path=folder_path,
            page=page,
            page_size=page_size,
            duplicate_only=duplicate_only,
        )
    except HTTPException:
        raise
    except Exception:
        raise


@router.get("/completed-folders")
def api_get_completed_folders(
    template_id: int = None,
    start_date: str = None,
    end_date: str = None,
    duplicate_only: bool = False,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    backfill_submission_metadata(db)
    count_rows, input_rows, template_rows = (
        SubmissionRepository(db).completed_folder_groups(
            template_id=template_id,
            start_date=start_date,
            end_date=end_date,
            duplicate_only=duplicate_only,
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


@router.get('/review-folders')
def api_get_review_folders(
    template_id: int = None,
    duplicate_only: bool = False,
    current_user: dict = Depends(get_reviewer_user),
    db: Session = Depends(get_db),
):
    ReviewWorkflowService.backfill_pending_review_assignments(db)
    if current_user.get('role') == 'admin':
        return {
            'status': 'ok',
            'data': ReviewWorkflowService.get_admin_review_folder_groups(
                db,
                template_id,
                duplicate_only=duplicate_only,
            ),
        }
    repository = ReviewRepository(db)

    groups: dict[str, dict] = {}
    for folder_path, input_name, template_name, count in (
        repository.reviewer_folder_rows(
            current_user["id"],
            template_id,
            duplicate_only=duplicate_only,
        )
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
        group["total_documents"] += count
        if duplicate_only:
            group["submitted_count"] += count
        group["input_names"].add(input_name)
        if template_name:
            group["template_names"].add(template_name)
    if not duplicate_only:
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
    duplicate_only: bool = False,
    current_user: dict = Depends(get_reviewer_user),
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="Số trang phải lớn hơn hoặc bằng 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="Số hồ sơ mỗi trang phải từ 1 đến 100")
    ReviewWorkflowService.backfill_pending_review_assignments(db)
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
            duplicate_only=duplicate_only,
        )
    else:
        total = review_repository.reviewer_folder_submissions_count(
            current_user["id"],
            folder_path,
            template_id,
            duplicate_only=duplicate_only,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        start_index = (current_page - 1) * page_size
        submissions_in_folder = review_repository.reviewer_folder_submissions(
            current_user["id"],
            folder_path,
            template_id,
            offset=start_index,
            limit=page_size,
            duplicate_only=duplicate_only,
        )

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
            ReviewWorkflowService.review_submission_payload(
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

@router.get("/review-next-submission")
def api_get_next_review_submission(
    current_id: int,
    folder_path: str = None,
    project_id: int = None,
    current_user: dict = Depends(get_reviewer_user),
    db: Session = Depends(get_db),
):
    """Return the next active review item in the same queue as ``current_id``."""
    backfill_submission_metadata(db)
    ReviewWorkflowService.backfill_pending_review_assignments(db)
    submission_repository = SubmissionRepository(db)
    current = submission_repository.get(current_id)
    if not current:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ đang kiểm tra")
    if project_id is not None:
        if current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Chỉ quản trị viên được duyệt theo dự án")
        project_repository = ProjectReportingRepository(db)
        if not project_repository.get_project(project_id):
            raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
        if not project_repository.submission_belongs_to_project(project_id, current.id):
            raise HTTPException(status_code=404, detail="Hồ sơ không thuộc dự án")
        candidates = project_repository.active_review_submissions(
            project_id,
            folder_path=folder_path,
        )
    else:
        candidates = None
    if current_user.get("role") != "admin" and not ReviewWorkflowService.can_review_submission(
        current,
        current_user,
        db,
    ):
        raise HTTPException(status_code=403, detail="Hồ sơ không được phân cho bạn kiểm tra")

    normalized_folder = normalize_folder_path(folder_path) if folder_path else None
    if candidates is not None:
        pass
    elif current_user.get("role") == "admin":
        candidates = submission_repository.list_active_review_submissions(
            folder_path=normalized_folder,
        )
    else:
        candidates = [
            submission
            for _assignment, submission in ReviewRepository(db).active_submission_assignments(
                current_user["id"]
            )
            if submission.created_by_user_id != current_user["id"]
            and (
                normalized_folder is None
                or normalize_folder_path(submission.folder_path) == normalized_folder
            )
        ]
        candidates.sort(
            key=lambda submission: (submission.created_at, submission.id),
            reverse=True,
        )

    current_key = (current.created_at, current.id)
    next_submission = next(
        (
            submission
            for submission in candidates
            if (submission.created_at, submission.id) < current_key
        ),
        None,
    )
    return {
        "status": "ok",
        "data": {"id": next_submission.id} if next_submission else None,
    }


@router.get("/submissions/{sub_id}")
def api_get_submission(sub_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
        can_review = ReviewWorkflowService.can_review_submission(sub, current_user, db)
        if (
            current_user["role"] != "admin"
            and sub.created_by_user_id != current_user["id"]
            and not can_review
        ):
            raise HTTPException(status_code=403, detail="Không có quyền truy cập hồ sơ này.")
        data_dict, document = SubmissionService.enrich_pdf_reference(
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
            "folder_files": SubmissionService.folder_files_for_document(document, db),
        }
    except Exception:
        raise

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
        and not ReviewWorkflowService.can_review_submission(submission, current_user, db)
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
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
            
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Bạn không có quyền sửa hồ sơ này.")
        if current_user["role"] != "admin" and sub.status not in {"draft", "rejected"}:
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ đã nộp duyệt nên không thể chỉnh sửa",
            )
        
        data_dict, document = SubmissionService.enrich_pdf_reference(
            req.data, db, sub.created_by_user_id
        )
        if req.status == "pending_review":
            SubmissionService.validate_required_fields(
                req.template_id or sub.template_id,
                req.data,
                db,
                allow_missing_linked_path=True,
            )
        sub.data_json = json.dumps(data_dict, ensure_ascii=False)
        SubmissionService.sync_submission_metadata(sub, data_dict, document, db)
        if req.status == "pending_review":
            SubmissionService.lock_duplicate_scope(sub.template_id, db)
            duplicate_count = SubmissionService.exact_duplicate_count(sub, data_dict, db)
            if duplicate_count:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "duplicate_submission",
                        "duplicate_count": duplicate_count,
                        "message": f"Có {duplicate_count} báo cáo trùng path và nội dung. Bản hiện tại vẫn được giữ lại ở trạng thái nháp.",
                    },
                )
        sub.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if req.status:
            sub.status = req.status
        if req.status == "pending_review":
            ReviewWorkflowService.assign_submission_reviewer(
                sub,
                db,
                document=document,
                required=False,
            )
        if document and req.status in {"draft", "pending_review"}:
            document.status = "completed"
            
        # Nộp lại hồ sơ sau khi báo lỗi thì xóa lỗi đi
        if req.status == "pending_review":
            if "_wrong_sections" in data_dict:
                data_dict["_wrong_sections"] = []
                sub.data_json = json.dumps(data_dict, ensure_ascii=False)
                
        if req.sync_cover:
            SubmissionService.sync_cover_data(sub, req.template_id or sub.template_id, data_dict, db)

        db.commit()
        return {"status": "ok"}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


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
        ReviewWorkflowService.require_assigned_reviewer(submission, current_user, db)
        if submission.status not in {"pending_review", "rejected"}:
            raise HTTPException(status_code=409, detail="Hồ sơ không còn ở bước kiểm tra")

        stored_data = json.loads(submission.data_json)
        for key, value in req.data.items():
            if not key.startswith("_"):
                stored_data[key] = value
        if req.wrong_fields is not None:
            stored_data["_wrong_fields"] = SubmissionService.normalize_wrong_fields(req.wrong_fields)
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
    except Exception:
        db.rollback()
        raise

@router.put("/submissions/{sub_id}/toggle_check")
def api_toggle_check(sub_id: int, current_user: dict = Depends(get_reviewer_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
        ReviewWorkflowService.require_assigned_reviewer(sub, current_user, db)
        if sub.status != "pending_review":
            raise HTTPException(status_code=409, detail="Hồ sơ không ở trạng thái chờ duyệt")
        sub.is_checked = True
        sub.status = "approved"
        
        db.commit()
        return {"status": "ok", "is_checked": sub.is_checked, "new_status": sub.status}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


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
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
        ReviewWorkflowService.require_assigned_reviewer(sub, current_user, db)
        if sub.status not in {"pending_review", "rejected"}:
            raise HTTPException(status_code=409, detail="Hồ sơ không ở trạng thái kiểm tra")
            
        data_dict = json.loads(sub.data_json)
        data_dict["_wrong_sections"] = req.wrong_sections
        if req.wrong_fields is not None:
            data_dict["_wrong_fields"] = SubmissionService.normalize_wrong_fields(req.wrong_fields)
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
    except Exception:
        db.rollback()
        raise

@router.delete("/submissions/{sub_id}")
def api_delete_submission(sub_id: int, current_user: dict = Depends(get_input_user), db: Session = Depends(get_db)):
    try:
        sub = SubmissionRepository(db).get(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
            
        SubmissionService.delete_submission(db, sub_id, current_user)
        return {"status": "ok"}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


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
        processed_count = SubmissionService.bulk_submission_action(db, req.action, submission_ids, current_user)
        return {
            "status": "ok",
            "action": req.action,
            "processed_count": processed_count,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

@router.post("/submissions/{sub_id}/copy")
def api_copy_submission(sub_id: int, current_user: dict = Depends(get_input_user), db: Session = Depends(get_db)):
    try:
        new_id = SubmissionService.copy_submission(db, sub_id, current_user)
        return {"status": "ok", "new_id": new_id}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

@router.get("/export")
async def api_export(
    template_id: int,
    background_tasks: BackgroundTasks,
    folder_path: str = None,
    start_date: str = None,
    end_date: str = None,
    include_pending_review: bool = False,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        if include_pending_review:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Xuất toàn bộ đã chuyển sang xử lý nền. "
                    "Vui lòng tải lại trang và bấm Xuất toàn bộ lần nữa."
                ),
            )
        template = LookupRepository(db).get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Không tìm thấy template mẫu.")
            
        template_file_path = os.path.join("templates", template.filename)
        template_extension = os.path.splitext(template.filename)[1].lower()
        if template_extension not in {".xlsx", ".xlsm"}:
            raise HTTPException(status_code=400, detail="Định dạng file mẫu không được hỗ trợ.")
        
        os.makedirs("scratch", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_prefix = "BaoCao_TatCa" if include_pending_review else "BaoCao"
        download_filename = f"{filename_prefix}_{template_id}_{timestamp}{template_extension}"
        download_path = os.path.join("scratch", download_filename)
        
        from server.services.excel_service import export_submissions_to_excel
        
        backfill_submission_metadata(db)
        submissions = SubmissionRepository(db).approved_for_export(
            template_id=template_id,
            folder_path=folder_path,
            start_date=start_date,
            end_date=end_date,
            include_pending_review=include_pending_review,
        )
        if not submissions:
            export_scope = "chờ duyệt hoặc đã duyệt" if include_pending_review else "đã duyệt"
            raise HTTPException(
                status_code=404,
                detail=f"Không có hồ sơ {export_scope} để xuất báo cáo cho biểu mẫu này.",
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
    except Exception:
        raise


@router.post("/export-jobs", status_code=202)
def api_start_export_job(
    template_id: int,
    folder_path: str = None,
    start_date: str = None,
    end_date: str = None,
    include_pending_review: bool = False,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    enforce_heavy_api_rate_limit("submission-export", current_user["id"], cost=30)
    template = LookupRepository(db).get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Không tìm thấy template mẫu.")
    extension = os.path.splitext(template.filename)[1].lower()
    if extension not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail="Định dạng file mẫu không được hỗ trợ.")
    try:
        job = start_export_job(
            template_id=template_id,
            extension=extension,
            include_pending_review=include_pending_review,
            folder_path=folder_path,
            start_date=start_date,
            end_date=end_date,
            requested_by_user_id=current_user["id"],
        )
    except ExportJobBusyError as exc:
        detail = "Một tác vụ xuất toàn bộ khác đang chạy. Vui lòng chờ tác vụ hiện tại hoàn tất."
        if exc.job_id:
            detail += f" Mã tác vụ: {exc.job_id}"
        raise HTTPException(status_code=409, detail=detail) from exc
    return {"status": "ok", "job": public_export_job(job)}


@router.get("/export-jobs/{job_id}")
def api_get_export_job(
    job_id: str,
    current_user: dict = Depends(get_admin_user),
):
    try:
        job = read_export_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ xuất")
    return {"status": "ok", "job": public_export_job(job)}


@router.get("/export-jobs/{job_id}/download")
def api_download_export_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_admin_user),
):
    try:
        job = read_export_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ xuất")
    if job.get("state") != "completed":
        raise HTTPException(status_code=409, detail=job.get("message") or "File chưa sẵn sàng")
    try:
        output_path = export_job_output_path(job_id, job.get("extension"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="File xuất không còn tồn tại")
    background_tasks.add_task(cleanup_export_job, job_id)
    return FileResponse(output_path, filename=job.get("filename") or output_path.name)

@router.post("/upload-pdf")
async def api_upload_pdf(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_input_user),
    db: Session = Depends(get_db),
):
    return await run_in_threadpool(_upload_pdf_sync, file, current_user, db)


def _upload_pdf_sync(file: UploadFile, current_user: dict, db: Session):
    filepath = None
    try:
        os.makedirs(PDF_STORAGE_PATH, exist_ok=True)
        original_filename = os.path.basename(file.filename or "")
        if not original_filename:
            raise HTTPException(status_code=400, detail="Tên file không hợp lệ")
        new_filename = f"{uuid.uuid4()}_{original_filename}"
        filepath = os.path.join(PDF_STORAGE_PATH, new_filename)

        save_validated_upload(
            file,
            filepath,
            kind="document",
            max_bytes=DOCUMENT_UPLOAD_MAX_BYTES,
        )
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

