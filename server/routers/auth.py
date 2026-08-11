from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import hashlib
import hmac
import jwt
import logging
import os
import secrets
from typing import Literal
from datetime import datetime, timedelta, timezone
from server.database import get_db, SessionLocal
from server.models import User, AssignedDocument, Submission, Task

router = APIRouter(prefix="/api", tags=["auth"])

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY:
    if len(SECRET_KEY.encode("utf-8")) < 32:
        raise RuntimeError("SECRET_KEY phải có ít nhất 32 byte.")
else:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning(
        "SECRET_KEY chưa được cấu hình; token sẽ hết hiệu lực khi server khởi động lại."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Mật khẩu không được để trống.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_password: str) -> bool:
    if not isinstance(password, str) or not isinstance(stored_password, str):
        return False
    if not stored_password.startswith("scrypt$"):
        return hmac.compare_digest(password, stored_password)

    try:
        _, n, r, p, salt_hex, digest_hex = stored_password.split("$", 5)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (TypeError, ValueError):
        return False


def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        raw_user_id = payload.get("sub", payload.get("id"))
        user_id = int(raw_user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return {"id": user.id, "username": user.username, "role": user.role}

def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return current_user

def init_admin():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            initial_password = os.getenv("INITIAL_ADMIN_PASSWORD")
            if not initial_password or len(initial_password) < 12:
                raise RuntimeError(
                    "Hãy cấu hình INITIAL_ADMIN_PASSWORD với ít nhất 12 ký tự "
                    "trước lần khởi động đầu tiên."
                )
            admin = User(
                username="admin",
                password=hash_password(initial_password),
                role="admin",
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()

class LoginRequest(BaseModel):
    username: str
    password: str = Field(max_length=128)

@router.post("/login")
def api_login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password):
        return {"status": "error", "message": "Sai tên đăng nhập hoặc mật khẩu"}

    if not user.password.startswith("scrypt$"):
        user.password = hash_password(req.password)
        db.commit()
    
    user_data = {"id": user.id, "username": user.username, "role": user.role}
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub": str(user.id),
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "exp": expire,
    }
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"status": "ok", "token": token, "user": user_data}

class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"

@router.post("/users")
def api_create_user(req: CreateUserRequest, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        return {"status": "error", "message": "Username already exists"}
    user = User(
        username=req.username,
        password=hash_password(req.password),
        role=req.role,
    )
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
        
    try:
        db.query(AssignedDocument).filter(
            AssignedDocument.assigned_to_user_id == user_id
        ).update({AssignedDocument.assigned_to_user_id: None}, synchronize_session=False)
        db.query(Submission).filter(
            Submission.created_by_user_id == user_id
        ).update({Submission.created_by_user_id: None}, synchronize_session=False)
        db.query(Task).filter(Task.user_id == user_id).update(
            {Task.user_id: None}, synchronize_session=False
        )
        db.delete(user)
        db.commit()
        return {"status": "ok"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể xóa người dùng")

@router.get("/users")
def api_get_users(current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"status": "ok", "data": [{"id": u.id, "username": u.username, "role": u.role} for u in users]}
