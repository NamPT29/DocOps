from collections import Counter
from datetime import timedelta, timezone

from fastapi import HTTPException

from server.database import get_utc_now
from server.models import CaseInputAssignment
from server.repositories.project_assignment_repository import ProjectAssignmentRepository
from server.repositories.workflow_repository import WorkflowRepository
from server.services import account_policy_service as account_policy
from server.services import workflow_engine as engine
from server.services.arrangement_catalog_parser import is_placeholder_box_key
from server.services.project_policy_service import get_effective_policy
from server.services.project_workspace_service import sync_project_assets_to_documents

VALID_REASONS = {
    "overdue": "Quá hạn",
    "ctv_expired": "CTV hết hạn",
    "user_locked": "Tài khoản bị khóa",
    "member_unavailable": "CTV nghỉ / bận / hết hạn",
    "rejected_too_much": "Trả lại nhiều lần / vượt ngưỡng",
    "other": "Khác",
}


def _least_loaded_user(eligible_user_ids, counts):
    if not eligible_user_ids:
        return None
    return min(eligible_user_ids, key=lambda user_id: (counts[user_id], user_id))


def assign_unassigned_project_cases(db, *, project_id, changed_by_user_id):
    repository = ProjectAssignmentRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        return {"input_assigned": 0, "reviewer_assigned": 0}

    workflow_repo = WorkflowRepository(db)
    stages = workflow_repo.stage_rows(project_id)
    has_workflow = any(r.is_enabled for r in stages)

    input_user_ids = repository.active_member_ids(project_id, "input")
    reviewer_user_ids = repository.active_member_ids(project_id, "reviewer")
    # Boxes still awaiting their scan (created from the arrangement catalogue)
    # are handed out later, once they hold PDFs.
    cases = [
        case_row for case_row in repository.lock_cases(project_id)
        if not is_placeholder_box_key(case_row.case_key)
    ]
    pdf_counts = repository.active_pdf_counts_by_case(project_id)
    case_weights = {
        case_row.id: max(1, pdf_counts.get(case_row.id, 0))
        for case_row in cases
    }
    input_loads = Counter()
    reviewer_loads = Counter()
    for case_row in cases:
        weight = case_weights[case_row.id]
        if case_row.assigned_input_user_id is not None:
            input_loads[case_row.assigned_input_user_id] += weight
        if case_row.assigned_reviewer_user_id is not None:
            reviewer_loads[case_row.assigned_reviewer_user_id] += weight

    input_assigned = 0
    reviewer_assigned = 0

    # Decision 1 / R3: If workflow is enabled, skip auto-assigning input cases!
    # For legacy projects, only assign cases that have NEVER had any input assignment.
    if not has_workflow:
        assigned_history_case_ids = repository.case_ids_with_history(project_id)
        unassigned_input_cases = sorted(
            (
                case_row for case_row in cases
                if case_row.assigned_input_user_id is None
                and case_row.id not in assigned_history_case_ids
            ),
            key=lambda case_row: (
                -case_weights[case_row.id],
                case_row.case_key.casefold(),
                case_row.id,
            ),
        )
        policy = get_effective_policy(db, project_id=project_id)
        deadline_days = policy["box_deadline_days"]
        now = get_utc_now()
        due_at = now + timedelta(days=deadline_days)
        for case_row in unassigned_input_cases:
            input_user_id = _least_loaded_user(input_user_ids, input_loads)
            if input_user_id is None:
                continue
            case_row.assigned_input_user_id = input_user_id
            input_loads[input_user_id] += case_weights[case_row.id]
            input_assigned += 1
            repository.add_case_input_assignment(
                CaseInputAssignment(
                    project_id=project_id,
                    case_id=case_row.id,
                    user_id=input_user_id,
                    assigned_by_user_id=changed_by_user_id,
                    assigned_at=now,
                    due_at=due_at,
                    deadline_days=deadline_days,
                )
            )
            repository.add_history(
                project_id=project_id,
                case_id=case_row.id,
                assignment_role="input",
                from_user_id=None,
                to_user_id=input_user_id,
                changed_by_user_id=changed_by_user_id,
                reason="initial_import",
            )

    for case_row in cases:
        if case_row.assigned_reviewer_user_id == case_row.assigned_input_user_id:
            previous_reviewer_id = case_row.assigned_reviewer_user_id
            if previous_reviewer_id is not None:
                reviewer_loads[previous_reviewer_id] -= case_weights[case_row.id]
            case_row.assigned_reviewer_user_id = None
            repository.add_history(
                project_id=project_id,
                case_id=case_row.id,
                assignment_role="reviewer",
                from_user_id=previous_reviewer_id,
                to_user_id=None,
                changed_by_user_id=changed_by_user_id,
                reason="prevent_self_review",
            )

    unassigned_reviewer_cases = sorted(
        (case_row for case_row in cases if case_row.assigned_reviewer_user_id is None),
        key=lambda case_row: (
            -case_weights[case_row.id],
            case_row.case_key.casefold(),
            case_row.id,
        ),
    )
    for case_row in unassigned_reviewer_cases:
        eligible_reviewers = [
            user_id
            for user_id in reviewer_user_ids
            if user_id != case_row.assigned_input_user_id
        ]
        reviewer_user_id = _least_loaded_user(eligible_reviewers, reviewer_loads)
        if reviewer_user_id is None:
            continue
        case_row.assigned_reviewer_user_id = reviewer_user_id
        reviewer_loads[reviewer_user_id] += case_weights[case_row.id]
        reviewer_assigned += 1
        repository.add_history(
            project_id=project_id,
            case_id=case_row.id,
            assignment_role="reviewer",
            from_user_id=None,
            to_user_id=reviewer_user_id,
            changed_by_user_id=changed_by_user_id,
            reason="initial_import",
        )

    db.flush()
    return {
        "input_assigned": input_assigned,
        "reviewer_assigned": reviewer_assigned,
    }


