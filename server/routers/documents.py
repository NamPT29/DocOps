from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
import os
import uuid
import shutil
from server.database import get_db
from server.routers.auth import get_current_user, get_admin_user
from server.models import AssignedDocument, User, Template
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
    
    uploaded_count = 0
    assigned_stats = {uid: 0 for uid in user_id_list}
    
    try:
        for i, file in enumerate(files):
            if not file.filename:
                continue
                
            uuid_name = str(uuid.uuid4()) + "_" + file.filename
            filepath = os.path.join(PDF_STORAGE_PATH, uuid_name)
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            # Round-robin assignment
            assignee_id = user_id_list[i % len(user_id_list)]
            
            doc = AssignedDocument(
                original_filename=file.filename,
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
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"Lỗi trong quá trình phân công: {str(e)}"}

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
            "url": f"/uploads/{d.uuid_filename}",
            "uuid": d.uuid_filename
        })
        
    return {"status": "ok", "data": list(grouped.values())}
