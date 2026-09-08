from datetime import datetime

from sqlalchemy import and_, func, or_

from server.models import User, UserLoginSession
from server.repositories.base import BaseRepository


class AuthSessionRepository(BaseRepository[UserLoginSession]):
    model = UserLoginSession

    @staticmethod
    def _active_filters(
        now: datetime,
        idle_cutoff: datetime,
        close_cutoff: datetime,
    ) -> tuple:
        return (
            UserLoginSession.expires_at > now,
            UserLoginSession.last_activity_at > idle_cutoff,
            or_(
                UserLoginSession.close_requested_at.is_(None),
                UserLoginSession.close_requested_at > close_cutoff,
            ),
        )

    def lock_user(self, user_id: int) -> User:
        return (
            self.session.query(User)
            .filter(User.id == user_id)
            .with_for_update()
            .one()
        )

    def delete_inactive(
        self,
        user_id: int,
        *,
        now: datetime,
        idle_cutoff: datetime,
        close_cutoff: datetime,
    ) -> int:
        return self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id,
            or_(
                UserLoginSession.expires_at <= now,
                UserLoginSession.last_activity_at <= idle_cutoff,
                and_(
                    UserLoginSession.close_requested_at.is_not(None),
                    UserLoginSession.close_requested_at <= close_cutoff,
                ),
            ),
        ).delete(synchronize_session=False)

    def get_by_browser(self, user_id: int, browser_id: str) -> UserLoginSession | None:
        return self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id,
            UserLoginSession.browser_id == browser_id,
        ).first()

    def get_by_session(self, user_id: int, session_id: str) -> UserLoginSession | None:
        return self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id,
            UserLoginSession.session_id == session_id,
        ).first()

    def get_user_session(
        self,
        user_id: int,
        session_id: str,
    ) -> tuple[User, UserLoginSession] | None:
        return (
            self.session.query(User, UserLoginSession)
            .join(UserLoginSession, UserLoginSession.user_id == User.id)
            .filter(
                User.id == user_id,
                UserLoginSession.session_id == session_id,
            )
            .first()
        )

    def active_count(
        self,
        user_id: int,
        *,
        now: datetime,
        idle_cutoff: datetime,
        close_cutoff: datetime,
    ) -> int:
        return int(
            self.session.query(func.count(UserLoginSession.session_id)).filter(
                UserLoginSession.user_id == user_id,
                *self._active_filters(now, idle_cutoff, close_cutoff),
            ).scalar()
            or 0
        )

    def active_counts(
        self,
        user_ids: set[int],
        *,
        now: datetime,
        idle_cutoff: datetime,
        close_cutoff: datetime,
    ) -> dict[int, int]:
        rows = (
            self.session.query(
                UserLoginSession.user_id,
                func.count(UserLoginSession.session_id),
            )
            .filter(
                UserLoginSession.user_id.in_(user_ids),
                *self._active_filters(now, idle_cutoff, close_cutoff),
            )
            .group_by(UserLoginSession.user_id)
            .all()
        )
        return {int(user_id): int(count) for user_id, count in rows}

    def list_active(
        self,
        user_id: int,
        *,
        now: datetime,
        idle_cutoff: datetime,
        close_cutoff: datetime,
    ) -> list[UserLoginSession]:
        return (
            self.session.query(UserLoginSession)
            .filter(
                UserLoginSession.user_id == user_id,
                *self._active_filters(now, idle_cutoff, close_cutoff),
            )
            .order_by(
                UserLoginSession.created_at.desc(),
                UserLoginSession.session_id.desc(),
            )
            .all()
        )

    def mark_closing(
        self,
        user_id: int,
        session_id: str,
        close_requested_at: datetime,
    ) -> int:
        return self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id,
            UserLoginSession.session_id == session_id,
        ).update(
            {UserLoginSession.close_requested_at: close_requested_at},
            synchronize_session=False,
        )

    def revoke_user_sessions(
        self,
        user_id: int,
        except_session_id: str | None = None,
    ) -> int:
        query = self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id
        )
        if except_session_id:
            query = query.filter(UserLoginSession.session_id != except_session_id)
        return query.delete(synchronize_session=False)

    def revoke_session(self, user_id: int, session_id: str) -> int:
        return self.session.query(UserLoginSession).filter(
            UserLoginSession.user_id == user_id,
            UserLoginSession.session_id == session_id,
        ).delete(synchronize_session=False)
