from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
import os
import uuid
import shutil
from server.database import get_db
from server.routers.auth import get_current_user
from server.models import AssignedDocument, User
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["documents"])

class AssignRequest(BaseModel):
    user_id: int
    count: int

@router.post("/documents/batch-upload")
async def batch_upload_documents(files: List[UploadFile] = File(...), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
        
    os.makedirs("uploads", exist_ok=True)
    uploaded_count = 0
    
    try:
        for file in files:
            if not file.filename:
                continue
                
            uuid_name = file.filename
            filepath = os.path.join("uploads", uuid_name)
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            doc = AssignedDocument(
                original_filename=file.filename,
                uuid_filename=uuid_name,
                assigned_to_user_id=None,
                status="pending"
            )
            db.add(doc)
            uploaded_count += 1
            
        db.commit()
        return {"status": "ok", "message": f"Successfully uploaded {uploaded_count} documents to the pool."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"Có lỗi xảy ra (có thể do trùng tên file gốc): {str(e)}"}

@router.get("/documents/pool")
def get_document_pool(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
        
    unassigned_count = db.query(AssignedDocument).filter(AssignedDocument.assigned_to_user_id == None).count()
    
    # Get assignment stats per user
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
        "unassigned_count": unassigned_count,
        "user_stats": stats
    }

@router.post("/documents/assign")
def assign_documents(req: AssignRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
        
    if req.count <= 0:
        return {"status": "error", "message": "Số lượng phải lớn hơn 0"}
        
    # Check total available documents first
    available_count = db.query(AssignedDocument).filter(AssignedDocument.assigned_to_user_id == None).count()
    if available_count == 0:
        return {"status": "error", "message": "Kho tài liệu đã hết, không còn tài liệu trống."}
        
    if req.count > available_count:
        return {"status": "error", "message": f"Số lượng yêu cầu ({req.count}) lớn hơn số tài liệu hiện có trong kho ({available_count})."}
        
    # Get unassigned documents
    unassigned_docs = db.query(AssignedDocument).filter(AssignedDocument.assigned_to_user_id == None).limit(req.count).all()
        
    assigned = 0
    for doc in unassigned_docs:
        doc.assigned_to_user_id = req.user_id
        assigned += 1
        
    db.commit()
    return {"status": "ok", "message": f"Đã giao thành công {assigned} tài liệu."}

@router.get("/documents/my-queue")
def get_my_queue(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    docs = db.query(AssignedDocument).filter(
        AssignedDocument.assigned_to_user_id == current_user["id"],
        AssignedDocument.status == "pending"
    ).order_by(AssignedDocument.created_at).all()
    
    queue = []
    for d in docs:
        queue.append({
            "name": d.original_filename,
            "url": f"/uploads/{d.uuid_filename}",
            "uuid": d.uuid_filename
        })
        
    return {"status": "ok", "data": queue}
