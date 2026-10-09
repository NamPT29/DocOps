"""Chi trả – chốt kỳ (P2, revision 0019_payroll_periods).

QC-01: kết quả đã tính phải lưu kèm giá trị tham số tại thời điểm tính. Chốt kỳ = tính như bảng tạm tính P1 rồi
LƯU từng dòng (người, mã, sản lượng, đơn giá, hệ số, thành tiền, tên người lúc chốt) và tham số (đơn giá,
`bad_paper_factor`, phiên bản QC). Excel của kỳ đã chốt xuất ĐÚNG số đã lưu; đổi đơn giá/hệ số sau đó không đổi file.
- Khoảng ngày chồng kỳ đã chốt: 409 `period_overlap`. Mã có sản lượng mà thiếu đơn giá: 409 `missing_rate`.
- Xóa kỳ: Admin, chỉ kỳ mới nhất (ngày bắt đầu lớn nhất), không thì 409 `not_latest_period`.
"""
import json
from decimal import Decimal

from server.models_payroll import PayrollLine, PayrollPeriod
from server.repositories.payroll_repository import PayrollRepository
from server.repositories.timesheet_repository import TimesheetRepository
from server.services.payroll_service import (
    WORKS,
    _error,
    _plain,
    _project_or_404,
    compute_payroll,
    parse_period,
    payroll_workbook,
)


def _iso_utc(value):
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


def _serialize(period, *, lines_count=0, created_by=None) -> dict:
    params = json.loads(period.params_json or "{}")
    return {
        "id": period.id,
        "from": period.date_from.isoformat(),
        "to": period.date_to.isoformat(),
        "total": _plain(Decimal(period.total_amount or 0)),
        "params": params,
        "lines": lines_count,
        "created_at": _iso_utc(period.created_at),
        "created_by": created_by,
    }


def create_period(db, *, project_id: int, date_from: str, date_to: str, actor: dict) -> dict:
    repository = PayrollRepository(db)
    _project_or_404(repository, project_id)
    start, end = parse_period(date_from, date_to)
    overlap = repository.overlapping_periods(project_id, start, end)
    if overlap:
        other = overlap[0]
        raise _error(409, "period_overlap",
                     f"Khoảng ngày chồng kỳ đã chốt {other.date_from.isoformat()} – {other.date_to.isoformat()}")
    result = compute_payroll(db, project_id=project_id, date_from=start, date_to=end)
    if result["warnings"]:
        raise _error(409, "missing_rate", "Chưa chốt được: " + "; ".join(result["warnings"]))
    period = PayrollPeriod(
        project_id=project_id, date_from=start, date_to=end,
        params_json=json.dumps(result["params"], ensure_ascii=False),
        total_amount=Decimal(result["total"]), created_by_user_id=actor["id"],
    )
    repository.add(period)
    repository.flush()
    for line in result["lines"]:
        repository.add(PayrollLine(
            period_id=period.id, user_id=line["user_id"], person_name=line["name"], work_code=line["work_code"],
            quantity=line["quantity"], unit_price=Decimal(str(line["unit_price"])), factor=Decimal(str(line["factor"])),
            amount=Decimal(str(line["amount"])),
        ))
    db.commit()
    return _serialize(period, lines_count=len(result["lines"]), created_by=actor.get("full_name") or actor.get("username"))


def list_periods(db, *, project_id: int) -> list[dict]:
    repository = PayrollRepository(db)
    _project_or_404(repository, project_id)
    periods = repository.periods(project_id)
    counts = repository.line_counts([period.id for period in periods])
    names = TimesheetRepository(db).display_names({period.created_by_user_id for period in periods})
    return [
        _serialize(period, lines_count=counts.get(period.id, 0), created_by=names.get(period.created_by_user_id))
        for period in reversed(periods)
    ]


def _stored_result(project, period, lines) -> dict:
    """Dựng lại kết quả để xuất Excel từ ĐÚNG số đã lưu, không tính lại."""
    rows = []
    people = {}
    for line in lines:
        work = line.work_code.rsplit("-", 1)[0]
        row = {
            "user_id": line.user_id, "name": line.person_name, "work_code": line.work_code, "work": WORKS[work][0],
            "unit": WORKS[work][1], "quantity": line.quantity, "unit_price": _plain(Decimal(line.unit_price)),
            "factor": _plain(Decimal(line.factor)), "amount": _plain(Decimal(line.amount)),
        }
        rows.append(row)
        person = people.setdefault((line.user_id, line.person_name),
                                   {"user_id": line.user_id, "name": line.person_name, "amount": 0, "complete": True})
        person["amount"] += row["amount"]
    return {
        "project": {"id": project.id, "name": project.name},
        "period": {"from": period.date_from.isoformat(), "to": period.date_to.isoformat()},
        "params": json.loads(period.params_json),
        "lines": rows,
        "people": list(people.values()),
        "total": _plain(Decimal(period.total_amount)),
        "warnings": [],
    }


def period_workbook(db, *, project_id: int, period_id: int) -> tuple[bytes, dict]:
    repository = PayrollRepository(db)
    project = _project_or_404(repository, project_id)
    period = repository.period(project_id, period_id)
    if period is None:
        raise _error(404, "period_not_found", "Không tìm thấy kỳ chi trả")
    result = _stored_result(project, period, repository.period_lines(period.id))
    return payroll_workbook(result, title=f"Bảng chi trả đã chốt (kỳ #{period.id})"), result


def delete_period(db, *, project_id: int, period_id: int) -> dict:
    repository = PayrollRepository(db)
    _project_or_404(repository, project_id)
    period = repository.period(project_id, period_id)
    if period is None:
        raise _error(404, "period_not_found", "Không tìm thấy kỳ chi trả")
    latest = repository.periods(project_id)[-1]
    if latest.id != period.id:
        raise _error(409, "not_latest_period", "Chỉ xóa được kỳ đã chốt mới nhất")
    repository.delete_period(period)
    db.commit()
    return {"deleted": period_id}