def list_action_needed_cases(db, *, project_id: int | None = None) -> list[dict]:
    repository = ProjectAssignmentRepository(db)
    return repository.list_action_needed_cases(project_id)


def list_ready_input_cases(db, *, project_id: int) -> dict:
    repository = ProjectAssignmentRepository(db)
    project = repository.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    workflow_repo = WorkflowRepository(db)
    stages = workflow_repo.stage_rows(project_id)
    enabled_keys = [s.stage_key for s in stages if s.is_enabled]
    prev_stage = engine.previous_enabled("data_entry", enabled_keys)
    prev_stage_label = engine.get_stage(prev_stage).label if prev_stage else None

    cases = repository.list_ready_input_cases(project_id, prev_stage)
    eligible_users = repository.eligible_input_members(project_id)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "previous_stage_key": prev_stage,
        "previous_stage_label": prev_stage_label,
        "cases": cases,
        "eligible_users": eligible_users,
    }


def assign_case_input(db, *, project_id: int, case_id: int, user_id: int, actor_user_id: int) -> dict:
    repository = ProjectAssignmentRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    case_row = repository.lock_case_by_id(project_id, case_id)
    if not case_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy hộp")

    if case_row.assigned_input_user_id is not None:
        raise HTTPException(status_code=409, detail="Hộp đã được giao cho người khác")

    if is_placeholder_box_key(case_row.case_key):
        raise HTTPException(status_code=409, detail="Hộp chờ scan chưa thể giao nhập liệu")

    pdf_counts = repository.active_pdf_counts_by_case(project_id)
    if pdf_counts.get(case_row.id, 0) == 0:
        raise HTTPException(status_code=409, detail="Hộp chưa có PDF không thể giao nhập liệu")

    workflow_repo = WorkflowRepository(db)
    stages = workflow_repo.stage_rows(project_id)
    enabled_keys = [s.stage_key for s in stages if s.is_enabled]
    if enabled_keys:
        prev_stage = engine.previous_enabled("data_entry", enabled_keys)
        if prev_stage is not None:
            prev_state = workflow_repo.case_stage_state(case_id, prev_stage)
            if not prev_state or prev_state.status != engine.DONE:
                stage_def = engine.get_stage(prev_stage)
                raise HTTPException(
                    status_code=409,
                    detail=f"Bước liền trước ({stage_def.label}) chưa hoàn tất",
                )

    user = workflow_repo.users_by_ids([user_id]).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")

    input_ids = repository.member_ids(project_id, "input")
    if user_id not in input_ids:
        raise HTTPException(
            status_code=409,
            detail="Người dùng không thuộc nhóm nhập liệu của dự án",
        )

    if account_policy.is_locked(user):
        raise HTTPException(status_code=409, detail="Tài khoản người nhận đang bị khóa")

    if account_policy.is_expired(user):
        raise HTTPException(status_code=409, detail="Tài khoản CTV của người nhận đã hết hạn")

    if user_id == case_row.assigned_reviewer_user_id:
        raise HTTPException(
            status_code=409,
            detail="Không được giao người nhập trùng với người kiểm tra của hộp (BR-04)",
        )

    now = get_utc_now()
    policy = get_effective_policy(db, project_id=project_id)
    deadline_days = policy["box_deadline_days"]
    due_at = now + timedelta(days=deadline_days)

    case_row.assigned_input_user_id = user_id
    repository.add_case_input_assignment(
        CaseInputAssignment(
            project_id=project_id,
            case_id=case_row.id,
            user_id=user_id,
            assigned_by_user_id=actor_user_id,
            assigned_at=now,
            due_at=due_at,
            deadline_days=deadline_days,
        )
    )
    repository.add_history(
        project_id=project_id,
        case_id=case_row.id,
        assignment_role="input",
        from_user_id=None,
        to_user_id=user_id,
        changed_by_user_id=actor_user_id,
        reason="manual_assignment",
    )
    # Condition 1: sync documents within the same transaction
    sync_project_assets_to_documents(db, project_id=project_id)
    db.commit()
    return {
        "status": "ok",
        "case_id": case_row.id,
        "assigned_user_id": user_id,
        "due_at": due_at.replace(tzinfo=timezone.utc).isoformat(),
        "deadline_days": deadline_days,
    }


