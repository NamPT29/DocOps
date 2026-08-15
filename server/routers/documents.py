from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException, Form
from sqlalchemy.orm import Session
from typing import List, Literal
from datetime import datetime
import os
import secrets
import uuid
from urllib.parse import quote
from server.database import get_db, get_utc_now
from server.routers.auth import (
    get_admin_user,
    get_input_user,
)
from server.models import (
    AssignedDocument,
    AssignedDocumentReviewAssignment,
    Submission,
    SubmissionReviewAssignment,
    ServerFolderImportJob,
)
from server.services.upload_service import save_validated_upload
from server.services.submission_metadata_service import (
    NO_FOLDER_SENTINEL,
    backfill_submission_metadata,
    normalize_folder_path,
)
from server.repositories import (
    DocumentRepository,
    ReviewRepository,
    ServerFolderRepository,
    SubmissionRepository,
    TemplateRepository,
    UserRepository,
)
from server.services.server_folder_service import (
    list_server_source_folders,
    process_server_folder_import,
    scan_server_source_documents,
)
from pydantic import BaseModel
import json

router = APIRouter(prefix="/api", tags=["documents"])


class ServerFolderScanRequest(BaseModel):
    relative_path: str = ""


class ServerFolderImportRequest(BaseModel):
    template_id: int
    input_user_ids: List[int]
    reviewer_user_ids: List[int]
    relative_path: str = ""
    grouping_level: int


class RevokeAssignmentsRequest(BaseModel):
    user_id: int
    assignment_type: Literal["input", "reviewer"]
    folder_path: str | None = None


class RedistributeFolderReviewersRequest(BaseModel):
    reviewer_user_ids: List[int]


