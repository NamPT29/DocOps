from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from server.database import get_db
from server.models import Task
from server.routers.auth import get_current_user, get_admin_user
from server.repositories import TaskRepository, TemplateRepository

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

class CreateTaskRequest(BaseModel):
    user_id: int
    template_id: int
    title: str
    target_quantity: int

@router.post("")
def api_create_task(req: CreateTaskRequest, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    
    # Check if template exists
    template = TemplateRepository(db).get(req.template_id)
    if not template:
        return {"status": "error", "message": "Template not found"}
        
    task = Task(user_id=req.user_id, template_id=req.template_id, title=req.title, target_quantity=req.target_quantity)
    TaskRepository(db).add(task)
    db.commit()
    return {"status": "ok"}

@router.get("")
def api_get_tasks(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = TaskRepository(db).list_with_names(
        None if current_user["role"] == "admin" else current_user["id"]
    )
    
    res = []
    for t, username, template_name in rows:
        res.append({
            "id": t.id,
            "username": username or "Unknown",
            "template_id": t.template_id if template_name is not None else None,
            "template_name": template_name or "Unknown",
            "title": t.title,
            "target_quantity": t.target_quantity,
            "current_quantity": t.current_quantity,
            "status": t.status,
            "created_at": str(t.created_at)
        })
    return {"status": "ok", "data": res}
