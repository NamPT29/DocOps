from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
import secrets
from server.database import get_db, SessionLocal
from server.models import User, AssignedDocument

router = APIRouter(prefix="/api", tags=["auth"])

# Simple in-memory session store
SESSIONS = {}

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    if token not in SESSIONS:
        raise HTTPException(status_code=401, detail="Invalid token")
    return SESSIONS[token]

def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return current_user

def init_admin():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(username="admin", password="123", role="admin")
            db.add(admin)
            db.commit()
    finally:
        db.close()

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def api_login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username, User.password == req.password).first()
    if not user:
        return {"status": "error", "message": "Sai tên đăng nhập hoặc mật khẩu"}
    token = secrets.token_hex(16)
    SESSIONS[token] = {"id": user.id, "username": user.username, "role": user.role}
    return {"status": "ok", "token": token, "user": SESSIONS[token]}

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"

@router.post("/users")
def api_create_user(req: CreateUserRequest, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        return {"status": "error", "message": "Username already exists"}
    user = User(username=req.username, password=req.password, role=req.role)
    db.add(user)
    db.commit()
    return {"status": "ok"}

@router.delete("/users/{user_id}")
def api_delete_user(user_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    if current_user["id"] == user_id:
        return {"status": "error", "message": "Không thể tự xóa tài khoản của chính mình"}
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"status": "error", "message": "Không tìm thấy người dùng"}
        
    # Trả các tài liệu chưa làm xong (pending) của nhân viên này về lại kho chung
    pending_docs = db.query(AssignedDocument).filter(
        AssignedDocument.assigned_to_user_id == user_id,
        AssignedDocument.status == "pending"
    ).all()
    
    for doc in pending_docs:
        doc.assigned_to_user_id = None
        
    db.delete(user)
    db.commit()
    return {"status": "ok"}

@router.get("/users")
def api_get_users(current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"status": "ok", "data": [{"id": u.id, "username": u.username, "role": u.role} for u in users]}
