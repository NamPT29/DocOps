from server.models import Notification, NotificationRecipient, User
from server.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    def list_for_user(self, user_id: int, limit: int = 100):
        return (
            self.session.query(Notification, NotificationRecipient, User.username)
            .join(NotificationRecipient, NotificationRecipient.notification_id == Notification.id)
            .join(User, User.id == Notification.created_by_user_id)
            .filter(NotificationRecipient.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .all()
        )

    def recipient_users(self, user_ids: list[int]) -> list[User]:
        if not user_ids:
            return []
        return self.session.query(User).filter(User.id.in_(user_ids)).all()

    def unread_for_user(self, user_id: int):
        return self.session.query(NotificationRecipient).filter(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.read_at.is_(None),
        )

    def recipient_for_user(self, notification_id: int, user_id: int):
        return self.session.query(NotificationRecipient).filter(
            NotificationRecipient.notification_id == notification_id,
            NotificationRecipient.user_id == user_id,
        ).first()
