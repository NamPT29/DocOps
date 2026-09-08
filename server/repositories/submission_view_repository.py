import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from server.models import Submission, SubmissionViewPresence, User
from server.database import get_utc_now


VIEWER_PRESENCE_TIMEOUT = timedelta(seconds=90)
VIEWER_PRESENCE_TIMEOUT_SECONDS = int(VIEWER_PRESENCE_TIMEOUT.total_seconds())


class SubmissionViewRepository:
    def __init__(self, session: Session):
        self.session = session

    def claim(self, submission_id: int, user_id: int) -> SubmissionViewPresence:
        now = get_utc_now()
        # Lock the parent row too so two first-time claims cannot both observe
        # an absent presence row and race to insert the same primary key.
        self.session.query(Submission.id).filter(
            Submission.id == submission_id,
        ).with_for_update().one_or_none()
        presence = self._get_for_update(submission_id)
        if presence is None:
            presence = SubmissionViewPresence(
                submission_id=submission_id,
                viewer_user_id=user_id,
                lease_token=secrets.token_urlsafe(32),
                last_seen_at=now,
            )
            self.session.add(presence)
            self.session.flush()
            return presence

        is_stale = now - presence.last_seen_at > VIEWER_PRESENCE_TIMEOUT
        if presence.viewer_user_id == user_id or is_stale:
            if (
                presence.viewer_user_id != user_id
                or is_stale
                or not presence.lease_token
            ):
                presence.lease_token = secrets.token_urlsafe(32)
            presence.viewer_user_id = user_id
            presence.last_seen_at = now
            self.session.flush()
        return presence

    def refresh_lease(
        self,
        submission_id: int,
        user_id: int,
        lease_token: object,
    ) -> tuple[str, SubmissionViewPresence | None]:
        """Validate the active owner/token and renew the 90-second lease."""
        presence = self._get_for_update(submission_id)
        now = get_utc_now()
        token = lease_token.strip() if isinstance(lease_token, str) else ""
        if not token:
            return "missing", presence
        if (
            presence is None
            or now - presence.last_seen_at > VIEWER_PRESENCE_TIMEOUT
        ):
            return "expired", presence
        if presence.viewer_user_id != user_id:
            return "conflict", presence
        if not presence.lease_token or not secrets.compare_digest(
            presence.lease_token,
            token,
        ):
            return "invalid", presence
        presence.last_seen_at = now
        self.session.flush()
        return "ok", presence

    def active_presence(
        self,
        submission_id: int,
    ) -> SubmissionViewPresence | None:
        presence = self._get_for_update(submission_id)
        if presence is None:
            return None
        if get_utc_now() - presence.last_seen_at > VIEWER_PRESENCE_TIMEOUT:
            self.session.delete(presence)
            self.session.flush()
            return None
        return presence

    def _get_for_update(self, submission_id: int) -> SubmissionViewPresence | None:
        return self.session.query(SubmissionViewPresence).filter(
            SubmissionViewPresence.submission_id == submission_id,
        ).with_for_update().one_or_none()

    def release(self, submission_id: int, user_id: int) -> bool:
        presence = self.session.get(SubmissionViewPresence, submission_id)
        if not presence or presence.viewer_user_id != user_id:
            return False
        self.session.delete(presence)
        self.session.flush()
        return True

    def release_owned(self, submission_ids: list[int] | set[int], user_id: int) -> int:
        if not submission_ids:
            return 0
        deleted = self.session.query(SubmissionViewPresence).filter(
            SubmissionViewPresence.submission_id.in_(submission_ids),
            SubmissionViewPresence.viewer_user_id == user_id,
        ).delete(synchronize_session=False)
        self.session.flush()
        return int(deleted or 0)

    def active_map(self, submission_ids: list[int] | set[int]) -> dict[int, dict]:
        if not submission_ids:
            return {}
        cutoff = get_utc_now() - VIEWER_PRESENCE_TIMEOUT
        rows = self.session.query(
            SubmissionViewPresence.submission_id,
            SubmissionViewPresence.viewer_user_id,
            User.username,
        ).outerjoin(
            User,
            User.id == SubmissionViewPresence.viewer_user_id,
        ).filter(
            SubmissionViewPresence.submission_id.in_(submission_ids),
            SubmissionViewPresence.last_seen_at >= cutoff,
        ).all()
        return {
            submission_id: {
                'user_id': viewer_user_id,
                'username': username or 'Người dùng khác',
            }
            for submission_id, viewer_user_id, username in rows
        }
