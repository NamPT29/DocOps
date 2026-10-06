from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from server.repositories.entry_qc_repository import EntryQcRepository
from server.services.project_policy_service import get_effective_policy
from server.services.workflow_engine import derive_entry_statuses, DONE
from server.models import get_utc_now
from server.models_entry_qc import CaseEntryQcResult
from server.repositories.workflow_repository import WorkflowRepository

def _user_display_name(user):
    if not user:
        return None
    return user.full_name if user.full_name else user.username

def check_entry_qc_gate(db, case_id):
    repo = EntryQcRepository(db)
    existing_rounds = repo.get_rounds(case_id)
    round1 = next((r for r in existing_rounds if r.round == 1), None)
    if not round1:
        return {"blocked": True, "code": "entry_qc_not_finalized", "message": "Hộp chưa chốt kết quả Check nhập liệu."}
    if not round1.passed and round1.resolution != "approved":
        return {"blocked": True, "code": "entry_qc_failed", "message": f"Hộp không đạt ngưỡng lỗi: {float(round1.rate_percent)}% (cần dưới {float(round1.threshold_percent)}%). Cần Admin duyệt kèm lý do."}
    return {"blocked": False, "code": None, "message": None}

def _check_permission(db, project_id, case_id, actor):
    workflow_repo = WorkflowRepository(db)
    case = workflow_repo.get_case(project_id, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
        
    if actor.get("role") != "admin":
        if not workflow_repo.user_has_legacy_role(project_id, actor["id"], "reviewer"):
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Bạn không có quyền thực hiện bước này."})

def get_entry_qc_summary(db, project_id, case_id, actor):
    _check_permission(db, project_id, case_id, actor)
    repo = EntryQcRepository(db)
    
    # 1. Workflow Status
    progress = repo.get_progress(project_id, case_id)
    statuses = derive_entry_statuses(**progress)
    entry_qc_status = statuses["entry_qc"]
    
    # 2. Live Quality Stats
    stats = repo.get_quality_stats(project_id, case_id)
    total_fields = stats["total_fields"]
    error_fields = stats["error_fields"]
    
    live = None
    if total_fields > 0:
        policy = get_effective_policy(db, project_id=project_id)
        threshold = policy["error_threshold_percent"]
        rate = (Decimal(error_fields) * 100 / Decimal(total_fields)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        live = {
            "reports_total": progress["report_total"],
            "reports_assessed": stats["reports_assessed"],
            "error_reports": stats["error_reports"],
            "total_fields": total_fields,
            "error_fields": error_fields,
            "rate_percent": float(rate),
            "threshold_percent": float(threshold),
            "would_pass": rate < threshold
        }
    
    # 3. Previous Rounds
    rounds = []
    for r in repo.get_rounds(case_id):
        creator_name = _user_display_name(r.created_by)
        rounds.append({
            "round": r.round,
            "reports_total": r.reports_total,
            "reports_assessed": r.reports_assessed,
            "error_reports": r.error_reports,
            "total_fields": r.total_fields,
            "error_fields": r.error_fields,
            "rate_percent": float(r.rate_percent),
            "threshold_percent": float(r.threshold_percent),
            "passed": r.passed,
            "resolution": r.resolution,
            "resolution_reason": r.resolution_reason,
            "resolved_by_name": _user_display_name(r.resolved_by),
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "created_at": r.created_at.isoformat(),
            "created_by_name": creator_name
        })
        
    return {
        "gate": check_entry_qc_gate(db, case_id),
        "entry_qc_status": entry_qc_status,
        "live": live,
        "rounds": rounds
    }

def finalize_round1(db, project_id, case_id, actor):
    repo = EntryQcRepository(db)
    
    _check_permission(db, project_id, case_id, actor)
    
    # Validation 2: Self-review
    if repo.has_submission_by_user(project_id, case_id, actor["id"]):
        raise HTTPException(
            status_code=409, 
            detail={"code": "self_review", "message": "Người check nhập liệu không được trùng người nhập liệu (của bất kỳ báo cáo nào trong hộp)."}
        )
    
    # Validation 3: entry_qc must be DONE
    progress = repo.get_progress(project_id, case_id)
    statuses = derive_entry_statuses(**progress)
    if statuses["entry_qc"] != DONE:
        raise HTTPException(
            status_code=409,
            detail={"code": "entry_qc_not_done", "message": "Hộp chưa hoàn tất kiểm tra nhập liệu."}
        )
    
    # Validation 4: Round 1 already finalized?
    existing_rounds = repo.get_rounds(case_id)
    if any(r.round == 1 for r in existing_rounds):
        raise HTTPException(
            status_code=409,
            detail={"code": "already_finalized", "message": "Vòng kiểm tra này đã được chốt kết quả."}
        )
    
    stats = repo.get_quality_stats(project_id, case_id)
    total_fields = stats["total_fields"]
    if total_fields == 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "no_fields", "message": "Hộp không có trường dữ liệu nào để tính tỷ lệ lỗi."}
        )
        
    policy = get_effective_policy(db, project_id=project_id)
    threshold = policy["error_threshold_percent"]
    rate = (Decimal(stats["error_fields"]) * 100 / Decimal(total_fields)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    row = CaseEntryQcResult(
        project_id=project_id,
        case_id=case_id,
        round=1,
        reports_total=progress["report_total"],
        reports_assessed=stats["reports_assessed"],
        error_reports=stats["error_reports"],
        total_fields=total_fields,
        error_fields=stats["error_fields"],
        rate_percent=rate,
        threshold_percent=threshold,
        passed=bool(rate < threshold),
        created_by_user_id=actor["id"]
    )
    repo.add_round(row)
    db.commit()
    
    # Return same structure as a round object in GET
    creator_name = actor.get("full_name") or actor.get("username")
    return {
        "round": row.round,
        "reports_total": row.reports_total,
        "reports_assessed": row.reports_assessed,
        "error_reports": row.error_reports,
        "total_fields": row.total_fields,
        "error_fields": row.error_fields,
        "rate_percent": float(row.rate_percent),
        "threshold_percent": float(row.threshold_percent),
        "passed": row.passed,
        "created_at": row.created_at.isoformat(),
        "created_by_name": creator_name
    }

def resolve_round1(db, project_id, case_id, actor, reason: str):
    _check_permission(db, project_id, case_id, actor)
    if actor.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Bạn không có quyền thực hiện bước này."})
    
    if not str(reason or "").strip():
        raise HTTPException(status_code=409, detail={"code": "reason_required", "message": "Cần nêu lý do khi duyệt."})
        
    repo = EntryQcRepository(db)
    
    if repo.has_submission_by_user(project_id, case_id, actor["id"]):
        raise HTTPException(
            status_code=409, 
            detail={"code": "self_review", "message": "Người check nhập liệu không được trùng người nhập liệu (của bất kỳ báo cáo nào trong hộp)."}
        )

    existing_rounds = repo.get_rounds(case_id)
    round1 = next((r for r in existing_rounds if r.round == 1), None)
    
    if not round1:
        raise HTTPException(status_code=409, detail={"code": "not_finalized", "message": "Chưa chốt kết quả Check nhập liệu."})
    
    if round1.passed:
        raise HTTPException(status_code=409, detail={"code": "not_failed", "message": "Vòng kiểm tra đã Đạt, không cần duyệt."})
        
    if round1.resolution:
        raise HTTPException(status_code=409, detail={"code": "already_resolved", "message": "Hộp đã được duyệt."})
        
    round1.resolution = "approved"
    round1.resolution_reason = reason.strip()
    round1.resolved_by_user_id = actor["id"]
    round1.resolved_at = get_utc_now()
    
    db.commit()
    
    resolver_name = actor.get("full_name") or actor.get("username")
    return {
        "resolution": round1.resolution,
        "resolution_reason": round1.resolution_reason,
        "resolved_by_name": resolver_name,
        "resolved_at": round1.resolved_at.isoformat()
    }
