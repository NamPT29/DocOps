from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import User
from server.routers.notifications import (
    CreateNotificationRequest,
    api_create_notification,
    api_get_notifications,
    api_mark_all_notifications_read,
    api_mark_notification_read,
)


def test_admin_can_send_notification_to_selected_users(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'notifications.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        admin = User(username="admin", password="hash", role="admin")
        first = User(username="first", password="hash", role="user")
        second = User(username="second", password="hash", role="user")
        db.add_all([admin, first, second])
        db.commit()

        result = api_create_notification(
            CreateNotificationRequest(
                title="Lịch làm việc",
                message="Vui lòng hoàn thành trước thứ Sáu.",
                recipient_user_ids=[first.id, first.id, second.id],
            ),
            current_user={"id": admin.id, "role": "admin"},
            db=db,
        )
        assert result == {"status": "ok", "id": 1, "recipient_count": 2}

        first_notifications = api_get_notifications({"id": first.id}, db)
        assert first_notifications["unread_count"] == 1
        assert first_notifications["data"][0]["title"] == "Lịch làm việc"

        api_mark_notification_read(1, {"id": first.id}, db)
        assert api_get_notifications({"id": first.id}, db)["unread_count"] == 0
        assert api_get_notifications({"id": second.id}, db)["unread_count"] == 1

        api_mark_all_notifications_read({"id": second.id}, db)
        assert api_get_notifications({"id": second.id}, db)["unread_count"] == 0
    finally:
        db.close()
        engine.dispose()
