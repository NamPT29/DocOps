import os
import json
import uuid
from typing import Literal, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from server.database import get_db
from server.models import Submission, Task, User, Template, AssignedDocument
from server.routers.auth import get_current_user, get_admin_user
from server.services.upload_service import save_validated_upload
from fastapi import HTTPException

router = APIRouter(prefix="/api", tags=["submissions"])
PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH", "uploads")


def _pdf_url(uuid_filename: str) -> str:
    return f"/api/files/{quote(uuid_filename, safe='')}"


def _resolve_document(data: dict, db: Session, owner_id: int, pending_only: bool = False):
    uuid_filename = data.get("_pdf_uuid")
    original_filename = data.get("_pdf_filename")
    if not uuid_filename and not original_filename:
        return None

    query = db.query(AssignedDocument).filter(
        AssignedDocument.assigned_to_user_id == owner_id
    )
    if uuid_filename:
        query = query.filter(AssignedDocument.uuid_filename == os.path.basename(str(uuid_filename)))
    else:
        query = query.filter(AssignedDocument.original_filename == original_filename)
    if pending_only:
        query = query.filter(AssignedDocument.status == "pending")
        return query.order_by(AssignedDocument.created_at.asc(), AssignedDocument.id.asc()).first()
    return query.order_by(AssignedDocument.created_at.desc(), AssignedDocument.id.desc()).first()


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
    elif enriched.get("_pdf_uuid"):
        uuid_filename = os.path.basename(str(enriched["_pdf_uuid"]))
        if not allow_unregistered:
            raise HTTPException(status_code=400, detail="File đính kèm không thuộc người dùng")
        enriched["_pdf_uuid"] = uuid_filename
        enriched["_pdf_url"] = _pdf_url(uuid_filename)
    elif enriched.get("_pdf_filename") and not allow_unregistered:
        raise HTTPException(status_code=400, detail="Không xác minh được file đính kèm")
    return enriched, document

class SubmitRequest(BaseModel):
    template_id: Optional[int] = None
    data: dict
    status: Optional[Literal["draft", "pending_review"]] = None

class ErrorSectionsRequest(BaseModel):
    wrong_sections: list[str]

