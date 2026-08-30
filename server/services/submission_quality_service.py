from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from server.models import (
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewFieldHistory,
    SubmissionReviewHistory,
)
from server.repositories.submission_quality_repository import SubmissionQualityRepository
from server.repositories.submission_repository import SubmissionRepository
from server.repositories.submission_review_history_repository import (
    SubmissionReviewHistoryRepository,
)
from server.repositories.template_repository import TemplateRepository


DEFAULT_ERROR_REPORT_THRESHOLD_PERCENT = 5
ERROR_REPORT_PERCENT = DEFAULT_ERROR_REPORT_THRESHOLD_PERCENT


def _json_dict(raw_value: str | None) -> dict:
    try:
        value = json.loads(raw_value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_error_report_threshold_percent(config: dict) -> float:
    """Return the configured threshold or the product default.

    The public template-config endpoint uses the same validation helper, while
    persisted legacy config falls back safely in `_error_report_threshold_percent`.
    """
    if "error_report_threshold_percent" not in config:
        return float(DEFAULT_ERROR_REPORT_THRESHOLD_PERCENT)
    value = config.get("error_report_threshold_percent")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 1 <= float(value) <= 100
    ):
        raise ValueError(
            "error_report_threshold_percent phải là số từ 1 đến 100"
        )
    return float(value)


def _public_form_data(data: dict) -> dict:
    return {
        key: value
        for key, value in data.items()
        if isinstance(key, str) and not key.startswith("_")
    }


def _effective_project_config(db, project) -> dict:
    config = _json_dict(project.template_config_json_snapshot)
    template = TemplateRepository(db).get(project.template_id)
    if template:
        current_config = _json_dict(template.config_json)
        config.update(current_config)
    return config


def _error_report_threshold_percent(db, submission: Submission) -> float:
    project = SubmissionQualityRepository(db).project_for_document(
        submission.assigned_document_id
    )
    if project:
        config = _effective_project_config(db, project)
    else:
        template = TemplateRepository(db).get(submission.template_id)
        config = _json_dict(template.config_json) if template else {}
    try:
        return validate_error_report_threshold_percent(config)
    except ValueError:
        return float(DEFAULT_ERROR_REPORT_THRESHOLD_PERCENT)


def _visible_schema_field_names(schema: object, config: dict) -> list[str]:
    configured_hidden_columns = config.get("hidden_cols", [])
    if not isinstance(configured_hidden_columns, (list, tuple, set)):
        configured_hidden_columns = []
    hidden_columns = {
        int(column)
        for column in configured_hidden_columns
        if str(column).strip().isdigit() and int(column) > 0
    }
    names: list[str] = []
    seen: set[str] = set()
    for category in schema if isinstance(schema, list) else []:
        if not isinstance(category, dict):
            continue
        fields = category.get("fields", [])
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            try:
                column_number = int(field.get("col_index")) + 1
            except (TypeError, ValueError):
                continue
            name = field.get("name")
            if (
                column_number in hidden_columns
                or not isinstance(name, str)
                or not name
                or name in seen
            ):
                continue
            seen.add(name)
            names.append(name)
    return names


