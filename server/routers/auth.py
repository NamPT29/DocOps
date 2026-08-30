from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import hashlib
import hmac
import jwt
import logging
import os
import secrets
from typing import Literal
from datetime import timedelta
from server.database import get_db, SessionLocal, get_utc_now
from server.models import User
from server.repositories import UserRepository
from server.services.login_rate_limit_service import (
    DatabaseLoginRateLimiter,
    LoginRateLimiter,
    RateLimitBackendUnavailable,
    RedisLoginRateLimiter,
)
from server.services.personnel_statistics_service import get_personnel_statistics
from server.services.auth_session_service import (
    ConcurrentSessionLimitReached,
    active_session_counts,
    create_login_session,
    enforce_session_limit,
    get_authenticated_user,
    normalize_session_limit,
    revoke_session,
    revoke_user_sessions,
)
from server.settings import settings

router = APIRouter(prefix="/api", tags=["auth"])
logger = logging.getLogger("server.auth")

SECRET_KEY = settings.secret_key

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours
def _create_login_rate_limiter():
    if not settings.redis_url:
        return DatabaseLoginRateLimiter(
            settings.login_max_failures,
            settings.login_failure_window_seconds,
        )
    import redis

    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        health_check_interval=30,
    )
    return RedisLoginRateLimiter(
        settings.login_max_failures,
        settings.login_failure_window_seconds,
        redis_client=client,
    )


login_rate_limiter = _create_login_rate_limiter()

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

    session_id = payload.get("sid")
    user = get_authenticated_user(db, user_id=user_id, session_id=session_id)
    if not user and not UserRepository(db).get(user_id):
        raise HTTPException(status_code=401, detail="User no longer exists")
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Phiên đăng nhập không còn hiệu lực",
        )
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "session_id": session_id,
    }

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


def build_user_payload(
    user: User,
    db: Session,
    *,
    capability_flags: tuple[bool, bool] | None = None,
    active_session_count: int | None = None,
) -> dict:
    full_name = str(getattr(user, "full_name", "") or "").strip()
    if capability_flags is None:
        capability_profile = get_user_capability_profile(user, db)
    else:
        capability_profile = _capability_profile(
            user,
            can_input=capability_flags[0],
            can_review=capability_flags[1],
        )
    payload = {
        "id": user.id,
        "username": user.username,
        "full_name": full_name or user.username,
        "phone_number": getattr(user, "phone_number", None),
        "role": user.role,
        "max_concurrent_sessions": normalize_session_limit(
            getattr(user, "max_concurrent_sessions", 1)
        ),
        **capability_profile,
    }
    if active_session_count is not None:
        payload["active_session_count"] = max(0, int(active_session_count))
    return payload


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

def init_admin() -> bool:
    db = SessionLocal()
    created = False
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
                full_name="admin",
                role="admin",
            )
            repository.add(admin)
            db.commit()
            created = True
        return created
    finally:
        db.close()

class LoginRequest(BaseModel):
    username: str
    password: str = Field(max_length=128)
    browser_id: str | None = Field(default=None, max_length=128)

@router.post("/login")
def api_login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_host = request.client.host if request.client else "unknown"
    rate_limit_key = f"{client_host}:{req.username.strip().casefold()}"
    try:
        retry_after = login_rate_limiter.retry_after(rate_limit_key)
    except RateLimitBackendUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Dịch vụ bảo vệ đăng nhập tạm thời không khả dụng.",
        ) from exc
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Đăng nhập thất bại quá nhiều lần. Vui lòng thử lại sau.",
            headers={"Retry-After": str(retry_after)},
        )

    user = UserRepository(db).get_by_username(req.username)
    if not user or not verify_password(req.password, user.password):
        try:
            retry_after = login_rate_limiter.record_failure(rate_limit_key)
        except RateLimitBackendUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="Dịch vụ bảo vệ đăng nhập tạm thời không khả dụng.",
            ) from exc
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Đăng nhập thất bại quá nhiều lần. Vui lòng thử lại sau.",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")

    try:
        login_rate_limiter.reset(rate_limit_key)
    except RateLimitBackendUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Dịch vụ bảo vệ đăng nhập tạm thời không khả dụng.",
        ) from exc

    if not user.password.startswith("scrypt$"):
        user.password = hash_password(req.password)

    expire = get_utc_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    request_cookies = getattr(request, "cookies", {}) or {}
    browser_id = req.browser_id or request_cookies.get("scanToExcelBrowserId")
    try:
        login_session = create_login_session(
            db,
            user=user,
            browser_id=browser_id,
            expires_at=expire,
        )
    except ConcurrentSessionLimitReached as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Tài khoản đang sử dụng đủ {exc.limit} trình duyệt được phép. "
                "Hãy đăng xuất ở trình duyệt khác hoặc liên hệ admin để giải phóng phiên."
            ),
        ) from exc

    active_count = active_session_counts(db, {user.id})[user.id]
    user_data = build_user_payload(
        user,
        db,
        active_session_count=active_count,
    )
    to_encode = {
        "sub": str(user.id),
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "sid": login_session.session_id,
        "exp": expire,
    }
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    db.commit()
    response.set_cookie(
        key="scanToExcelBrowserId",
        value=login_session.browser_id,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
    )

    return {"status": "ok", "token": token, "user": user_data}


