import secrets
from datetime import datetime, timedelta

from server.database import get_utc_now
from server.models import User, UserLoginSession
from server.repositories.auth_session_repository import AuthSessionRepository
from server.settings import settings


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


def _idle_cutoff(now: datetime, idle_timeout_minutes: int | None) -> datetime:
    minutes = idle_timeout_minutes or settings.session_idle_timeout_minutes
    return now - timedelta(minutes=max(1, int(minutes)))


def _close_cutoff(now: datetime, close_grace_seconds: int | None) -> datetime:
    seconds = close_grace_seconds or settings.session_close_grace_seconds
    return now - timedelta(seconds=max(1, int(seconds)))


def create_login_session(
    db,
    *,
    user: User,
    browser_id: object,
    expires_at: datetime,
    idle_timeout_minutes: int | None = None,
    close_grace_seconds: int | None = None,
) -> UserLoginSession:
    """Create/replace one browser session while serializing logins per user."""
    repository = AuthSessionRepository(db)
    locked_user = repository.lock_user(user.id)
    now = get_utc_now()
    normalized_browser_id = normalize_browser_id(browser_id)

    idle_cutoff = _idle_cutoff(now, idle_timeout_minutes)
    close_cutoff = _close_cutoff(now, close_grace_seconds)
    repository.delete_inactive(
        locked_user.id,
        now=now,
        idle_cutoff=idle_cutoff,
        close_cutoff=close_cutoff,
    )

    existing = repository.get_by_browser(locked_user.id, normalized_browser_id)
    active_count = repository.active_count(
        locked_user.id,
        now=now,
        idle_cutoff=idle_cutoff,
        close_cutoff=close_cutoff,
    )
    limit = normalize_session_limit(locked_user.max_concurrent_sessions)
    if existing is None and active_count >= limit:
        raise ConcurrentSessionLimitReached(active_count=active_count, limit=limit)

    if existing is not None:
        repository.delete(existing)
        repository.flush()

    login_session = UserLoginSession(
        session_id=secrets.token_urlsafe(32),
        user_id=locked_user.id,
        browser_id=normalized_browser_id,
        last_activity_at=now,
        expires_at=expires_at,
    )
    repository.add(login_session)
    repository.flush()
    return login_session


def get_authenticated_user(
    db,
    *,
    user_id: int,
    session_id: object,
    idle_timeout_minutes: int | None = None,
    close_grace_seconds: int | None = None,
) -> User | None:
    normalized_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not normalized_session_id:
        return None
    repository = AuthSessionRepository(db)
    now = get_utc_now()
    user_session = repository.get_user_session(user_id, normalized_session_id)
    if user_session is None:
        return None
    user, login_session = user_session
    is_active = (
        login_session.expires_at > now
        and login_session.last_activity_at > _idle_cutoff(
            now,
            idle_timeout_minutes,
        )
        and (
            login_session.close_requested_at is None
            or login_session.close_requested_at > _close_cutoff(
                now,
                close_grace_seconds,
            )
        )
    )
    if not is_active:
        repository.delete(login_session)
        db.commit()
        return None
    return user


def active_session_counts(
    db,
    user_ids: set[int] | list[int],
    *,
    idle_timeout_minutes: int | None = None,
    close_grace_seconds: int | None = None,
) -> dict[int, int]:
    normalized_ids = {int(user_id) for user_id in user_ids}
    counts = {user_id: 0 for user_id in normalized_ids}
    if not normalized_ids:
        return counts
    now = get_utc_now()
    counts.update(
        AuthSessionRepository(db).active_counts(
            normalized_ids,
            now=now,
            idle_cutoff=_idle_cutoff(now, idle_timeout_minutes),
            close_cutoff=_close_cutoff(now, close_grace_seconds),
        )
    )
    return counts


def enforce_session_limit(
    db,
    *,
    user_id: int,
    limit: int,
    idle_timeout_minutes: int | None = None,
    close_grace_seconds: int | None = None,
) -> int:
    """Keep the newest sessions and revoke older sessions beyond the new limit."""
    normalized_limit = normalize_session_limit(limit)
    now = get_utc_now()
    repository = AuthSessionRepository(db)
    active_sessions = repository.list_active(
        user_id,
        now=now,
        idle_cutoff=_idle_cutoff(now, idle_timeout_minutes),
        close_cutoff=_close_cutoff(now, close_grace_seconds),
    )
    revoked = 0
    for login_session in active_sessions[normalized_limit:]:
        repository.delete(login_session)
        revoked += 1
    return revoked


def touch_session_activity(
    db,
    *,
    user_id: int,
    session_id: object,
    user_active: bool,
    touch_interval_seconds: int | None = None,
) -> bool:
    normalized_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not normalized_session_id:
        return False
    login_session = AuthSessionRepository(db).get_by_session(
        user_id,
        normalized_session_id,
    )
    if login_session is None:
        return False

    changed = login_session.close_requested_at is not None
    login_session.close_requested_at = None
    if user_active:
        now = get_utc_now()
        interval = touch_interval_seconds or settings.session_activity_touch_interval_seconds
        if login_session.last_activity_at <= now - timedelta(seconds=max(1, int(interval))):
            login_session.last_activity_at = now
            changed = True
    return changed


def mark_session_closing(db, *, user_id: int, session_id: object) -> bool:
    normalized_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not normalized_session_id:
        return False
    updated = AuthSessionRepository(db).mark_closing(
        user_id,
        normalized_session_id,
        get_utc_now(),
    )
    return bool(updated)


def revoke_user_sessions(db, *, user_id: int, except_session_id: str | None = None) -> int:
    return AuthSessionRepository(db).revoke_user_sessions(
        user_id,
        except_session_id,
    )


def revoke_session(db, *, user_id: int, session_id: object) -> bool:
    normalized_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not normalized_session_id:
        return False
    deleted = AuthSessionRepository(db).revoke_session(
        user_id,
        normalized_session_id,
    )
    return bool(deleted)
