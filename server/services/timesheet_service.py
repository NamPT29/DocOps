"""Sheet "Chấm công theo ngày" trong file Excel xuất.

Mỗi dòng: một người trong một ngày (giờ Việt Nam), số hàng đã nhập và số hàng đã duyệt,
chỉ tính trên đúng các báo cáo có trong file xuất. Cách đếm giống bảng Thống kê nhân sự:
- Đã nhập: người nhập = input_user_id của baseline chất lượng, không có thì người tạo hồ sơ;
  ngày = lúc tạo baseline (lần nộp kiểm tra đầu tiên), không có thì created_at của hồ sơ.
- Đã duyệt: lần "review_confirmed" đầu tiên của hồ sơ; người = reviewer_user_id, ngày = lúc duyệt.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from server.repositories.timesheet_repository import TimesheetRepository
from server.services.account_policy_service import VIETNAM_TZ


@dataclass(frozen=True)
class TimesheetRow:
    work_date: date
    name: str
    entered: int
    reviewed: int


def vietnam_date(value: datetime | None) -> date | None:
    """Ngày theo giờ Việt Nam của một thời điểm lưu UTC không kèm múi giờ."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(VIETNAM_TZ).date()


def daily_timesheet_rows(db, submissions) -> list[TimesheetRow]:
    submissions = list(submissions)
    if not submissions:
        return []
    repository = TimesheetRepository(db)
    submission_ids = [submission.id for submission in submissions]
    assessments = repository.assessments_by_submission(submission_ids)
    reviews = repository.first_review_confirmations(submission_ids)

    entered: dict[tuple[date, int], int] = {}
    reviewed: dict[tuple[date, int], int] = {}
    for submission in submissions:
        input_user_id, submitted_at = assessments.get(submission.id, (None, None))
        input_user_id = input_user_id or submission.created_by_user_id
        work_date = vietnam_date(submitted_at or submission.created_at)
        if input_user_id is not None and work_date is not None:
            key = (work_date, input_user_id)
            entered[key] = entered.get(key, 0) + 1

        review = reviews.get(submission.id)
        if review is not None:
            reviewer_user_id, reviewed_at = review
            review_date = vietnam_date(reviewed_at)
            if reviewer_user_id is not None and review_date is not None:
                key = (review_date, reviewer_user_id)
                reviewed[key] = reviewed.get(key, 0) + 1

    keys = set(entered) | set(reviewed)
    names = repository.display_names({user_id for _work_date, user_id in keys})

    def name_of(user_id):
        return names.get(user_id) or f"Tài khoản #{user_id}"

    ordered = sorted(
        keys,
        key=lambda key: (key[0], name_of(key[1]).casefold(), key[1]),
    )
    return [
        TimesheetRow(
            work_date=work_date,
            name=name_of(user_id),
            entered=entered.get((work_date, user_id), 0),
            reviewed=reviewed.get((work_date, user_id), 0),
        )
        for work_date, user_id in ordered
    ]