def revoke_case_input(
    db,
    *,
    project_id: int,
    case_id: int,
    reason_code: str,
    note: str | None,
    new_user_id: int | None,
    actor_user_id: int,
) -> dict:
    if reason_code not in VALID_REASONS:
        raise HTTPException(status_code=400, detail="Lý do thu hồi không hợp lệ")
    if reason_code == "other" and (not note or not note.strip()):
        raise HTTPException(status_code=400, detail="Vui lòng nhập ghi chú khi chọn lý do khác")

    reason_str = VALID_REASONS[reason_code]
    if note and note.strip():
        reason_str += f": {note.strip()}"

    repository = ProjectAssignmentRepository(db)
    project = repository.lock_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    case_row = repository.lock_case_by_id(project_id, case_id)
    if not case_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy hộp")

    previous_user_id = case_row.assigned_input_user_id
    if previous_user_id is None:
        raise HTTPException(status_code=409, detail="Hộp chưa được giao cho ai")

    if new_user_id is not None and new_user_id == previous_user_id:
        raise HTTPException(
            status_code=409,
            detail="Không cho giao lại cho chính người đang giữ hộp",
        )

    workflow_repo = WorkflowRepository(db)
    if new_user_id is not None:
        new_user = workflow_repo.users_by_ids([new_user_id]).get(new_user_id)
        if not new_user:
            raise HTTPException(status_code=404, detail="Không tìm thấy người nhận mới")

        input_ids = repository.member_ids(project_id, "input")
        if new_user_id not in input_ids:
            raise HTTPException(
                status_code=409,
                detail="Người nhận mới không thuộc nhóm nhập liệu của dự án",
            )

        if account_policy.is_locked(new_user):
            raise HTTPException(status_code=409, detail="Tài khoản người nhận mới đang bị khóa")

        if account_policy.is_expired(new_user):
            raise HTTPException(status_code=409, detail="Tài khoản CTV của người nhận mới đã hết hạn")

        if new_user_id == case_row.assigned_reviewer_user_id:
            raise HTTPException(
                status_code=409,
                detail="Không được giao người nhập trùng với người kiểm tra của hộp (BR-04)",
            )

    now = get_utc_now()
    active_assignment = repository.active_case_input_assignment(case_row.id)
    if active_assignment:
        active_assignment.ended_at = now
        active_assignment.ended_by_user_id = actor_user_id
        active_assignment.end_reason = reason_str

    if new_user_id is not None:
        policy = get_effective_policy(db, project_id=project_id)
        deadline_days = policy["box_deadline_days"]
        due_at = now + timedelta(days=deadline_days)

        case_row.assigned_input_user_id = new_user_id
        repository.add_case_input_assignment(
            CaseInputAssignment(
                project_id=project_id,
                case_id=case_row.id,
                user_id=new_user_id,
                assigned_by_user_id=actor_user_id,
                assigned_at=now,
                due_at=due_at,
                deadline_days=deadline_days,
            )
        )
        repository.add_history(
            project_id=project_id,
            case_id=case_row.id,
            assignment_role="input",
            from_user_id=previous_user_id,
            to_user_id=new_user_id,
            changed_by_user_id=actor_user_id,
            reason=reason_str,
        )
    else:
        case_row.assigned_input_user_id = None
        due_at = None
        deadline_days = None
        repository.add_history(
            project_id=project_id,
            case_id=case_row.id,
            assignment_role="input",
            from_user_id=previous_user_id,
            to_user_id=None,
            changed_by_user_id=actor_user_id,
            reason=reason_str,
        )

    # Condition 1: sync documents within the same transaction
    sync_project_assets_to_documents(db, project_id=project_id)
    db.commit()
    return {
        "status": "ok",
        "case_id": case_row.id,
        "assigned_user_id": new_user_id,
        "due_at": due_at.replace(tzinfo=timezone.utc).isoformat() if due_at else None,
        "deadline_days": deadline_days,
    }