def _visible_field_names(
    db,
    submission: Submission,
    baseline: dict,
    comparison_data: dict | None = None,
) -> list[str]:
    project = SubmissionQualityRepository(db).project_for_document(
        submission.assigned_document_id
    )
    if project:
        try:
            schema = json.loads(project.form_schema_json_snapshot or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            schema = []
        names = _visible_schema_field_names(
            schema,
            _effective_project_config(db, project),
        )
        if names:
            return names
    return sorted(
        set(_public_form_data(baseline))
        | set(_public_form_data(comparison_data or {}))
    )


def _comparable(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SubmissionQualityService:
    @staticmethod
    def detail_for_input_user(
        submission: Submission,
        user_id: int,
        db,
        *,
        mark_seen: bool = False,
    ) -> dict | None:
        assessment = SubmissionQualityRepository(db).get_for_submission(submission.id)
        if (
            assessment is None
            or not SubmissionRepository(db).is_active_input_assignee(
                submission,
                user_id,
            )
        ):
            return None

        history_repository = SubmissionReviewHistoryRepository(db)
        review_history = history_repository.latest_confirmed_review(submission.id)
        reviewed_changes = (
            history_repository.field_names_for_event(review_history.id)
            if review_history is not None
            else []
        )
        corrected_fields = (
            history_repository.corrected_field_names(review_history.id)
            if review_history is not None
            else []
        )
        is_unread = submission.id in history_repository.unread_submission_ids(user_id)
        if mark_seen and review_history is not None and reviewed_changes:
            history_repository.mark_seen(submission.id, user_id, review_history.id)

        return {
            "has_review_changes": bool(reviewed_changes),
            "changed_field_count": len(reviewed_changes),
            "visible_field_count": int(assessment.visible_field_count or 0),
            "is_error_report": bool(assessment.is_error_report),
            "reviewed_changes": reviewed_changes,
            "corrected_fields": corrected_fields,
            "is_unread": is_unread,
        }

    @staticmethod
    def ensure_baseline(
        submission: Submission,
        data: dict,
        db,
    ) -> SubmissionQualityAssessment | None:
        repository = SubmissionQualityRepository(db)
        assessment = repository.get_for_submission(submission.id)
        if assessment:
            return assessment
        if submission.created_by_user_id is None:
            return None

        baseline = _public_form_data(data)
        assessment = SubmissionQualityAssessment(
            submission_id=submission.id,
            input_user_id=submission.created_by_user_id,
            baseline_data_json=json.dumps(baseline, ensure_ascii=False),
            visible_field_count=len(_visible_field_names(db, submission, baseline)),
            changed_field_count=0,
            is_error_report=False,
        )
        repository.add(assessment)
        return assessment

    @staticmethod
    def assess_confirmed_review(
        submission: Submission,
        final_data: dict,
        reviewer_user_id: int,
        db,
    ) -> SubmissionQualityAssessment | None:
        assessment = SubmissionQualityService.ensure_baseline(
            submission,
            _json_dict(submission.data_json),
            db,
        )
        if assessment is None:
            return None

        baseline = _json_dict(assessment.baseline_data_json)
        final_public_data = _public_form_data(final_data)
        field_names = _visible_field_names(
            db,
            submission,
            baseline,
            final_public_data,
        )
        changed_count = sum(
            _comparable(baseline.get(name, ""))
            != _comparable(final_public_data.get(name, ""))
            for name in field_names
        )
        visible_count = len(field_names)
        threshold_percent = _error_report_threshold_percent(db, submission)
        exceeds_threshold = (
            visible_count > 0
            and changed_count * 100 >= visible_count * threshold_percent
        )

        assessment.visible_field_count = visible_count
        assessment.changed_field_count = changed_count
        assessment.is_error_report = bool(exceeds_threshold)
        assessment.reviewer_user_id = reviewer_user_id
        assessment.assessed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        history_repository = SubmissionReviewHistoryRepository(db)
        review_history = history_repository.add(SubmissionReviewHistory(
            submission_id=submission.id,
            event_type="review_confirmed",
            input_user_id=assessment.input_user_id,
            reviewer_user_id=reviewer_user_id,
            baseline_data_json=json.dumps(baseline, ensure_ascii=False),
            reviewer_data_json=json.dumps(final_public_data, ensure_ascii=False),
            visible_field_count=visible_count,
            changed_field_count=changed_count,
            reviewer_error_count=0,
        ))
        db.flush()
        for name in field_names:
            baseline_value = baseline.get(name, "")
            reviewer_value = final_public_data.get(name, "")
            if _comparable(baseline_value) == _comparable(reviewer_value):
                continue
            history_repository.add_field(SubmissionReviewFieldHistory(
                event_id=review_history.id,
                submission_id=submission.id,
                field_name=name,
                baseline_value_json=_json_value(baseline_value),
                reviewer_value_json=_json_value(reviewer_value),
                reviewer_error=False,
            ))
        return assessment

    @staticmethod
    def apply_input_correction(
        submission: Submission,
        data: dict,
        input_user_id: int,
        db,
    ) -> tuple[SubmissionReviewHistory, dict]:
        history_repository = SubmissionReviewHistoryRepository(db)
        review_history = history_repository.latest_confirmed_review(submission.id)
        if review_history is None:
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ chưa có lịch sử xác nhận kiểm duyệt",
            )
        if not SubmissionRepository(db).is_active_input_assignee(
            submission,
            input_user_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="Chỉ nhân viên đang được phân công hồ sơ mới được sửa lại",
            )
        if submission.status != "pending_input_confirmation":
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ chưa ở bước người nhập kiểm tra lại",
            )
        if history_repository.get_input_correction(review_history.id) is not None:
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ này đã được người nhập xác nhận",
            )

        baseline = _json_dict(review_history.baseline_data_json)
        reviewed = _json_dict(review_history.reviewer_data_json)
        field_names = _visible_field_names(db, submission, baseline, reviewed)
        reviewer_changed_names = {
            name
            for name in field_names
            if _comparable(baseline.get(name, ""))
            != _comparable(reviewed.get(name, ""))
        }
        requested = _public_form_data(data)
        unknown_fields = sorted(set(requested).difference(reviewer_changed_names))
        if unknown_fields:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_correction_fields",
                    "fields": unknown_fields,
                    "message": "Chỉ được sửa các trường mà người kiểm duyệt đã thay đổi",
                },
            )

        final_public_data = dict(reviewed)
        final_public_data.update(requested)
        corrected_names = [
            name
            for name in field_names
            if _comparable(reviewed.get(name, ""))
            != _comparable(final_public_data.get(name, ""))
        ]
        history_names = [
            name
            for name in field_names
            if (
                _comparable(baseline.get(name, ""))
                != _comparable(reviewed.get(name, ""))
                or name in corrected_names
            )
        ]
        reviewer_error_names = {
            name
            for name in history_names
            if (
                _comparable(baseline.get(name, ""))
                != _comparable(reviewed.get(name, ""))
                and _comparable(final_public_data.get(name, ""))
                != _comparable(reviewed.get(name, ""))
            )
        }

        correction_history = history_repository.add(SubmissionReviewHistory(
            submission_id=submission.id,
            review_event_id=review_history.id,
            event_type="input_confirmed",
            input_user_id=review_history.input_user_id,
            confirmed_by_user_id=input_user_id,
            reviewer_user_id=review_history.reviewer_user_id,
            baseline_data_json=json.dumps(baseline, ensure_ascii=False),
            reviewer_data_json=json.dumps(reviewed, ensure_ascii=False),
            final_data_json=json.dumps(final_public_data, ensure_ascii=False),
            visible_field_count=len(field_names),
            changed_field_count=len(corrected_names),
            reviewer_error_count=len(reviewer_error_names),
            correction_token=history_repository.correction_token(review_history.id),
        ))
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="Hồ sơ này đã được người nhập xác nhận",
            ) from exc

        for name in history_names:
            history_repository.add_field(SubmissionReviewFieldHistory(
                event_id=correction_history.id,
                submission_id=submission.id,
                field_name=name,
                baseline_value_json=_json_value(baseline.get(name, "")),
                reviewer_value_json=_json_value(reviewed.get(name, "")),
                final_value_json=_json_value(final_public_data.get(name, "")),
                reviewer_error=name in reviewer_error_names,
            ))

        stored_data = _json_dict(submission.data_json)
        stored_data.update(final_public_data)
        submission.data_json = json.dumps(stored_data, ensure_ascii=False)
        submission.status = "completed"
        submission.is_checked = True
        assessment = SubmissionQualityRepository(db).get_for_submission(submission.id)
        if assessment is not None:
            final_error_count = sum(
                _comparable(baseline.get(name, ""))
                != _comparable(final_public_data.get(name, ""))
                for name in field_names
            )
            assessment.visible_field_count = len(field_names)
            assessment.changed_field_count = final_error_count
            threshold_percent = _error_report_threshold_percent(db, submission)
            assessment.is_error_report = bool(
                field_names
                and final_error_count * 100
                >= len(field_names) * threshold_percent
            )
        return correction_history, stored_data
