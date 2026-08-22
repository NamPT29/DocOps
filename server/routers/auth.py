from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import hashlib
import hmac
import jwt
import os
import secrets
from typing import Literal
from datetime import datetime, timedelta, timezone
from server.database import get_db, SessionLocal
from server.models import User
from server.repositories import UserRepository
from server.services.login_rate_limit_service import LoginRateLimiter
from server.settings import settings

router = APIRouter(prefix="/api", tags=["auth"])

SECRET_KEY = settings.secret_key

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours
login_rate_limiter = LoginRateLimiter(
    settings.login_max_failures,
    settings.login_failure_window_seconds,
)

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

    user = UserRepository(db).get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return {"id": user.id, "username": user.username, "role": user.role}

def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return current_user


def _capability_profile(user: User, *, can_input: bool = False, can_review: bool = False) -> dict:
    if user.role == "admin":
        can_input = True
        can_review = True
    roles = []
    if user.role == "admin":
        roles.append("admin")
    if can_input:
        roles.append("input")
    if can_review:
        roles.append("reviewer")
    return {
        "can_input": can_input,
        "can_review": can_review,
        "roles": roles,
    }


def get_user_capability_profile(user: User, db: Session) -> dict:
    can_input, can_review = UserRepository(db).capability_flags(user.id)
    return _capability_profile(
        user,
        can_input=can_input,
        can_review=can_review,
    )


def build_user_payload(user: User, db: Session) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        **get_user_capability_profile(user, db),
    }


def get_input_user(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = UserRepository(db).get(current_user["id"])
    profile = get_user_capability_profile(user, db) if user else None
    if not profile or not profile["can_input"]:
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền nhập liệu")
    return {**current_user, **profile}


def get_reviewer_user(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = UserRepository(db).get(current_user["id"])
    profile = get_user_capability_profile(user, db) if user else None
    if not profile or not profile["can_review"]:
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền kiểm tra")
    return {**current_user, **profile}

def init_admin():
    db = SessionLocal()
    try:
        repository = UserRepository(db)
        admin = repository.get_by_username("admin")
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
            repository.add(admin)
            db.commit()
    finally:
        db.close()

class LoginRequest(BaseModel):
    username: str
    password: str = Field(max_length=128)

@router.post("/login")
def api_login(
    req: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_host = request.client.host if request.client else "unknown"
    rate_limit_key = f"{client_host}:{req.username.strip().casefold()}"
    retry_after = login_rate_limiter.retry_after(rate_limit_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Đăng nhập thất bại quá nhiều lần. Vui lòng thử lại sau.",
            headers={"Retry-After": str(retry_after)},
        )

    user = UserRepository(db).get_by_username(req.username)
    if not user or not verify_password(req.password, user.password):
        retry_after = login_rate_limiter.record_failure(rate_limit_key)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Đăng nhập thất bại quá nhiều lần. Vui lòng thử lại sau.",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")

    login_rate_limiter.reset(rate_limit_key)

    if not user.password.startswith("scrypt$"):
        user.password = hash_password(req.password)
        db.commit()
    
    user_data = build_user_payload(user, db)
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
    repository = UserRepository(db)
    if repository.get_by_username(req.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=req.username,
        password=hash_password(req.password),
        role=req.role,
    )
    repository.add(user)
    db.commit()
    return {"status": "ok", "user": build_user_payload(user, db)}

@router.delete("/users/{user_id}")
def api_delete_user(user_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    if current_user["id"] == user_id:
        raise HTTPException(status_code=409, detail="Không thể tự xóa tài khoản của chính mình")
        
    repository = UserRepository(db)
    user = repository.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
        
    try:
        repository.detach_references_and_delete(user)
        db.commit()
        return {"status": "ok"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể xóa người dùng")

class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)

@router.put("/users/{user_id}/password")
def api_change_user_password(
    user_id: int, 
    req: ChangePasswordRequest, 
    current_user: dict = Depends(get_admin_user), 
    db: Session = Depends(get_db)
):
    repository = UserRepository(db)
    user = repository.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    
    user.password = hash_password(req.new_password)
    db.commit()
    return {"status": "ok"}

@router.get("/users")
def api_get_users(current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = UserRepository(db).list_all()
    return {"status": "ok", "data": [build_user_payload(user, db) for user in users]}


@router.get("/me")
def api_get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    user = UserRepository(db).get(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return {"status": "ok", "user": build_user_payload(user, db)}