@router.post("/submit")
def api_submit(req: SubmitRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        data_dict, document = _enrich_pdf_reference(
            req.data, db, current_user["id"], pending_only=True
        )
        sub = Submission(
            data_json=json.dumps(data_dict, ensure_ascii=False),
            created_by_user_id=current_user["id"],
            template_id=req.template_id,
            status=req.status or "draft"
        )
        db.add(sub)
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
def api_get_submissions(template_id: int = None, start_date: str = None, end_date: str = None, status: str = None, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        query = db.query(Submission)
        if current_user["role"] != "admin":
            query = query.filter(Submission.created_by_user_id == current_user["id"])
        
        if status:
            if "," in status:
                query = query.filter(Submission.status.in_(status.split(",")))
            else:
                query = query.filter(Submission.status == status)
                
        if template_id:
            query = query.filter(Submission.template_id == template_id)
            
        if start_date:
            from datetime import datetime
            query = query.filter(Submission.created_at >= datetime.fromisoformat(start_date))
            
        if end_date:
            from datetime import datetime
            query = query.filter(Submission.created_at <= datetime.fromisoformat(end_date))
            
        submissions = query.order_by(Submission.created_at.desc(), Submission.id.desc()).all()
            
        users = db.query(User).all()
        user_map = {u.id: u.username for u in users}
        
        templates = db.query(Template).all()
        template_map = {t.id: t.name for t in templates}
            
        results = []
        for sub in submissions:
            data_dict = json.loads(sub.data_json)
            ho_ten = data_dict.get("col_8", "") or data_dict.get("col_25", "") or "(Chưa có tên)"
            so_giay_to = data_dict.get("col_13", "") or data_dict.get("col_30", "") or "(Chưa có CMND)"
            template_name = template_map.get(sub.template_id, "Unknown") if sub.template_id else "Unknown"
                
            results.append({
                "id": sub.id,
                "ho_ten": ho_ten,
                "so_giay_to": so_giay_to,
                "created_at": (sub.created_at + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S") if sub.created_at else "",
                "template": template_name,
                "template_id": sub.template_id,
                "pdf_filename": data_dict.get("_pdf_filename", ""),
                "is_checked": sub.is_checked,
                "status": sub.status,
                "has_errors": sub.status == "rejected" or len(data_dict.get("_wrong_sections", [])) > 0,
                "creator_name": user_map.get(sub.created_by_user_id, "Unknown")
            })
        return {"status": "ok", "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/submissions/by-pdf")
def api_get_submission_by_pdf(filename: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        search_str = f'"{filename}"'
        query = db.query(Submission).filter(Submission.data_json.contains(search_str))
        if current_user["role"] != "admin":
            query = query.filter(Submission.created_by_user_id == current_user["id"])
        submissions = query.order_by(Submission.created_at.desc(), Submission.id.desc()).all()
        for sub in submissions:
            data_dict = json.loads(sub.data_json)
            if data_dict.get("_pdf_filename") == filename:
                data_dict, _ = _enrich_pdf_reference(
                    data_dict, db, sub.created_by_user_id, allow_unregistered=True
                )
                return {"status": "ok", "data": data_dict, "id": sub.id, "template_id": sub.template_id}
        return {"status": "ok", "data": None}
    except Exception as e:
        return {"status": "error", "message": str(e)}
@router.get("/submissions/{sub_id}")
def api_get_submission(sub_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            return {"status": "error", "message": "Không có quyền truy cập hồ sơ này."}
        data_dict, _ = _enrich_pdf_reference(
            json.loads(sub.data_json),
            db,
            sub.created_by_user_id,
            allow_unregistered=True,
        )
        return {"status": "ok", "data": data_dict, "template_id": sub.template_id, "is_checked": sub.is_checked, "submission_status": sub.status}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.put("/submissions/{sub_id}")
def api_update_submission(sub_id: int, req: SubmitRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
            
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Bạn không có quyền sửa hồ sơ này.")
        
        data_dict, document = _enrich_pdf_reference(
            req.data, db, sub.created_by_user_id
        )
        sub.data_json = json.dumps(data_dict, ensure_ascii=False)
        if req.status:
            sub.status = req.status
        if document and req.status == "pending_review":
            document.status = "completed"
            
        # Nộp lại hồ sơ sau khi báo lỗi thì xóa lỗi đi
        if req.status == "pending_review":
            if "_wrong_sections" in data_dict:
                data_dict["_wrong_sections"] = []
                sub.data_json = json.dumps(data_dict, ensure_ascii=False)
                
        db.commit()
        return {"status": "ok"}
    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.put("/submissions/{sub_id}/toggle_check")
def api_toggle_check(sub_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
        
        # In case is_checked is None (for old data before migration)
        current = sub.is_checked if sub.is_checked is not None else False
        sub.is_checked = not current
        sub.status = "approved" if sub.is_checked else "pending_review"
        
        db.commit()
        return {"status": "ok", "is_checked": sub.is_checked, "new_status": sub.status}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.put("/submissions/{sub_id}/errors")
def api_update_errors(sub_id: int, req: ErrorSectionsRequest, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
            
        data_dict = json.loads(sub.data_json)
        data_dict["_wrong_sections"] = req.wrong_sections
        sub.data_json = json.dumps(data_dict, ensure_ascii=False)
        sub.status = "rejected"
        sub.is_checked = False
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.delete("/submissions/{sub_id}")
def api_delete_submission(sub_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
        
        db.delete(sub)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.post("/submissions/{sub_id}/copy")
def api_copy_submission(sub_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        if not sub:
            return {"status": "error", "message": "Không tìm thấy hồ sơ."}
            
        if current_user["role"] != "admin" and sub.created_by_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Bạn không có quyền nhân bản hồ sơ này.")
        
        new_created_at = sub.created_at - timedelta(milliseconds=1) if sub.created_at else datetime.now()
        
        new_sub = Submission(
            data_json=sub.data_json,
            template_id=sub.template_id,
            created_at=new_created_at,
            created_by_user_id=current_user["id"]  # Mới: Người copy sẽ là người tạo
        )
        db.add(new_sub)
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
async def api_export(template_id: int, background_tasks: BackgroundTasks, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise Exception("Không tìm thấy template mẫu.")
            
        template_file_path = os.path.join("templates", template.filename)
        template_extension = os.path.splitext(template.filename)[1].lower()
        if template_extension not in {".xlsx", ".xlsm"}:
            raise Exception("Định dạng file mẫu không được hỗ trợ.")
        
        os.makedirs("scratch", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"BaoCao_{template_id}_{timestamp}{template_extension}"
        download_path = os.path.join("scratch", download_filename)
        
        from server.services.excel_service import export_submissions_to_excel
        
        submissions = db.query(Submission).filter(Submission.template_id == template_id).order_by(Submission.id).all()
        if not submissions:
            raise Exception("Không có dữ liệu hồ sơ nào trong hệ thống để xuất báo cáo cho mẫu này.")
            
        await run_in_threadpool(export_submissions_to_excel, template_file_path, submissions, download_path)
        
        def remove_file(path):
            try:
                os.remove(path)
            except:
                pass
        
        background_tasks.add_task(remove_file, download_path)
        
        return FileResponse(download_path, filename=download_filename)
    except Exception as e:
        return {"status": "error", "message": str(e)}

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

    document = db.query(AssignedDocument).filter(
        AssignedDocument.uuid_filename == safe_filename
    ).first()
    original_filename = document.original_filename if document else safe_filename

    if document:
        if current_user["role"] != "admin" and document.assigned_to_user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Không có quyền truy cập file")
    else:
        legacy_query = db.query(Submission).filter(Submission.data_json.contains(safe_filename))
        if current_user["role"] != "admin":
            legacy_query = legacy_query.filter(
                Submission.created_by_user_id == current_user["id"]
            )
        legacy_submission = legacy_query.order_by(Submission.id.desc()).first()
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

