from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from server.database import get_db
from server.models import Task, User, Template
from server.routers.auth import get_current_user

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

class CreateTaskRequest(BaseModel):
    user_id: int
    template_id: int
    title: str
    target_quantity: int

@router.post("")
def api_create_task(req: CreateTaskRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user["role"] != "admin":
        return {"status": "error", "message": "Access denied"}
    
    # Check if template exists
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        return {"status": "error", "message": "Template not found"}
        
    task = Task(user_id=req.user_id, template_id=req.template_id, title=req.title, target_quantity=req.target_quantity)
    db.add(task)
    db.commit()
    return {"status": "ok"}

@router.get("")
def api_get_tasks(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user["role"] == "admin":
        tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    else:
        tasks = db.query(Task).filter(Task.user_id == current_user["id"]).order_by(Task.created_at.desc()).all()
    
    res = []
    for t in tasks:
        user = db.query(User).filter(User.id == t.user_id).first()
        template = db.query(Template).filter(Template.id == t.template_id).first()
        res.append({
            "id": t.id,
            "username": user.username if user else "Unknown",
            "template_id": template.id if template else None,
            "template_name": template.name if template else "Unknown",
            "title": t.title,
            "target_quantity": t.target_quantity,
            "current_quantity": t.current_quantity,
            "status": t.status,
            "created_at": str(t.created_at)
        })
    return {"status": "ok", "data": res}
