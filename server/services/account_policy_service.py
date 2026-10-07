"""Account types and CTV expiry (BA mục 3; FR-AUT-02, FR-AUT-03).

Pure functions: no database access. ``users.role`` stays the authorization flag
('admin' | 'user'); ``users.account_type`` splits non-admins into Hành chính
('staff') and cộng tác viên ('ctv').
"""

from datetime import date, datetime, timedelta, timezone

from server.services import workflow_engine as engine

ADMIN = "admin"
STAFF = "staff"
CTV = "ctv"
ACCOUNT_TYPE_LABELS = {ADMIN: "Admin", STAFF: "Hành chính", CTV: "CTV"}

# Vietnam has no daylight saving time, so a fixed offset needs no tz database.
VIETNAM_TZ = timezone(timedelta(hours=7))

# Pipeline stages a CTV may be assigned to (BA 3.3).
CTV_STAGE_KEYS = tuple(
    stage.key for stage in engine.STAGE_CATALOG if CTV in stage.allowed_roles
)

CTV_REVIEWER_ERROR = "CTV không được làm người kiểm tra (chỉ Admin và Hành chính)."

# Shown to the locked person; the reason stays in the admin-only lock log.
LOCKED_MESSAGE = "Tài khoản đã bị khóa. Liên hệ quản trị viên."


def vietnam_today() -> date:
    return datetime.now(VIETNAM_TZ).date()


def account_type_of(user) -> str:
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    if role == "admin":
        return ADMIN
    acct = user.get("account_type") if isinstance(user, dict) else getattr(user, "account_type", None)
    return CTV if acct == CTV else STAFF


def role_labels(account_types) -> str:
    return ", ".join(ACCOUNT_TYPE_LABELS[item] for item in account_types)


def is_expired(user, today: date | None = None) -> bool:
    """A CTV may work through the whole ``expires_on`` day (Vietnam time)."""
    if account_type_of(user) != CTV:
        return False
    expires_on = getattr(user, "expires_on", None)
    if expires_on is None:
        return True  # a CTV without an expiry date is never valid
    return (today or vietnam_today()) > expires_on


def expired_message(user) -> str:
    expires_on = getattr(user, "expires_on", None)
    if expires_on is None:
        return "Tài khoản CTV chưa có ngày hết hạn. Liên hệ quản trị viên."
    return (
        f"Tài khoản CTV đã hết hạn sử dụng từ ngày {expires_on:%d/%m/%Y}. "
        "Liên hệ quản trị viên để gia hạn."
    )


def is_locked(user) -> bool:
    return bool(getattr(user, "is_locked", False))


def access_block_message(user, today: date | None = None) -> str | None:
    """Why ``user`` may not sign in or keep a session, or ``None`` if allowed."""
    if is_locked(user):
        return LOCKED_MESSAGE
    if is_expired(user, today):
        return expired_message(user)
    return None


def validate_expiry(account_type, expires_on, *, previous=None, today: date | None = None):
    """Return the ``expires_on`` to store, or raise ``ValueError``.

    Only CTV accounts keep a date. A new date may not lie in the past; an
    unchanged ``previous`` date is accepted so other fields stay editable.
    """
    if account_type != CTV:
        return None
    if expires_on is None:
        raise ValueError("Tài khoản CTV phải có ngày hết hạn.")
    if expires_on != previous and expires_on < (today or vietnam_today()):
        raise ValueError("Ngày hết hạn không được ở quá khứ.")
    return expires_on


def ctv_user_ids(users) -> list[int]:
    return sorted(user.id for user in users if account_type_of(user) == CTV)


def describe_ctv_conflicts(rows) -> list[str]:
    """Format ``(project_name, kind, stage_key)`` rows from the repository."""
    descriptions = []
    for project_name, kind, stage_key in rows:
        if kind == "reviewer":
            descriptions.append(f"Người kiểm tra – dự án {project_name}")
        else:
            label = engine.STAGES_BY_KEY[stage_key].label if stage_key in engine.STAGES_BY_KEY else stage_key
            descriptions.append(f"Bước {label} – dự án {project_name}")
    return descriptions
