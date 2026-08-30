import secrets
from datetime import datetime

from sqlalchemy import func

from server.database import get_utc_now
from server.models import User, UserLoginSession


MAX_CONFIGURED_SESSIONS = 20


class ConcurrentSessionLimitReached(Exception):
    def __init__(self, *, active_count: int, limit: int):
        super().__init__("Concurrent login session limit reached")
        self.active_count = active_count
        self.limit = limit


def normalize_session_limit(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(parsed, MAX_CONFIGURED_SESSIONS))


def normalize_browser_id(value: object) -> str:
    browser_id = value.strip() if isinstance(value, str) else ""
    return browser_id[:128] or secrets.token_urlsafe(24)


def create_login_session(
    db,
    *,
    user: User,
    browser_id: object,
    expires_at: datetime,
) -> UserLoginSession:
    """Create/replace one browser session while serializing logins per user."""
    locked_user = (
        db.query(User)
        .filter(User.id == user.id)
        .with_for_update()
        .one()
    )
    now = get_utc_now()
    normalized_browser_id = normalize_browser_id(browser_id)

    db.query(UserLoginSession).filter(
        UserLoginSession.user_id == locked_user.id,
        UserLoginSession.expires_at <= now,
    ).delete(synchronize_session=False)

    existing = db.query(UserLoginSession).filter(
        UserLoginSession.user_id == locked_user.id,
        UserLoginSession.browser_id == normalized_browser_id,
    ).first()
    active_count = db.query(func.count(UserLoginSession.session_id)).filter(
        UserLoginSession.user_id == locked_user.id,
        UserLoginSession.expires_at > now,
    ).scalar() or 0
    limit = normalize_session_limit(locked_user.max_concurrent_sessions)
    if existing is None and active_count >= limit:
        raise ConcurrentSessionLimitReached(active_count=active_count, limit=limit)

    if existing is not None:
        db.delete(existing)
        db.flush()

    login_session = UserLoginSession(
        session_id=secrets.token_urlsafe(32),
        user_id=locked_user.id,
        browser_id=normalized_browser_id,
        expires_at=expires_at,
    )
    db.add(login_session)
    db.flush()
    return login_session


def get_authenticated_user(db, *, user_id: int, session_id: object) -> User | None:
    normalized_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not normalized_session_id:
        return None
    return (
        db.query(User)
        .join(UserLoginSession, UserLoginSession.user_id == User.id)
        .filter(
            User.id == user_id,
            UserLoginSession.session_id == normalized_session_id,
            UserLoginSession.expires_at > get_utc_now(),
        )
        .first()
    )


def active_session_counts(db, user_ids: set[int] | list[int]) -> dict[int, int]:
    normalized_ids = {int(user_id) for user_id in user_ids}
    counts = {user_id: 0 for user_id in normalized_ids}
    if not normalized_ids:
        return counts
    rows = (
        db.query(UserLoginSession.user_id, func.count(UserLoginSession.session_id))
        .filter(
            UserLoginSession.user_id.in_(normalized_ids),
            UserLoginSession.expires_at > get_utc_now(),
        )
        .group_by(UserLoginSession.user_id)
        .all()
    )
    for user_id, count in rows:
        counts[int(user_id)] = int(count)
    return counts


def enforce_session_limit(db, *, user_id: int, limit: int) -> int:
    """Keep the newest sessions and revoke older sessions beyond the new limit."""
    normalized_limit = normalize_session_limit(limit)
    active_sessions = (
        db.query(UserLoginSession)
        .filter(
            UserLoginSession.user_id == user_id,
            UserLoginSession.expires_at > get_utc_now(),
        )
        .order_by(UserLoginSession.created_at.desc(), UserLoginSession.session_id.desc())
        .all()
    )
    revoked = 0
    for login_session in active_sessions[normalized_limit:]:
        db.delete(login_session)
        revoked += 1
    return revoked


def revoke_user_sessions(db, *, user_id: int, except_session_id: str | None = None) -> int:
    query = db.query(UserLoginSession).filter(UserLoginSession.user_id == user_id)
    if except_session_id:
        query = query.filter(UserLoginSession.session_id != except_session_id)
    return query.delete(synchronize_session=False)


def revoke_session(db, *, user_id: int, session_id: object) -> bool:
    normalized_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not normalized_session_id:
        return False
    deleted = db.query(UserLoginSession).filter(
        UserLoginSession.user_id == user_id,
        UserLoginSession.session_id == normalized_session_id,
    ).delete(synchronize_session=False)
    return bool(deleted)