@router.get("/documents/server-folders")
def browse_server_folders(
    path: str = "",
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", **list_server_source_folders(path)}


@router.post("/documents/server-folder/scan")
def scan_server_folder(
    request: ServerFolderScanRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    summary, _ = scan_server_source_documents(request.relative_path)
    return {"status": "ok", **summary}


@router.post("/documents/server-folder/import")
def start_server_folder_import(
    request: ServerFolderImportRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    input_user_ids = list(dict.fromkeys(request.input_user_ids))
    reviewer_user_ids = list(dict.fromkeys(request.reviewer_user_ids))
    if not input_user_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một người nhập")
    if not reviewer_user_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một người kiểm tra")
    summary, _ = scan_server_source_documents(request.relative_path)
    if summary["total_files"] == 0:
        raise HTTPException(status_code=400, detail="Thư mục không có tài liệu được hỗ trợ")
    maximum_level = max(1, summary["max_folder_depth"])
    if request.grouping_level < 1 or request.grouping_level > maximum_level:
        raise HTTPException(status_code=400, detail="Cấp folder phân việc không hợp lệ")
    if not TemplateRepository(db).get(request.template_id):
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
        created_by_user_id=current_user["id"],
        template_id=request.template_id,
        source_relative_path=summary["selected_relative_path"],
        grouping_level=request.grouping_level,
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
    background_tasks.add_task(process_server_folder_import, job.id)
    return {"status": "ok", "job_id": job.id, "total_files": job.total_files}


@router.get("/documents/server-folder/jobs/{job_id}")
def get_server_folder_import_job(
    job_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    job = ServerFolderRepository(db).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt nhập tài liệu")
    return {
        "status": "ok",
        "job": {
            "id": job.id,
            "state": job.status,
            "total_files": job.total_files,
            "processed_files": job.processed_files,
            "imported_files": job.imported_files,
            "skipped_files": job.skipped_files,
            "failed_files": job.failed_files,
            "current_path": job.current_path,
            "error_message": job.error_message,
        },
    }

@router.post("/documents/upload-assign")
async def upload_and_assign_documents(
    template_id: int = Form(...),
    user_ids: str = Form(...),
    reviewer_user_ids: str = Form(...),
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_admin_user), 
    db: Session = Depends(get_db)
):
    # Parse user_ids
    try:
        user_id_list = [int(id.strip()) for id in user_ids.split(",") if id.strip()]
        if not user_id_list:
            return {"status": "error", "message": "Vui lòng chọn ít nhất 1 nhân viên."}
    except:
        return {"status": "error", "message": "Danh sách nhân viên không hợp lệ."}
    try:
        reviewer_id_list = [
            int(value.strip()) for value in reviewer_user_ids.split(",") if value.strip()
        ]
        if not reviewer_id_list:
            return {"status": "error", "message": "Vui lòng chọn ít nhất 1 người kiểm tra."}
    except ValueError:
        return {"status": "error", "message": "Danh sách người kiểm tra không hợp lệ."}
        
    from dotenv import load_dotenv
    load_dotenv()
    PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH", "uploads")
    os.makedirs(PDF_STORAGE_PATH, exist_ok=True)

    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Biểu mẫu không tồn tại")
    user_repository = UserRepository(db)
    valid_user_ids = user_repository.input_user_ids()
    valid_reviewer_ids = {user.id for user in user_repository.list_all()}
    if not set(user_id_list).issubset(valid_user_ids):
        raise HTTPException(status_code=400, detail="Danh sách nhân viên không hợp lệ")
    if not set(reviewer_id_list).issubset(valid_reviewer_ids):
        raise HTTPException(status_code=400, detail="Danh sách người kiểm tra không hợp lệ")
    if any(not (set(reviewer_id_list) - {user_id}) for user_id in user_id_list):
        raise HTTPException(
            status_code=400,
            detail="Mỗi người nhập phải có ít nhất một người kiểm tra khác mình",
        )
    
    uploaded_count = 0
    assigned_stats = {uid: 0 for uid in user_id_list}
    created_paths = []
    
    try:
        document_repository = DocumentRepository(db)
        for i, file in enumerate(files):
            if not file.filename:
                continue

            original_filename = os.path.basename(file.filename)
            uuid_name = str(uuid.uuid4()) + "_" + original_filename
            filepath = os.path.join(PDF_STORAGE_PATH, uuid_name)

            save_validated_upload(file, filepath, kind="document")
            created_paths.append(filepath)
                
            # Round-robin assignment
            assignee_id = user_id_list[uploaded_count % len(user_id_list)]
            
            doc = AssignedDocument(
                original_filename=original_filename,
                uuid_filename=uuid_name,
                assigned_to_user_id=assignee_id,
                template_id=template_id,
                status="pending"
            )
            document_repository.add(doc)
            db.flush()
            reviewer_candidates = [
                user_id for user_id in reviewer_id_list if user_id != assignee_id
            ]
            document_repository.add_review_assignment(
                AssignedDocumentReviewAssignment(
                    document_id=doc.id,
                    reviewer_user_id=secrets.choice(reviewer_candidates),
                )
            )
            assigned_stats[assignee_id] += 1
            uploaded_count += 1
            
        db.commit()
        return {
            "status": "ok", 
            "message": f"Đã tải lên và chia đều {uploaded_count} tài liệu cho {len(user_id_list)} nhân viên."
        }
    except HTTPException:
        db.rollback()
        for path in created_paths:
            if os.path.exists(path):
                os.remove(path)
        raise
    except Exception:
        db.rollback()
        for path in created_paths:
            if os.path.exists(path):
                os.remove(path)
        raise HTTPException(status_code=500, detail="Không thể tải lên và phân công tài liệu")

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


def _get_user_pending_assignment_folders(db: Session, user_id: int) -> list[dict]:
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


@router.get("/documents/assignments/folders")
def get_user_assignment_folders(
    user_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    target_user = UserRepository(db).get(user_id)
    if not target_user or target_user.role == "admin":
        raise HTTPException(status_code=400, detail="Nhân viên không hợp lệ")

    backfill_submission_metadata(db)
    groups = _get_user_pending_assignment_folders(db, target_user.id)
    data = [{
        "folder_path": group["folder_path"],
        "folder_name": group["folder_name"],
        "document_count": group["document_count"],
        "submission_count": group["submission_count"],
        "can_revoke": group["submission_count"] == 0,
    } for group in groups]
    return {
        "status": "ok",
        "user_id": target_user.id,
        "username": target_user.username,
        "folder_count": len(data),
        "data": data,
    }


@router.post("/documents/assignments/revoke")
def revoke_user_assignments(
    request: RevokeAssignmentsRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    target_user = UserRepository(db).get(request.user_id)
    if not target_user or target_user.role == "admin":
        raise HTTPException(status_code=400, detail="Nhân viên thu hồi không hợp lệ")

    result = {
        "input_revoked": 0,
        "input_folders_revoked": 0,
        "input_folders_blocked": 0,
        "drafts_blocked": 0,
        "review_reservations_revoked": 0,
        "reviews_transferred_to_admin": 0,
        "reviews_blocked": 0,
    }
    try:
        document_repository = DocumentRepository(db)
        review_repository = ReviewRepository(db)
        if request.assignment_type == "input":
            target_folder_path = normalize_folder_path(request.folder_path)
            if not target_folder_path:
                raise HTTPException(
                    status_code=400,
                    detail="Vui lòng chọn folder cần thu hồi",
                )
            backfill_submission_metadata(db)
            groups = _get_user_pending_assignment_folders(db, target_user.id)
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
                target_user.id
            )
            result["review_reservations_revoked"] = len(pending_mappings)
            for mapping in pending_mappings:
                review_repository.delete(mapping)

            active_reviews = review_repository.active_submission_assignments(
                target_user.id
            )
            for assignment, submission in active_reviews:
                if submission.created_by_user_id == current_user["id"]:
                    result["reviews_blocked"] += 1
                    continue
                assignment.reviewer_user_id = current_user["id"]
                assignment.assigned_at = get_utc_now()
                document = _find_submission_document(db, submission)
                if document:
                    document_mapping = review_repository.get_document_assignment(
                        document.id
                    )
                    if document_mapping:
                        document_mapping.reviewer_user_id = current_user["id"]
                        document_mapping.assigned_at = get_utc_now()
                    else:
                        document_repository.add_review_assignment(
                            AssignedDocumentReviewAssignment(
                                document_id=document.id,
                                reviewer_user_id=current_user["id"],
                            )
                        )
                result["reviews_transferred_to_admin"] += 1

        db.commit()
        return {"status": "ok", **result}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể thu hồi công việc")


def _get_active_reviewer_folder_groups(db: Session) -> list[dict]:
    backfill_submission_metadata(db)
    rows = DocumentRepository(db).active_reviewer_folder_rows()

    groups: dict[str, dict] = {}
    document_group: dict[int, dict] = {}
    for document, folder_path, assignment in rows:
        group = groups.setdefault(folder_path, {
            "folder_path": folder_path,
            "documents": [],
            "input_user_ids": set(),
            "current_reviewer_user_ids": set(),
            "active_document_ids": set(),
            "active_submissions": [],
        })
        group["documents"].append(document)
        group["input_user_ids"].add(document.assigned_to_user_id)
        if assignment:
            group["current_reviewer_user_ids"].add(assignment.reviewer_user_id)
        if document.status == "pending":
            group["active_document_ids"].add(document.id)
        document_group[document.id] = group

    active_submissions = SubmissionRepository(db).list_active_reviews()
    for submission in active_submissions:
        group = document_group.get(submission.assigned_document_id)
        if group:
            group["active_document_ids"].add(submission.assigned_document_id)
            group["active_submissions"].append(submission)

    return [
        group for group in groups.values()
        if group["active_document_ids"]
    ]


@router.get("/documents/reviewer-folder-assignments")
def get_reviewer_folder_assignments(
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    users = {user.id: user.username for user in UserRepository(db).list_all()}
    groups = _get_active_reviewer_folder_groups(db)
    data = []
    for group in sorted(groups, key=lambda item: item["folder_path"].casefold()):
        reviewer_ids = sorted(group["current_reviewer_user_ids"])
        input_ids = sorted(group["input_user_ids"])
        data.append({
            "folder_path": group["folder_path"],
            "folder_name": "Thư mục gốc" if group["folder_path"] == "__ROOT__" else group["folder_path"].rstrip("/").rsplit("/", 1)[-1],
            "document_count": len(group["documents"]),
            "active_document_count": len(group["active_document_ids"]),
            "active_submission_count": len(group["active_submissions"]),
            "input_user_ids": input_ids,
            "input_usernames": [users.get(user_id, "Không xác định") for user_id in input_ids],
            "reviewer_user_ids": reviewer_ids,
            "reviewer_usernames": [users.get(user_id, "Chưa phân công") for user_id in reviewer_ids],
        })
    return {"status": "ok", "data": data, "folder_count": len(data)}


@router.put("/documents/reviewer-folders/redistribute")
def redistribute_folder_reviewers(
    request: RedistributeFolderReviewersRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    reviewer_ids = list(dict.fromkeys(request.reviewer_user_ids))
    if not reviewer_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một người kiểm tra")

    reviewer_map = UserRepository(db).user_map(reviewer_ids)
    if len(reviewer_map) != len(reviewer_ids):
        raise HTTPException(status_code=400, detail="Danh sách người kiểm tra không hợp lệ")

    groups = _get_active_reviewer_folder_groups(db)
    reviewer_order = {reviewer_id: index for index, reviewer_id in enumerate(reviewer_ids)}
    folder_counts = {reviewer_id: 0 for reviewer_id in reviewer_ids}
    assignment_plan = []
    for group in sorted(
        groups,
        key=lambda item: (
            sum(reviewer_id not in item["input_user_ids"] for reviewer_id in reviewer_ids),
            item["folder_path"].casefold(),
        ),
    ):
        eligible = [
            reviewer_id for reviewer_id in reviewer_ids
            if reviewer_id not in group["input_user_ids"]
        ]
        if not eligible:
            input_names = ", ".join(
                reviewer_map[user_id].username
                for user_id in group["input_user_ids"]
                if user_id in reviewer_map
            ) or "người nhập của folder"
            raise HTTPException(
                status_code=409,
                detail=f"Folder {group['folder_path']} không có người kiểm tra phù hợp; {input_names} không thể tự kiểm tra hồ sơ của mình",
            )
        reviewer_id = min(
            eligible,
            key=lambda user_id: (folder_counts[user_id], reviewer_order[user_id]),
        )
        folder_counts[reviewer_id] += 1
        assignment_plan.append((group, reviewer_id))

    document_updates = 0
    submission_updates = 0
    distribution = {
        reviewer_id: {
            "reviewer_user_id": reviewer_id,
            "reviewer_username": reviewer_map[reviewer_id].username,
            "folder_count": 0,
            "document_count": 0,
            "submission_count": 0,
        }
        for reviewer_id in reviewer_ids
    }
    try:
        document_repository = DocumentRepository(db)
        review_repository = ReviewRepository(db)
        for group, reviewer_id in assignment_plan:
            distribution[reviewer_id]["folder_count"] += 1
            for document in group["documents"]:
                mapping = review_repository.get_document_assignment(document.id)
                if mapping:
                    mapping.reviewer_user_id = reviewer_id
                    mapping.assigned_at = datetime.now()
                else:
                    document_repository.add_review_assignment(AssignedDocumentReviewAssignment(
                        document_id=document.id,
                        reviewer_user_id=reviewer_id,
                    ))
                document_updates += 1
                distribution[reviewer_id]["document_count"] += 1

            for submission in group["active_submissions"]:
                mapping = review_repository.get_submission_assignment(submission.id)
                if mapping:
                    mapping.reviewer_user_id = reviewer_id
                    mapping.assigned_at = datetime.now()
                else:
                    review_repository.add(SubmissionReviewAssignment(
                        submission_id=submission.id,
                        reviewer_user_id=reviewer_id,
                    ))
                submission_updates += 1
                distribution[reviewer_id]["submission_count"] += 1
        db.commit()
        return {
            "status": "ok",
            "folder_count": len(assignment_plan),
            "document_updates": document_updates,
            "submission_updates": submission_updates,
            "distribution": [distribution[reviewer_id] for reviewer_id in reviewer_ids],
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể tự phân lại folder kiểm tra")


@router.get("/documents/stats")
def get_document_stats(current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = [user for user in UserRepository(db).list_all() if user.role != "admin"]
    document_repository = DocumentRepository(db)
    document_counts = document_repository.user_document_counts()
    reservation_counts = document_repository.reviewer_reservation_counts()
    active_review_counts = ReviewRepository(db).active_review_counts()
    stats = []
    for u in users:
        counts = document_counts.get(u.id, {})
        pending = counts.get("pending", 0)
        completed = counts.get("completed", 0)
        review_reservations = reservation_counts.get(u.id, 0)
        active_reviews = active_review_counts.get(u.id, 0)
        
        stats.append({
            "user_id": u.id,
            "username": u.username,
            "pending": pending,
            "completed": completed,
            "review_pending": review_reservations + active_reviews,
        })
        
    return {
        "status": "ok", 
        "user_stats": stats
    }

@router.get("/documents/my-queue")
def get_my_queue(current_user: dict = Depends(get_input_user), db: Session = Depends(get_db)):
    backfill_submission_metadata(db)
    repository = DocumentRepository(db)
    linked_pdf_uuids = repository.linked_pdf_uuids(current_user["id"])
    docs = repository.list_input_queue(current_user["id"])
    
    # Group by template
    grouped = {}
    for d, template_name, relative_path, folder_group in docs:
        tid = d.template_id or 0
        tname = template_name or "Chưa phân loại"
        
        if tid not in grouped:
            grouped[tid] = {
                "template_id": tid,
                "template_name": tname,
                "files": []
            }
            
        grouped[tid]["files"].append({
            "name": d.original_filename,
            "url": f"/api/files/{quote(d.uuid_filename, safe='')}",
            "uuid": d.uuid_filename,
            "relative_path": relative_path,
            "folder_group": folder_group,
        })
        
    return {
        "status": "ok",
        "data": list(grouped.values()),
        "linked_pdf_uuids": sorted(linked_pdf_uuids),
    }
