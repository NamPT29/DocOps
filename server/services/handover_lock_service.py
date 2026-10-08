"""Khóa sửa hồ sơ sau bàn giao (K1, revision 0017_project_handover_lock).

Admin khóa sau khi đã có lần đóng gói bàn giao xong. Khi khóa, mọi thao tác SỬA hồ sơ nhập của dự án
trả 423 `project_handed_over`; xem, xuất Excel, kế hoạch, đối soát vẫn được. Hồ sơ thuộc dự án nào:
submission.assigned_document_id -> file nhập liệu của dự án. Hồ sơ không gắn file dự án: không khóa.
Mở khóa: Admin, bắt buộc lý do, ghi nhật ký audit.
"""
import logging

from fastapi import HTTPException

from server.database import get_utc_now
from server.repositories.handover_lock_repository import HandoverLockRepository
from server.services.handover_package_service import read_job

audit_logger = logging.getLogger("server.audit.handover_lock")

LOCKED_MESSAGE = "Dự án đã bàn giao, không sửa được hồ sơ. Admin mở khóa nếu cần sửa."
NOTE_MAX_LENGTH = 1000


def locked_error() -> HTTPException:
    return HTTPException(status_code=423, detail={"code": "project_handed_over", "message": LOCKED_MESSAGE})


def locked_document_ids(db, document_ids) -> set[int]:
    return HandoverLockRepository(db).locked_document_ids(set(document_ids))


def ensure_document_editable(db, document_id) -> None:
    if document_id is not None and locked_document_ids(db, {document_id}):
        raise locked_error()


def ensure_submission_editable(db, submission) -> None:
    ensure_document_editable(db, getattr(submission, "assigned_document_id", None))


def ensure_submissions_editable(db, submissions) -> None:
    """Một hồ sơ bị khóa thì chặn cả lệnh (gọi trước khi ghi bất kỳ thứ gì)."""
    if locked_document_ids(db, {submission.assigned_document_id for submission in submissions}):
        raise locked_error()


def ensure_project_editable(db, project_id: int) -> None:
    project = HandoverLockRepository(db).get(project_id)
    if project is not None and project.handover_locked_at is not None:
        raise locked_error()


def iso_utc(value) -> str | None:
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


def lock_state(project) -> dict:
    return {
        "project_id": project.id,
        "handover_locked_at": iso_utc(project.handover_locked_at),
        "handover_locked_by_user_id": project.handover_locked_by_user_id,
        "handover_lock_note": project.handover_lock_note,
    }


def _project_or_404(repository, project_id):
    project = repository.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Không tìm thấy dự án"})
    return project


def _clean_text(value, field_label) -> str:
    text = str(value or "").strip()
    if len(text) > NOTE_MAX_LENGTH:
        raise HTTPException(status_code=400, detail={"code": "text_too_long", "message": f"{field_label} tối đa {NOTE_MAX_LENGTH} ký tự"})
    return text


def lock_project(db, *, project_id: int, note, actor: dict) -> dict:
    repository = HandoverLockRepository(db)
    project = _project_or_404(repository, project_id)
    if project.handover_locked_at is not None:
        raise HTTPException(status_code=409, detail={"code": "already_locked", "message": "Dự án đã khóa bàn giao"})
    job = read_job(project_id)
    if not job or job.get("state") != "done":
        raise HTTPException(status_code=409, detail={
            "code": "package_required",
            "message": "Chưa có lần đóng gói bàn giao nào xong. Hãy Đóng gói bàn giao trước khi khóa.",
        })
    project.handover_locked_at = get_utc_now()
    project.handover_locked_by_user_id = actor["id"]
    project.handover_lock_note = _clean_text(note, "Ghi chú") or None
    db.commit()
    audit_logger.info("Khóa bàn giao dự án %s bởi %s", project.id, actor.get("username"))
    return lock_state(project)


def unlock_project(db, *, project_id: int, reason, actor: dict) -> dict:
    repository = HandoverLockRepository(db)
    project = _project_or_404(repository, project_id)
    reason_text = _clean_text(reason, "Lý do")
    if not reason_text:
        raise HTTPException(status_code=400, detail={"code": "reason_required", "message": "Nhập lý do mở khóa"})
    if project.handover_locked_at is None:
        raise HTTPException(status_code=409, detail={"code": "not_locked", "message": "Dự án chưa khóa bàn giao"})
    project.handover_locked_at = None
    project.handover_locked_by_user_id = None
    project.handover_lock_note = None
    db.commit()
    audit_logger.info("Mở khóa bàn giao dự án %s bởi %s, lý do: %s", project.id, actor.get("username"), reason_text)
    return lock_state(project)