@router.post("/logout")
def api_logout(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revoke_session(
        db,
        user_id=current_user["id"],
        session_id=current_user.get("session_id"),
    )
    db.commit()
    return {"status": "ok"}

class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=50)
    role: Literal["admin", "user"] = "user"
    max_concurrent_sessions: int = Field(default=1, ge=1, le=20)

@router.post("/users")
def api_create_user(req: CreateUserRequest, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    repository = UserRepository(db)
    if repository.get_by_username(req.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=req.username,
        password=hash_password(req.password),
        full_name=(req.full_name or "").strip() or req.username,
        phone_number=(req.phone_number or "").strip() or None,
        role=req.role,
        max_concurrent_sessions=req.max_concurrent_sessions,
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

    blockers = repository.deletion_blockers(user_id)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail=(
                "Không thể xóa tài khoản vì vẫn còn dữ liệu lịch sử: "
                f"{', '.join(blockers)}."
            ),
        )

    try:
        repository.detach_references_and_delete(user)
        db.commit()
        return {"status": "ok"}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa tài khoản vì vẫn còn dữ liệu đang tham chiếu.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error while deleting user", extra={"user_id": user_id})
        raise HTTPException(status_code=500, detail="Không thể xóa người dùng") from exc

class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UpdateUserProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=50)
    max_concurrent_sessions: int | None = Field(default=None, ge=1, le=20)

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
    revoke_user_sessions(
        db,
        user_id=user.id,
        except_session_id=(
            current_user.get("session_id")
            if current_user["id"] == user.id
            else None
        ),
    )
    db.commit()
    return {"status": "ok"}


@router.patch("/users/{user_id}")
def api_update_user_profile(
    user_id: int,
    req: UpdateUserProfileRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    repository = UserRepository(db)
    user = repository.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")

    user.full_name = (req.full_name or "").strip() or user.username
    user.phone_number = (req.phone_number or "").strip() or None
    revoked_sessions = 0
    if req.max_concurrent_sessions is not None:
        user.max_concurrent_sessions = req.max_concurrent_sessions
        revoked_sessions = enforce_session_limit(
            db,
            user_id=user.id,
            limit=req.max_concurrent_sessions,
        )
    db.commit()
    active_count = active_session_counts(db, {user.id})[user.id]
    return {
        "status": "ok",
        "user": build_user_payload(
            user,
            db,
            active_session_count=active_count,
        ),
        "revoked_sessions": revoked_sessions,
    }

@router.get("/users")
def api_get_users(current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    repository = UserRepository(db)
    users = repository.list_all()
    user_ids = {user.id for user in users}
    capability_flags = repository.capability_flags_map(user_ids)
    session_counts = active_session_counts(db, user_ids)
    return {
        "status": "ok",
        "data": [
            build_user_payload(
                user,
                db,
                capability_flags=capability_flags[user.id],
                active_session_count=session_counts[user.id],
            )
            for user in users
        ],
    }


@router.delete("/users/{user_id}/sessions")
def api_revoke_user_sessions(
    user_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = UserRepository(db).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    keep_session_id = (
        current_user.get("session_id") if current_user["id"] == user_id else None
    )
    revoked = revoke_user_sessions(
        db,
        user_id=user_id,
        except_session_id=keep_session_id,
    )
    db.commit()
    return {"status": "ok", "revoked_sessions": revoked}


@router.get("/users/personnel-stats")
def api_get_personnel_statistics(
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": get_personnel_statistics(db)}


@router.get("/me")
def api_get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    user = UserRepository(db).get(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return {"status": "ok", "user": build_user_payload(user, db)}
