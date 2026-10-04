"""Project policy (FR-PRJ-01/03) with defaults from QC-01.

A NULL setting means "follow the current QC-01 default": when QC-01 gets a new
version every project that did not set its own value follows it, while values
an admin set for one project stay (QC-01 v0.1.1, "Cách áp dụng giá trị mặc
định"). Results computed from these settings must store the values they used.
"""

import re
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from server.models import ProjectPolicy
from server.repositories.project_policy_repository import ProjectPolicyRepository

QC_VERSION = "QC-01 v0.1.1"

EXPORT_PROFILES = {
    "NN-SIP": "Khối Nhà nước (NN-SIP)",
    "DANG-HD40": "Khối Đảng (DANG-HD40)",
}

# Single source of the defaults; keep in sync with docs/standards/QC-01.
QC01_DEFAULTS = {
    "error_threshold_percent": Decimal("5"),
    "sample_rate_percent": Decimal("30"),
    "box_deadline_days": 2,
    "organ_code": None,
    "file_notation": None,
    "export_profile": "NN-SIP",
    "bad_paper_factor": Decimal("1.3"),
    "overtime_factor": Decimal("1.2"),
    "sunday_factor": Decimal("1.4"),
}

_ORGAN_CODE = re.compile(r"^[A-Za-z0-9._-]{1,50}$")
_FILE_NOTATION = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


@dataclass(frozen=True)
class PolicyField:
    key: str
    label: str
    qc: str
    kind: str  # percent | days | factor | organ_code | file_notation | export_profile


POLICY_FIELDS = (
    PolicyField("error_threshold_percent", "Ngưỡng lỗi của hộp (BR-07)", "QC-08", "percent"),
    PolicyField("sample_rate_percent", "Tỷ lệ lấy mẫu check vòng 2", "QC-08", "percent"),
    PolicyField("box_deadline_days", "Hạn xử lý hộp", "QC-08", "days"),
    PolicyField("organ_code", "Mã cơ quan", "QC-02/03", "organ_code"),
    PolicyField("file_notation", "Ký hiệu hồ sơ", "QC-03", "file_notation"),
    PolicyField("export_profile", "Chuẩn xuất", "QC-01", "export_profile"),
    PolicyField("bad_paper_factor", "Hệ số giấy xấu", "QC-07", "factor"),
    PolicyField("overtime_factor", "Hệ số ngoài giờ (OT)", "QC-09", "factor"),
    PolicyField("sunday_factor", "Hệ số Chủ nhật", "QC-09", "factor"),
)
POLICY_KEYS = tuple(field.key for field in POLICY_FIELDS)


def _decimal(field, value, *, minimum, maximum, minimum_inclusive=True):
    if isinstance(value, bool):
        raise ValueError(f"{field.label} phải là số.")
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field.label} phải là số.") from None
    if not number.is_finite():
        raise ValueError(f"{field.label} phải là số.")
    if number.as_tuple().exponent < -2:
        raise ValueError(f"{field.label} chỉ được tối đa 2 chữ số thập phân.")
    too_small = number < minimum if minimum_inclusive else number <= minimum
    if too_small or number > maximum:
        if minimum_inclusive:
            raise ValueError(f"{field.label} phải từ {minimum} đến {maximum}.")
        raise ValueError(f"{field.label} phải lớn hơn {minimum} và không quá {maximum}.")
    return number


def clean_policy_value(field: PolicyField, value):
    """Return the value to store (``None`` = follow QC-01) or raise ``ValueError``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if field.kind == "percent":
        return _decimal(field, value, minimum=Decimal(0), maximum=Decimal(100))
    if field.kind == "factor":
        return _decimal(
            field, value, minimum=Decimal(0), maximum=Decimal(10), minimum_inclusive=False,
        )
    if field.kind == "days":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field.label} phải là số ngày nguyên.")
        if not 1 <= value <= 365:
            raise ValueError(f"{field.label} phải từ 1 đến 365 ngày.")
        return value
    text = str(value).strip()
    if field.kind == "organ_code" and not _ORGAN_CODE.match(text):
        raise ValueError(
            f"{field.label} chỉ gồm chữ không dấu, số và . _ - (tối đa 50 ký tự, không khoảng trắng)."
        )
    if field.kind == "file_notation" and not _FILE_NOTATION.match(text):
        raise ValueError(
            f"{field.label} chỉ gồm chữ không dấu, số và _ - (tối đa 20 ký tự)."
        )
    if field.kind == "export_profile" and text not in EXPORT_PROFILES:
        raise ValueError(f"{field.label} phải là {' hoặc '.join(EXPORT_PROFILES)}.")
    return text


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _overrides(row):
    return {key: (getattr(row, key) if row is not None else None) for key in POLICY_KEYS}


def effective_policy(row) -> dict:
    """Settings to apply: a project value when set, otherwise the QC-01 default."""
    overrides = _overrides(row)
    return {
        key: overrides[key] if overrides[key] is not None else QC01_DEFAULTS[key]
        for key in POLICY_KEYS
    }


def get_effective_policy(db, *, project_id) -> dict:
    """For later stages (box deadline, round-2 sampling, KPI, packaging)."""
    return effective_policy(ProjectPolicyRepository(db).for_project(project_id))


def _payload(repository, row) -> dict:
    updated_by = None
    if row is not None and row.updated_by_user_id is not None:
        updated_by = repository.username(row.updated_by_user_id)
    return {
        "qc_version": QC_VERSION,
        "values": {key: _plain(value) for key, value in effective_policy(row).items()},
        "overrides": {key: _plain(value) for key, value in _overrides(row).items()},
        "defaults": {key: _plain(value) for key, value in QC01_DEFAULTS.items()},
        "fields": [
            {"key": field.key, "label": field.label, "qc": field.qc} for field in POLICY_FIELDS
        ],
        "export_profiles": EXPORT_PROFILES,
        "updated_at": (
            row.updated_at.replace(tzinfo=timezone.utc).isoformat() if row is not None else None
        ),
        "updated_by": updated_by,
    }


def _repository_for(db, project_id):
    repository = ProjectPolicyRepository(db)
    if not repository.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return repository


def get_project_policy(db, *, project_id) -> dict:
    repository = _repository_for(db, project_id)
    return _payload(repository, repository.for_project(project_id))


def update_project_policy(db, *, project_id, values: dict, actor_user_id) -> dict:
    """Replace every setting; a missing or empty value means "follow QC-01"."""
    repository = _repository_for(db, project_id)
    cleaned, errors = {}, []
    for field in POLICY_FIELDS:
        try:
            cleaned[field.key] = clean_policy_value(field, values.get(field.key))
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise HTTPException(status_code=400, detail="\n".join(errors))

    row = repository.for_project(project_id)
    if row is None:
        row = repository.add(ProjectPolicy(project_id=project_id))
    for key, value in cleaned.items():
        setattr(row, key, value)
    row.updated_by_user_id = actor_user_id
    db.commit()
    return _payload(repository, row)
