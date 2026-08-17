from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.database import get_db, get_utc_now
from server.models import Notification, NotificationRecipient
from server.repositories import NotificationRepository
from server.routers.auth import get_admin_user, get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class CreateNotificationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=5000)
    recipient_user_ids: list[int] = Field(min_length=1, max_length=500)


def _notification_payload(notification, recipient, creator_username=None):
    return {
        "id": notification.id,
        "title": notification.title,
        "message": notification.message,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "read_at": recipient.read_at.isoformat() if recipient.read_at else None,
        "created_by": creator_username,
    }


@router.get("")
def api_get_notifications(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = NotificationRepository(db).list_for_user(current_user["id"])
    data = [_notification_payload(notification, recipient, username) for notification, recipient, username in rows]
    return {"status": "ok", "data": data, "unread_count": sum(1 for item in data if not item["read_at"])}


@router.post("")
def api_create_notification(
    req: CreateNotificationRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    recipient_ids = sorted(set(req.recipient_user_ids))
    users = NotificationRepository(db).recipient_users(recipient_ids)
    found_ids = {user.id for user in users}
    missing = [user_id for user_id in recipient_ids if user_id not in found_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy người dùng: {', '.join(map(str, missing))}")

    notification = Notification(
        title=req.title.strip(),
        message=req.message.strip(),
        created_by_user_id=current_user["id"],
    )
    if not notification.title or not notification.message:
        raise HTTPException(status_code=400, detail="Tiêu đề và nội dung không được để trống")
    db.add(notification)
    db.flush()
    db.add_all([
        NotificationRecipient(notification_id=notification.id, user_id=user_id)
        for user_id in recipient_ids
    ])
    db.commit()
    return {"status": "ok", "id": notification.id, "recipient_count": len(recipient_ids)}


@router.post("/{notification_id}/read")
def api_mark_notification_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipient = NotificationRepository(db).recipient_for_user(notification_id, current_user["id"])
    if not recipient:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo")
    if recipient.read_at is None:
        recipient.read_at = get_utc_now()
        db.commit()
    return {"status": "ok"}


@router.post("/read-all")
def api_mark_all_notifications_read(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = NotificationRepository(db).unread_for_user(current_user["id"]).update(
        {NotificationRecipient.read_at: get_utc_now()}, synchronize_session=False
    )
    db.commit()
    return {"status": "ok", "updated": updated}
