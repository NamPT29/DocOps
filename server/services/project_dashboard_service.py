"""Bảng tiến độ dự án (D1): số liệu cho PM theo sổ BM-TKDA (tài liệu phân tích mẫu, mục 6). Chỉ đọc.

- stages: mỗi bước đang bật (thứ tự STAGE_CATALOG) đếm hộp theo trạng thái và khối lượng đã xong.
- documents: văn bản (file nhập liệu đang dùng, trừ bìa) đã nhập / hoàn thành / còn lại.
- daily: 14 ngày gần nhất theo giờ Việt Nam; entered = lần nộp kiểm tra đầu tiên (baseline chất lượng,
  như sheet Chấm công), approved = lần "review_confirmed" đầu tiên, scan_pages = trang A4 quy đổi của gói S
  `done` xong trong ngày.
- forecast: trung bình 7 ngày gần nhất; ngày dự kiến xong = hôm nay + ceil(còn lại / duyệt trung bình).
- people: số liệu 7 ngày gần nhất của từng người.
"""

from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException

from server.repositories.project_dashboard_repository import ProjectDashboardRepository
from server.repositories.timesheet_repository import TimesheetRepository
from server.services import workflow_engine as engine
from server.services.account_policy_service import VIETNAM_TZ
from server.services.normalization_plan_service import is_cover_file
from server.services.timesheet_service import vietnam_date
from server.services.workflow_service import case_status_matrix

DAILY_DAYS = 14
AVERAGE_DAYS = 7

# Đơn vị khối lượng của từng bước; khối lượng tính trong _volume_done.
STAGE_UNITS = {
    "arrangement": "hồ sơ",
    "scan": "trang A4",
    "scan_qc": "trang A4",
    "data_entry": "văn bản",
    "entry_qc": "văn bản",
    "normalization": "hồ sơ",
    "handover": "hồ sơ",
}

# Định mức QC-10 (QC-01). Giả định trừ SC-A4-1 (lấy từ sổ mẫu).
NORMS = (
    {"code": "CL", "label": "Chỉnh lý, lập mục lục", "unit": "hồ sơ", "per_8h": 40, "source": "Giả định"},
    {"code": "SC-A4-1", "label": "Scan A4 giấy thường", "unit": "trang", "per_8h": 3500, "source": "Mẫu"},
    {"code": "SC-A4-2", "label": "Scan A4 giấy xấu", "unit": "trang", "per_8h": 2000, "source": "Giả định"},
    {"code": "CS-1", "label": "Check scan vòng 1", "unit": "trang", "per_8h": 6000, "source": "Giả định"},
    {"code": "NL-1", "label": "Nhập liệu tài liệu thường", "unit": "văn bản", "per_8h": 250, "source": "Giả định"},
    {"code": "NL-2", "label": "Nhập liệu tài liệu xấu", "unit": "văn bản", "per_8h": 150, "source": "Giả định"},
    {"code": "CN-1", "label": "Check nhập liệu vòng 1", "unit": "văn bản", "per_8h": 600, "source": "Giả định"},
    {"code": "CH", "label": "Chuẩn hóa, đóng gói", "unit": "hồ sơ", "per_8h": 200, "source": "Giả định"},
)


def _percent(part, total):
    return round(part * 100 / total, 1) if total else 0.0


def _document_progress(repository, project_id):
    """Văn bản của dự án: lần lưu mới nhất từng file nhập liệu đang dùng (trừ bìa)."""
    document_ids = {
        document_id
        for document_id, filename in repository.active_assets(project_id)
        if document_id is not None and not is_cover_file(filename or "")
    }
    latest = repository.latest_submissions_by_document(document_ids)
    entered = [submission for submission in latest.values() if submission.status != "draft"]
    completed = sum(1 for submission in entered if submission.status == "completed")
    return {
        "total": len(document_ids),
        "entered": len(entered),
        "completed": completed,
        "remaining": len(document_ids) - completed,
    }, entered


def _volume_done(stage_key, done_case_ids, dossiers, scan_a4, documents):
    if stage_key in ("arrangement", "normalization", "handover"):
        return sum(dossiers.get(case_id, 0) for case_id in done_case_ids)
    if stage_key in ("scan", "scan_qc"):
        return sum(scan_a4.get(case_id, 0) for case_id in done_case_ids)
    if stage_key == "data_entry":
        return documents["entered"]
    return documents["completed"]


