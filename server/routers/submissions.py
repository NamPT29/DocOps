import os
import json
import uuid
import shutil
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from server.database import get_db
from server.models import Submission, Task, User, Template
from server.routers.auth import get_current_user, get_admin_user
from fastapi import HTTPException

router = APIRouter(prefix="/api", tags=["submissions"])

class SubmitRequest(BaseModel):
    template_id: Optional[int] = None
    data: dict

class ErrorSectionsRequest(BaseModel):
    wrong_sections: list[str]

@router.post("/submit")
def api_submit(req: SubmitRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = Submission(
            data_json=json.dumps(req.data, ensure_ascii=False),
            created_by_user_id=current_user["id"],
            template_id=req.template_id
        )
        db.add(sub)
        # Update document status if linked
        pdf_filename = req.data.get('_pdf_filename')
        if pdf_filename:
            from server.models import AssignedDocument
            doc = db.query(AssignedDocument).filter(
                AssignedDocument.original_filename == pdf_filename,
                AssignedDocument.assigned_to_user_id == current_user["id"],
                AssignedDocument.status == "pending"
            ).first()
            if doc:
                doc.status = "completed"

        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@router.get("/submissions")
def api_get_submissions(template_id: int = None, start_date: str = None, end_date: str = None, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        query = db.query(Submission)
        if current_user["role"] != "admin":
            query = query.filter(Submission.created_by_user_id == current_user["id"])
        
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
                "has_errors": len(data_dict.get("_wrong_sections", [])) > 0,
                "creator_name": user_map.get(sub.created_by_user_id, "Unknown")
            })
        return {"status": "ok", "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/submissions/by-pdf")
def api_get_submission_by_pdf(filename: str, db: Session = Depends(get_db)):
    try:
        search_str = f'"{filename}"'
        submissions = db.query(Submission).filter(Submission.data_json.contains(search_str)).order_by(Submission.created_at.desc(), Submission.id.desc()).all()
        for sub in submissions:
            data_dict = json.loads(sub.data_json)
            if data_dict.get("_pdf_filename") == filename:
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
        return {"status": "ok", "data": json.loads(sub.data_json), "template_id": sub.template_id, "is_checked": sub.is_checked}
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
        
        sub.data_json = json.dumps(req.data, ensure_ascii=False)
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
        db.commit()
        return {"status": "ok", "is_checked": sub.is_checked}
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

@router.get("/export")
def api_export(template_id: int, background_tasks: BackgroundTasks, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        import openpyxl
        
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise Exception("Không tìm thấy template mẫu.")
            
        template_file_path = os.path.join("templates", template.filename)
        
        os.makedirs("scratch", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"BaoCao_{template_id}_{timestamp}.xlsx"
        download_path = os.path.join("scratch", download_filename)
        
        from server.services.excel_service import export_submissions_to_excel
        
        submissions = db.query(Submission).filter(Submission.template_id == template_id).order_by(Submission.id).all()
        if not submissions:
            raise Exception("Không có dữ liệu hồ sơ nào trong hệ thống để xuất báo cáo cho mẫu này.")
            
        export_submissions_to_excel(template_file_path, submissions, download_path)
        
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
async def api_upload_pdf(file: UploadFile = File(...)):
    try:
        os.makedirs("uploads", exist_ok=True)
        # Sử dụng nguyên bản tên gốc
        new_filename = file.filename
        filepath = os.path.join("uploads", new_filename)
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"status": "ok", "url": f"/uploads/{new_filename}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

