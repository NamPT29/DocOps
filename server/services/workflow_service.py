from fastapi import HTTPException

from server.database import get_utc_now
from server.models import (
    CaseStageEvent,
    CaseStageState,
    ProjectStage,
    ProjectStageMember,
)
from server.repositories.workflow_repository import WorkflowRepository
from server.services import account_policy_service as account_policy
from server.services import workflow_engine as engine

_CLIENT_ERROR_CODES = {"unknown_stage", "unknown_action", "reason_required"}


def _http_error(error):
    status = 400 if error.code in _CLIENT_ERROR_CODES else 409
    return HTTPException(
        status_code=status,
        detail={"code": error.code, "message": error.message},
    )


def _stage(stage_key):
    try:
        return engine.get_stage(stage_key)
    except engine.WorkflowError as error:
        raise _http_error(error)


def stage_catalog():
    return [
        {
            "key": stage.key,
            "label": stage.label,
            "kind": stage.kind,
            "reviews": stage.reviews,
            "derived": stage.derived,
            "allowed_roles": list(stage.allowed_roles),
        }
        for stage in engine.STAGE_CATALOG
    ]


def _project_or_404(repository, project_id):
    project = repository.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return project


def _enabled_keys(repository, project_id):
    return [row.stage_key for row in repository.stage_rows(project_id) if row.is_enabled]


# --------------------------------------------------------------------------- config
def get_workflow_config(db, *, project_id):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    rows = {row.stage_key: row for row in repository.stage_rows(project_id)}
    members = {}
    for member in repository.stage_member_rows(project_id):
        if member.is_active:
            members.setdefault(member.stage_key, []).append(member.user_id)
    stages = []
    for stage in engine.STAGE_CATALOG:
        row = rows.get(stage.key)
        if stage.member_role:
            member_ids = repository.legacy_member_ids(project_id, stage.member_role)
        else:
            member_ids = sorted(members.get(stage.key, []))
        stages.append({
            "key": stage.key,
            "label": stage.label,
            "kind": stage.kind,
            "reviews": stage.reviews,
            "derived": stage.derived,
            "allowed_roles": list(stage.allowed_roles),
            "enabled": bool(row and row.is_enabled),
            "member_user_ids": member_ids,
            "members_from_project": stage.member_role is not None,
        })
    return {"project_id": project_id, "configured": bool(rows), "stages": stages}


def _validate_enabled(enabled_keys):
    keys = set(enabled_keys)
    for key in keys:
        _stage(key)
    if not keys:
        raise HTTPException(status_code=400, detail="Cần bật ít nhất một bước quy trình")
    for key in keys:
        reviewed = engine.STAGES_BY_KEY[key].reviews
        if reviewed and reviewed not in keys:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Bước '{engine.STAGES_BY_KEY[key].label}' cần bật kèm "
                    f"'{engine.STAGES_BY_KEY[reviewed].label}'"
                ),
            )
    return keys


def _validate_members(repository, enabled, members):
    cleaned = {}
    for stage_key, user_ids in (members or {}).items():
        stage = _stage(stage_key)
        if stage.member_role:
            continue  # input/reviewer pools are managed on the project itself
        if stage_key not in enabled:
            continue
        cleaned[stage_key] = sorted({int(user_id) for user_id in user_ids or []})
    users = repository.users_by_ids({uid for ids in cleaned.values() for uid in ids})
    for stage_key, ids in cleaned.items():
        stage = engine.STAGES_BY_KEY[stage_key]
        for user_id in ids:
            user = users.get(user_id)
            if user is None:
                raise HTTPException(status_code=400, detail=f"Không tìm thấy người dùng: {user_id}")
            # FR-AUT-03: "staff" means Hành chính only, so CTV is excluded here.
            if account_policy.account_type_of(user) not in stage.allowed_roles:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Bước '{stage.label}' chỉ dành cho: "
                        f"{account_policy.role_labels(stage.allowed_roles)}"
                    ),
                )
    return cleaned


