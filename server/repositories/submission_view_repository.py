from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from server.models import SubmissionViewPresence, User


VIEWER_PRESENCE_TIMEOUT = timedelta(seconds=90)


class SubmissionViewRepository:
    def __init__(self, session: Session):
        self.session = session

    def claim(self, submission_id: int, user_id: int) -> SubmissionViewPresence:
        now = datetime.utcnow()
        presence = self.session.get(SubmissionViewPresence, submission_id)
        if presence is None:
            presence = SubmissionViewPresence(
                submission_id=submission_id,
                viewer_user_id=user_id,
                last_seen_at=now,
            )
            self.session.add(presence)
            self.session.flush()
            return presence

        if (
            presence.viewer_user_id == user_id
            or now - presence.last_seen_at > VIEWER_PRESENCE_TIMEOUT
        ):
            presence.viewer_user_id = user_id
            presence.last_seen_at = now
            self.session.flush()
        return presence

    def release(self, submission_id: int, user_id: int) -> bool:
        presence = self.session.get(SubmissionViewPresence, submission_id)
        if not presence or presence.viewer_user_id != user_id:
            return False
        self.session.delete(presence)
        self.session.flush()
        return True

    def active_map(self, submission_ids: list[int] | set[int]) -> dict[int, dict]:
        if not submission_ids:
            return {}
        cutoff = datetime.utcnow() - VIEWER_PRESENCE_TIMEOUT
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
