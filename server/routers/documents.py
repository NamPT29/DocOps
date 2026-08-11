from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
import os
import uuid
from urllib.parse import quote
from server.database import get_db
from server.routers.auth import get_current_user, get_admin_user
from server.models import AssignedDocument, User, Template
from server.services.upload_service import save_validated_upload
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["documents"])

@router.post("/documents/upload-assign")
async def upload_and_assign_documents(
    template_id: int = Form(...),
    user_ids: str = Form(...),
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
        
    from dotenv import load_dotenv
    load_dotenv()
    PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH", "uploads")
    os.makedirs(PDF_STORAGE_PATH, exist_ok=True)

    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Biểu mẫu không tồn tại")
    users = db.query(User).filter(User.id.in_(user_id_list)).all()
    valid_user_ids = {user.id for user in users}
    if valid_user_ids != set(user_id_list):
        raise HTTPException(status_code=400, detail="Danh sách nhân viên không hợp lệ")
    
    uploaded_count = 0
    assigned_stats = {uid: 0 for uid in user_id_list}
    created_paths = []
    
    try:
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
            db.add(doc)
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

@router.get("/documents/stats")
def get_document_stats(current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role == "user").all()
    stats = []
    for u in users:
        pending = db.query(AssignedDocument).filter(
            AssignedDocument.assigned_to_user_id == u.id,
            AssignedDocument.status == "pending"
        ).count()
        completed = db.query(AssignedDocument).filter(
            AssignedDocument.assigned_to_user_id == u.id,
            AssignedDocument.status == "completed"
        ).count()
        
        stats.append({
            "user_id": u.id,
            "username": u.username,
            "pending": pending,
            "completed": completed
        })
        
    return {
        "status": "ok", 
        "user_stats": stats
    }

@router.get("/documents/my-queue")
def get_my_queue(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    docs = db.query(AssignedDocument, Template.name).outerjoin(
        Template, AssignedDocument.template_id == Template.id
    ).filter(
        AssignedDocument.assigned_to_user_id == current_user["id"],
        AssignedDocument.status == "pending"
    ).order_by(AssignedDocument.template_id, AssignedDocument.created_at).all()
    
    # Group by template
    grouped = {}
    for d, template_name in docs:
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
            "uuid": d.uuid_filename
        })
        
    return {"status": "ok", "data": list(grouped.values())}