def configure_workflow(db, *, project_id, enabled_stage_keys, members, actor_user_id):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    enabled = _validate_enabled(enabled_stage_keys)
    cleaned_members = _validate_members(repository, enabled, members)

    existing_rows = {row.stage_key: row for row in repository.stage_rows(project_id)}
    first_time = not existing_rows
    try:
        for position, stage in enumerate(engine.STAGE_CATALOG):
            row = existing_rows.get(stage.key)
            is_enabled = stage.key in enabled
            if row is None:
                repository.add_stage(ProjectStage(
                    project_id=project_id,
                    stage_key=stage.key,
                    position=position,
                    is_enabled=is_enabled,
                ))
            else:
                row.is_enabled = is_enabled
                row.position = position

        member_rows = {
            (row.stage_key, row.user_id): row
            for row in repository.stage_member_rows(project_id)
        }
        wanted = {
            (stage_key, user_id)
            for stage_key, user_ids in cleaned_members.items()
            for user_id in user_ids
        }
        for key, row in member_rows.items():
            row.is_active = key in wanted
        for stage_key, user_id in sorted(wanted - set(member_rows)):
            repository.add_stage_member(ProjectStageMember(
                project_id=project_id,
                user_id=user_id,
                stage_key=stage_key,
            ))

        backfilled = 0
        if first_time:
            backfilled = _backfill_upstream_stages(
                repository, project_id, enabled, actor_user_id
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    result = get_workflow_config(db, project_id=project_id)
    result["backfilled_states"] = backfilled
    return result


def _backfill_upstream_stages(repository, project_id, enabled, actor_user_id):
    """Existing cases already have PDFs, so stages before data entry are done."""
    upstream = [
        key for key in engine.ordered_enabled(enabled)
        if engine.STAGE_KEYS.index(key) < engine.STAGE_KEYS.index("data_entry")
    ]
    if not upstream:
        return 0
    created = 0
    now = get_utc_now()
    for case_id in sorted(repository.case_ids_with_active_pdfs(project_id)):
        for stage_key in upstream:
            repository.add_state(CaseStageState(
                project_id=project_id,
                case_id=case_id,
                stage_key=stage_key,
                status=engine.DONE,
                started_at=now,
                completed_at=now,
            ))
            repository.add_event(CaseStageEvent(
                project_id=project_id,
                case_id=case_id,
                stage_key=stage_key,
                action="backfill",
                from_status=None,
                to_status=engine.DONE,
                actor_user_id=actor_user_id,
                reason="Hồ sơ đã có PDF trước khi bật quy trình",
            ))
            created += 1
    return created


# --------------------------------------------------------------------------- views
def _status_matrix(repository, project_id, enabled, cases):
    """``{case_id: {stage_key: {status, assigned_user_id, rework_count}}}``."""
    stored = {}
    for state in repository.states_for_project(project_id):
        stored.setdefault(state.case_id, {})[state.stage_key] = state
    derived_keys = [key for key in enabled if engine.STAGES_BY_KEY[key].derived]
    progress = repository.entry_progress_by_case(project_id) if derived_keys else {}

    matrix = {}
    for case in cases:
        row = {}
        derived = {}
        if derived_keys:
            derived = engine.derive_entry_statuses(
                **progress.get(case.id, {
                    "report_total": 0,
                    "reports_entered": 0,
                    "submissions_total": 0,
                    "submissions_under_review": 0,
                    "submissions_completed": 0,
                })
            )
        for key in enabled:
            state = stored.get(case.id, {}).get(key)
            if engine.STAGES_BY_KEY[key].derived:
                row[key] = {"status": derived[key], "assigned_user_id": None, "rework_count": 0}
            elif state is None:
                row[key] = {"status": engine.PENDING, "assigned_user_id": None, "rework_count": 0}
            else:
                row[key] = {
                    "status": state.status,
                    "assigned_user_id": state.assigned_user_id,
                    "rework_count": state.rework_count,
                }
        matrix[case.id] = row
    return matrix


def get_overview(db, *, project_id):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    enabled = engine.ordered_enabled(_enabled_keys(repository, project_id))
    cases = repository.list_cases(project_id)
    matrix = _status_matrix(repository, project_id, enabled, cases)

    stages = []
    for stage in engine.STAGE_CATALOG:
        if stage.key not in enabled:
            stages.append({
                "key": stage.key, "label": stage.label, "kind": stage.kind,
                "enabled": False,
                "counts": {status: 0 for status in engine.STATUSES},
                "ready": 0, "backlog": 0, "rework_total": 0,
            })
            continue
        counts = {status: 0 for status in engine.STATUSES}
        ready = 0
        rework_total = 0
        for case in cases:
            row = matrix[case.id]
            cell = row[stage.key]
            counts[cell["status"]] += 1
            rework_total += cell["rework_count"]
            statuses = {key: value["status"] for key, value in row.items()}
            if cell["status"] in (engine.PENDING, engine.REJECTED) and engine.is_available(
                stage.key, statuses, enabled
            ):
                ready += 1
        stages.append({
            "key": stage.key, "label": stage.label, "kind": stage.kind,
            "enabled": True,
            "counts": counts,
            "ready": ready,
            "backlog": ready + counts[engine.IN_PROGRESS],
            "rework_total": rework_total,
        })

    bottleneck = None
    best = 0
    for stage in stages:
        if stage["enabled"] and stage["backlog"] > best:
            best = stage["backlog"]
            bottleneck = stage["key"]
    completed_cases = sum(
        1
        for case in cases
        if enabled and all(matrix[case.id][key]["status"] == engine.DONE for key in enabled)
    )
    return {
        "project_id": project_id,
        "configured": bool(enabled),
        "cases_total": len(cases),
        "completed_cases": completed_cases,
        "bottleneck": bottleneck,
        "stages": stages,
    }


def list_cases(db, *, project_id, stage_key=None, status=None, page=1, page_size=50):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    enabled = engine.ordered_enabled(_enabled_keys(repository, project_id))
    if stage_key is not None:
        _stage(stage_key)
    if status is not None and status not in engine.STATUSES:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ")
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    cases = repository.list_cases(project_id)
    matrix = _status_matrix(repository, project_id, enabled, cases)

    rows = []
    for case in cases:
        statuses = {key: value["status"] for key, value in matrix[case.id].items()}
        if stage_key is not None:
            cell = matrix[case.id].get(stage_key)
            if cell is None or (status is not None and cell["status"] != status):
                continue
        elif status is not None and not any(
            value["status"] == status for value in matrix[case.id].values()
        ):
            continue
        rows.append({
            "case_id": case.id,
            "case_key": case.case_key,
            "display_name": case.display_name,
            "stages": {
                key: {
                    **cell,
                    "available": engine.is_available(key, statuses, enabled),
                }
                for key, cell in matrix[case.id].items()
            },
        })
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "enabled_stages": enabled,
        "items": rows[start:start + page_size],
    }