def _stages(enabled, cases, matrix, dossiers, scan_a4, documents):
    stages = []
    for stage in engine.STAGE_CATALOG:
        if stage.key not in enabled:
            continue
        counts = {status: 0 for status in engine.STATUSES}
        done_case_ids = []
        for case in cases:
            status = matrix[case.id][stage.key]["status"]
            counts[status] += 1
            if status == engine.DONE:
                done_case_ids.append(case.id)
        stages.append({
            "key": stage.key,
            "label": stage.label,
            "boxes_total": len(cases),
            "boxes_done": counts[engine.DONE],
            "boxes_in_progress": counts[engine.IN_PROGRESS],
            "boxes_rejected": counts[engine.REJECTED],
            "boxes_pending": counts[engine.PENDING],
            "percent_done": _percent(counts[engine.DONE], len(cases)),
            "unit": STAGE_UNITS[stage.key],
            "volume_done": _volume_done(stage.key, done_case_ids, dossiers, scan_a4, documents),
        })
    return stages


def build_dashboard(db, project_id: int, now_utc: datetime) -> dict:
    """now_utc: giờ UTC không kèm múi giờ (như get_utc_now), truyền vào để test cố định."""
    repository = ProjectDashboardRepository(db)
    project = repository.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Không tìm thấy dự án"})

    today = vietnam_date(now_utc)
    days = [today - timedelta(days=offset) for offset in range(DAILY_DAYS - 1, -1, -1)]
    recent = set(days[-AVERAGE_DAYS:])
    window_start_utc = (
        datetime.combine(days[0], time.min, tzinfo=VIETNAM_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    )

    enabled, cases, matrix = case_status_matrix(db, project_id=project_id)
    documents, entered_submissions = _document_progress(repository, project_id)
    stages = _stages(
        enabled, cases, matrix,
        repository.dossier_counts_by_case(project_id),
        repository.latest_done_scan_a4_by_case(project_id),
        documents,
    )

    daily = {day: {"entered": 0, "approved": 0, "scan_pages": 0} for day in days}
    people = {}

    def person(user_id):
        return people.setdefault(user_id, {"entered": 0, "approved": 0, "scan_pages": 0})

    timesheet = TimesheetRepository(db)
    submission_ids = [submission.id for submission in entered_submissions]
    assessments = timesheet.assessments_by_submission(submission_ids)
    reviews = timesheet.first_review_confirmations(submission_ids)
    for submission in entered_submissions:
        input_user_id, submitted_at = assessments.get(submission.id, (None, None))
        work_date = vietnam_date(submitted_at or submission.created_at)
        if work_date in daily:
            daily[work_date]["entered"] += 1
        user_id = input_user_id or submission.created_by_user_id
        if work_date in recent and user_id is not None:
            person(user_id)["entered"] += 1
        review = reviews.get(submission.id)
        if review is not None:
            reviewer_user_id, reviewed_at = review
            review_date = vietnam_date(reviewed_at)
            if review_date in daily:
                daily[review_date]["approved"] += 1
            if review_date in recent and reviewer_user_id is not None:
                person(reviewer_user_id)["approved"] += 1

    for scanned_by_user_id, a4, finished_at in repository.done_scan_packages_finished_since(project_id, window_start_utc):
        scan_date = vietnam_date(finished_at)
        if scan_date in daily:
            daily[scan_date]["scan_pages"] += a4 or 0
        if scan_date in recent and scanned_by_user_id is not None:
            person(scanned_by_user_id)["scan_pages"] += a4 or 0

    last_week = [daily[day] for day in days[-AVERAGE_DAYS:]]
    entered_7d = sum(item["entered"] for item in last_week)
    approved_7d = sum(item["approved"] for item in last_week)
    finish_date = None
    if approved_7d > 0:
        # Số nguyên: ceil(còn lại / (duyệt 7 ngày / 7)), tránh sai số số thực (3 / (1/7) = 21,000…04).
        days_left = -(-documents["remaining"] * AVERAGE_DAYS // approved_7d)
        finish_date = (today + timedelta(days=days_left)).isoformat()

    names = timesheet.display_names(set(people))
    people_rows = [
        {"user_id": user_id, "name": names.get(user_id) or f"Tài khoản #{user_id}", **values}
        for user_id, values in people.items()
        if any(values.values())
    ]
    people_rows.sort(key=lambda row: (row["name"].casefold(), row["user_id"]))

    return {
        "project": {"id": project.id, "name": project.name},
        "generated_at": now_utc.replace(microsecond=0).isoformat() + "Z",
        "stages": stages,
        "documents": documents,
        "daily": [{"date": day.isoformat(), **daily[day]} for day in days],
        "forecast": {
            "avg_entered_per_day_7d": round(entered_7d / AVERAGE_DAYS, 1),
            "avg_approved_per_day_7d": round(approved_7d / AVERAGE_DAYS, 1),
            "estimated_finish_date": finish_date,
        },
        "people": people_rows,
        "norms": [dict(norm) for norm in NORMS],
    }