def list_case_events(db, *, project_id, case_id):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    if not repository.get_case(project_id, case_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
    return [
        {
            "id": event.id,
            "stage_key": event.stage_key,
            "action": event.action,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "actor_user_id": event.actor_user_id,
            "reason": event.reason,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in repository.events_for_case(case_id)
    ]


# --------------------------------------------------------------------- transitions
def _require_stage_worker(repository, project_id, actor, stage_key):
    if actor.get("role") == "admin":
        return
    if not repository.user_is_stage_member(project_id, actor["id"], stage_key):
        raise HTTPException(
            status_code=403,
            detail="Bạn không được phân quyền cho bước này trong dự án",
        )


def _current_statuses(repository, project_id, case_id, enabled):
    stored = {state.stage_key: state for state in repository.states_for_case(case_id)}
    statuses = {}
    derived = {}
    if any(engine.STAGES_BY_KEY[key].derived for key in enabled):
        progress = repository.entry_progress_by_case(project_id, case_id=case_id)
        derived = engine.derive_entry_statuses(**progress.get(case_id, {
            "report_total": 0,
            "reports_entered": 0,
            "submissions_total": 0,
            "submissions_under_review": 0,
            "submissions_completed": 0,
        }))
    for key in enabled:
        if engine.STAGES_BY_KEY[key].derived:
            statuses[key] = derived[key]
        else:
            state = stored.get(key)
            statuses[key] = state.status if state else engine.PENDING
    return statuses, stored


def _check_scan_qc_complete(repository, case_id, is_admin, reason):
    if not repository.catalog_dossier_count(case_id):
        return
        
    pkg = repository.get_latest_scan_package(case_id)
    if pkg and pkg.status == "processing":
        raise HTTPException(
            status_code=409,
            detail={"code": "scan_processing", "message": "Gói scan đang được xử lý ngầm, vui lòng đợi."}
        )
        
    is_mismatch = (
        not pkg 
        or pkg.status == "failed" 
        or pkg.match_status != "matched"
    )
    
    if is_mismatch:
        if not is_admin:
            raise HTTPException(
                status_code=409,
                detail={"code": "scan_catalog_mismatch", "message": "Hồ sơ scan lệch với mục lục. Chỉ Admin được duyệt."}
            )
        if not reason or not str(reason).strip():
            raise HTTPException(
                status_code=409,
                detail={"code": "reason_required", "message": "Bắt buộc nhập lý do khi duyệt hồ sơ lệch mục lục."}
            )


def transition_case_stage(db, *, project_id, case_id, stage_key, action, actor, reason=None):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    case = repository.get_case(project_id, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
    enabled = engine.ordered_enabled(_enabled_keys(repository, project_id))
    is_admin = actor.get("role") == "admin"

    try:
        _stage(stage_key)
        if action == engine.REOPEN and not is_admin:
            raise HTTPException(status_code=403, detail="Chỉ quản trị viên được mở lại bước")
        if action != engine.REOPEN and stage_key in enabled:
            _require_stage_worker(repository, project_id, actor, stage_key)
            
        if stage_key == "scan_qc" and action == engine.COMPLETE:
            _check_scan_qc_complete(repository, case_id, is_admin, reason)

        # Lock the rows we may change so two actors cannot race on one case.
        for key in enabled:
            if not engine.STAGES_BY_KEY[key].derived:
                repository.get_state(case_id, key, lock=True)
        statuses, stored = _current_statuses(repository, project_id, case_id, enabled)
        changes = engine.apply_action(
            stage_key, action, statuses, enabled, reason=reason
        )
        stage = engine.STAGES_BY_KEY[stage_key]
        now = get_utc_now()

        # BA: Chỉnh lý is complete once the box's catalogue was imported.
        if (
            stage_key == "arrangement"
            and action == engine.COMPLETE
            and not repository.catalog_dossier_count(case_id)
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "catalog_required",
                    "message": (
                        "Hộp chưa có mục lục chỉnh lý (FR-ARR-01). Hãy import mục lục "
                        "của hộp trước khi hoàn tất bước Chỉnh lý."
                    ),
                },
            )

        # BR-04: nobody checks their own work, administrators included.
        if stage.kind == "qc" and action in (
            engine.START, engine.COMPLETE, engine.REJECT
        ):
            reviewed_state = stored.get(stage.reviews)
            if reviewed_state is not None and reviewed_state.assigned_user_id == actor["id"]:
                raise HTTPException(
                    status_code=403,
                    detail="Người thực hiện không được tự kiểm tra hồ sơ của mình",
                )
        own_state = stored.get(stage_key)
        if (
            not is_admin
            and action in (engine.COMPLETE, engine.REJECT)
            and own_state is not None
            and own_state.assigned_user_id not in (None, actor["id"])
        ):
            raise HTTPException(status_code=403, detail="Hồ sơ đang được người khác xử lý")

        for key, new_status in changes.items():
            state = stored.get(key)
            old_status = state.status if state else engine.PENDING
            if state is None:
                state = repository.add_state(CaseStageState(
                    project_id=project_id,
                    case_id=case_id,
                    stage_key=key,
                    status=old_status,
                ))
                stored[key] = state
            state.status = new_status
            if new_status == engine.IN_PROGRESS:
                state.started_at = state.started_at or now
                state.completed_at = None
                # A worker claims the case; an admin keeps an existing assignee.
                if key == stage_key and action == engine.START and (
                    not is_admin or state.assigned_user_id is None
                ):
                    state.assigned_user_id = actor["id"]
            elif new_status == engine.DONE:
                state.completed_at = now
            elif new_status == engine.REJECTED:
                state.rework_count = (state.rework_count or 0) + 1
                state.completed_at = None
            repository.add_event(CaseStageEvent(
                project_id=project_id,
                case_id=case_id,
                stage_key=key,
                action=action if key == stage_key else "returned",
                from_status=old_status,
                to_status=new_status,
                actor_user_id=actor["id"],
                reason=(str(reason).strip()[:500] if reason else None),
            ))
        db.commit()
    except engine.WorkflowError as error:
        db.rollback()
        raise _http_error(error)
    except Exception:
        db.rollback()
        raise
    return {
        "case_id": case_id,
        "stage_key": stage_key,
        "action": action,
        "statuses": {key: value for key, value in changes.items()},
    }


def assign_case_stage(db, *, project_id, case_id, stage_key, user_id, actor):
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    if not repository.get_case(project_id, case_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
    stage = _stage(stage_key)
    enabled = _enabled_keys(repository, project_id)
    if stage_key not in enabled:
        raise HTTPException(status_code=409, detail="Bước chưa được bật cho dự án")
    if stage.derived:
        raise HTTPException(
            status_code=409,
            detail="Bước nhập liệu/kiểm tra phân công theo hồ sơ trong tab Dự án",
        )
    if user_id is not None and not repository.user_is_stage_member(project_id, user_id, stage_key):
        raise HTTPException(status_code=400, detail="Người dùng chưa thuộc nhóm thực hiện bước này")
    try:
        state = repository.get_state(case_id, stage_key, lock=True)
        previous = state.assigned_user_id if state else None
        if state is None:
            state = repository.add_state(CaseStageState(
                project_id=project_id, case_id=case_id, stage_key=stage_key,
                status=engine.PENDING,
            ))
        state.assigned_user_id = user_id
        repository.add_event(CaseStageEvent(
            project_id=project_id,
            case_id=case_id,
            stage_key=stage_key,
            action="assign",
            from_status=state.status,
            to_status=state.status,
            actor_user_id=actor["id"],
            reason=f"{previous or '-'} -> {user_id or '-'}",
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"case_id": case_id, "stage_key": stage_key, "assigned_user_id": user_id}


def list_my_work(db, *, project_id, user):
    """Cases a stage member can act on now (claimable or already theirs)."""
    repository = WorkflowRepository(db)
    _project_or_404(repository, project_id)
    enabled = engine.ordered_enabled(_enabled_keys(repository, project_id))
    stage_keys = [
        key for key in enabled
        if not engine.STAGES_BY_KEY[key].derived
        and repository.user_is_stage_member(project_id, user["id"], key)
    ]
    if not stage_keys:
        return []
    cases = repository.list_cases(project_id)
    matrix = _status_matrix(repository, project_id, enabled, cases)
    items = []
    for case in cases:
        row = matrix[case.id]
        statuses = {key: value["status"] for key, value in row.items()}
        for key in stage_keys:
            cell = row[key]
            mine = cell["assigned_user_id"] == user["id"]
            claimable = (
                cell["status"] in (engine.PENDING, engine.REJECTED)
                and cell["assigned_user_id"] in (None, user["id"])
                and engine.is_available(key, statuses, enabled)
            )
            if claimable or (cell["status"] == engine.IN_PROGRESS and mine):
                items.append({
                    "case_id": case.id,
                    "case_key": case.case_key,
                    "display_name": case.display_name,
                    "stage_key": key,
                    "status": cell["status"],
                })
    return items
