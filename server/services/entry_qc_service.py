from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from server.repositories.entry_qc_repository import EntryQcRepository
from server.services.project_policy_service import get_effective_policy
from server.services.workflow_engine import derive_entry_statuses, DONE
from server.models import get_utc_now, Submission, SubmissionQualityAssessment
from server.services.submission_quality_service import SubmissionQualityService
from server.models_entry_qc import CaseEntryQcResult, CaseEntryQcSampling, CaseEntryQcSampleItem
from server.repositories.workflow_repository import WorkflowRepository
import math
import secrets
import random
import json
from sqlalchemy.exc import IntegrityError
from server.models import ProjectReportUnit
from server.repositories.document_repository import DocumentRepository
from server.services.submission_quality_service import _visible_schema_fields, _effective_project_config
from server.services.submission_helpers import create_document_file_response
from server.settings import settings

def _user_display_name(user):
    if not user:
        return None
    return user.full_name if user.full_name else user.username

def check_entry_qc_gate(db, project_id, case_id):
    repo = EntryQcRepository(db)
    existing_rounds = repo.get_rounds(case_id)
    round1 = next((r for r in existing_rounds if r.round == 1), None)
    if not round1:
        return {"blocked": True, "code": "entry_qc_not_finalized", "message": "Hộp chưa chốt kết quả Check nhập liệu."}
    if not round1.passed and round1.resolution != "approved":
        return {"blocked": True, "code": "entry_qc_failed", "message": f"Hộp không đạt ngưỡng lỗi: {float(round1.rate_percent)}% (cần dưới {float(round1.threshold_percent)}%). Cần Admin duyệt kèm lý do."}
        
    policy = get_effective_policy(db, project_id=project_id)
    if policy.get("entry_qc_round2_enabled", True):
        sampling = repo.get_sampling(case_id, 2)
        if not sampling:
            return {"blocked": True, "code": "entry_qc_round2_required", "message": "Hộp chưa làm Check nhập vòng 2."}
            
        round2 = next((r for r in existing_rounds if r.round == 2), None)
        if not round2:
            return {"blocked": True, "code": "entry_qc_round2_pending", "message": "Check nhập vòng 2 chưa chốt."}
            
        if not round2.passed and round2.resolution != "approved":
            return {"blocked": True, "code": "entry_qc_round2_failed", "message": f"Vòng 2 không đạt ngưỡng lỗi: {float(round2.rate_percent)}% (cần dưới {float(round2.threshold_percent)}%). Cần Admin duyệt kèm lý do."}

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
    
    policy = get_effective_policy(db, project_id=project_id)
    
    live = None
    if total_fields > 0:
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

    # 4. Round 2
    round2_payload = {"enabled": policy.get("entry_qc_round2_enabled", True), "sampling": None}
    
    sampling = repo.get_sampling(case_id, 2)
    if sampling:
        items = []
        for row, report_name in repo.get_sample_items_with_info(sampling.id):
            items.append({
                "submission_id": row.submission_id,
                "report_name": report_name,
                "checked": row.checked_at is not None,
                "checked_by_name": _user_display_name(row.checked_by) if row.checked_at else None,
                "changed_field_count": row.changed_field_count,
                "visible_field_count": row.visible_field_count
            })
        round2_payload["sampling"] = {
            "sample_rate_percent": float(sampling.sample_rate_percent),
            "population_count": sampling.population_count,
            "sample_size": sampling.sample_size,
            "created_at": sampling.created_at.isoformat(),
            "created_by_name": _user_display_name(sampling.created_by),
            "items": items
        }
        
    return {
        "gate": check_entry_qc_gate(db, project_id, case_id),
        "entry_qc_status": entry_qc_status,
        "live": live,
        "rounds": rounds,
        "round2": round2_payload
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

def _resolve_round(db, project_id, case_id, actor, reason: str, round_no: int):
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
    round_obj = next((r for r in existing_rounds if r.round == round_no), None)
    
    if not round_obj:
        raise HTTPException(status_code=409, detail={"code": "not_finalized", "message": "Chưa chốt kết quả Check nhập liệu."})
    
    if round_obj.passed:
        raise HTTPException(status_code=409, detail={"code": "not_failed", "message": "Vòng kiểm tra đã Đạt, không cần duyệt."})
        
    if round_obj.resolution:
        raise HTTPException(status_code=409, detail={"code": "already_resolved", "message": "Hộp đã được duyệt."})
        
    round_obj.resolution = "approved"
    round_obj.resolution_reason = reason.strip()
    round_obj.resolved_by_user_id = actor["id"]
    round_obj.resolved_at = get_utc_now()
    
    db.commit()
    
    resolver_name = actor.get("full_name") or actor.get("username")
    return {
        "resolution": round_obj.resolution,
        "resolution_reason": round_obj.resolution_reason,
        "resolved_by_name": resolver_name,
        "resolved_at": round_obj.resolved_at.isoformat()
    }

def resolve_round1(db, project_id, case_id, actor, reason: str):
    return _resolve_round(db, project_id, case_id, actor, reason, 1)

def resolve_round2(db, project_id, case_id, actor, reason: str):
    return _resolve_round(db, project_id, case_id, actor, reason, 2)


def sample_round2(db, project_id, case_id, actor):
    repo = EntryQcRepository(db)
    _check_permission(db, project_id, case_id, actor)

    policy = get_effective_policy(db, project_id=project_id)
    if not policy.get("entry_qc_round2_enabled", True):
        raise HTTPException(
            status_code=409, detail={"code": "round2_disabled", "message": "Dự án không bật Check vòng 2."}
        )

    existing_rounds = repo.get_rounds(case_id)
    round1 = next((r for r in existing_rounds if r.round == 1), None)
    if not round1 or (not round1.passed and round1.resolution != "approved"):
        raise HTTPException(
            status_code=409, detail={"code": "round1_not_passed", "message": "Cần xong vòng 1 trước khi lấy mẫu."}
        )

    if repo.get_sampling(case_id, 2):
        raise HTTPException(
            status_code=409, detail={"code": "already_sampled", "message": "Hộp đã được lấy mẫu vòng 2."}
        )

    completed_submissions = repo.get_completed_submissions(project_id, case_id)
    population = len(completed_submissions)
    if population == 0:
        raise HTTPException(
            status_code=409, detail={"code": "no_submissions", "message": "Hộp không có phiếu nào để lấy mẫu."}
        )

    rate = policy["sample_rate_percent"]
    sample_size = math.ceil(population * float(rate) / 100.0)
    sample_size = max(1, min(sample_size, population))

    seed = secrets.randbits(63)
    sorted_ids = sorted(s.id for s in completed_submissions)
    sampled_ids = set(random.Random(seed).sample(sorted_ids, sample_size))

    sampling = CaseEntryQcSampling(
        project_id=project_id,
        case_id=case_id,
        round=2,
        population_count=population,
        sample_size=sample_size,
        sample_rate_percent=rate,
        seed=seed,
        created_by_user_id=actor["id"]
    )
    repo.add_sampling(sampling)
    
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "already_sampled", "message": "Hộp đã được lấy mẫu vòng 2."}
        )

    items = []
    for sub in completed_submissions:
        if sub.id in sampled_ids:
            items.append(CaseEntryQcSampleItem(
                sampling_id=sampling.id,
                submission_id=sub.id,
                baseline_data_json=sub.data_json
            ))
    repo.add_sample_items(items)
    db.commit()
    return {"message": "Đã lấy mẫu vòng 2."}

def _check_round2_item_access(db, project_id, case_id, submission_id, actor):
    repo = EntryQcRepository(db)
    _check_permission(db, project_id, case_id, actor)

    sampling = repo.get_sampling(case_id, 2)
    if not sampling:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Không tìm thấy mẫu."})

    item = repo.get_sample_item(case_id, 2, submission_id)
    if not item:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Phiếu không thuộc mẫu của hộp này."})

    submission = repo.get_submission(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Không tìm thấy phiếu."})
        
    if submission.created_by_user_id == actor["id"]:
        raise HTTPException(status_code=409, detail={"code": "self_review", "message": "Người check nhập liệu không được trùng người nhập liệu."})

    assessment = repo.get_quality_assessment(submission_id)
    if assessment and assessment.reviewer_user_id == actor["id"]:
        raise HTTPException(status_code=409, detail={"code": "self_review", "message": "Người check vòng 2 không được trùng người đã duyệt vòng 1."})
        
    return repo, item, submission

def check_round2_item(db, project_id, case_id, submission_id, request_data: dict, actor):
    repo, item, submission = _check_round2_item_access(db, project_id, case_id, submission_id, actor)
    
    # Needs a separate lock for update
    item = repo.get_sample_item_for_update(case_id, 2, submission_id)

    if item.checked_at is not None:
        raise HTTPException(status_code=409, detail={"code": "already_checked", "message": "Phiếu này đã được check."})

    if submission.status != 'completed':
        raise HTTPException(status_code=409, detail={"code": "submission_changed", "message": "Phiếu đã thay đổi trạng thái."})

    existing_rounds = repo.get_rounds(case_id)
    if any(r.round == 2 for r in existing_rounds):
        raise HTTPException(status_code=409, detail={"code": "round2_finalized", "message": "Vòng kiểm tra này đã được chốt kết quả."})

    current = json.loads(submission.data_json or "{}")
    
    final_data = dict(current)
    for k, v in request_data.items():
        if isinstance(k, str) and not k.startswith("_"):
            final_data[k] = v
            
    visible_count, changed_count = SubmissionQualityService.count_field_changes(db, submission, current, final_data)

    item.final_data_json = json.dumps(final_data, ensure_ascii=False)
    item.visible_field_count = visible_count
    item.changed_field_count = changed_count
    item.checked_by_user_id = actor["id"]
    item.checked_at = get_utc_now()

    sub_data = json.loads(submission.data_json or "{}")
    for k, v in request_data.items():
        if isinstance(k, str) and not k.startswith("_"):
            sub_data[k] = v
    submission.data_json = json.dumps(sub_data, ensure_ascii=False)

    db.commit()
    return {"message": "Đã lưu kết quả check."}

def get_round2_item(db, project_id, case_id, submission_id, actor):
    repo, item, submission = _check_round2_item_access(db, project_id, case_id, submission_id, actor)
    
    current = json.loads(submission.data_json or "{}")
    final_data = json.loads(item.final_data_json or "{}") if item.checked_at else None
    
    project = repo.get_project(project_id)
    try:
        schema = json.loads(project.form_schema_json_snapshot or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        schema = []
        
    config = _effective_project_config(db, project)
    fields = _visible_schema_fields(schema, config)
    
    for f in fields:
        name = f["name"]
        if item.checked_at:
            f["value"] = final_data.get(name)
        else:
            f["value"] = current.get(name)
    
    report_name = repo.get_report_name(submission.assigned_document_id)
    
    return {
        "submission_id": item.submission_id,
        "report_name": report_name,
        "checked": item.checked_at is not None,
        "checked_by_name": _user_display_name(item.checked_by) if item.checked_at else None,
        "changed_field_count": item.changed_field_count,
        "visible_field_count": item.visible_field_count,
        "fields": fields,
        "pdf_url": f"/api/projects/{project_id}/workflow/cases/{case_id}/entry-qc/round2/items/{submission_id}/pdf"
    }

def get_round2_item_pdf(db, project_id, case_id, submission_id, actor):
    repo, item, submission = _check_round2_item_access(db, project_id, case_id, submission_id, actor)
    
    document = DocumentRepository(db).get(submission.assigned_document_id)
    if not document:
        raise HTTPException(status_code=404, detail="File không tồn tại")
        
    return create_document_file_response(document, str(settings.pdf_storage_path))

def finalize_round2(db, project_id, case_id, actor):
    repo = EntryQcRepository(db)
    _check_permission(db, project_id, case_id, actor)

    if repo.has_submission_by_user(project_id, case_id, actor["id"]):
        raise HTTPException(
            status_code=409, 
            detail={"code": "self_review", "message": "Người chốt không được trùng người nhập liệu (của bất kỳ báo cáo nào trong hộp)."}
        )

    sampling = repo.get_sampling(case_id, 2)
    if not sampling:
        raise HTTPException(status_code=409, detail={"code": "not_sampled", "message": "Hộp chưa được lấy mẫu vòng 2."})

    existing_rounds = repo.get_rounds(case_id)
    if any(r.round == 2 for r in existing_rounds):
        raise HTTPException(status_code=409, detail={"code": "already_finalized", "message": "Vòng kiểm tra này đã được chốt kết quả."})

    items = repo.get_sample_items(sampling.id)
    unchecked_count = sum(1 for item in items if item.checked_at is None)
    if unchecked_count > 0:
        raise HTTPException(status_code=409, detail={"code": "items_unchecked", "message": f"Còn {unchecked_count} phiếu chưa check."})

    total_fields = sum(item.visible_field_count or 0 for item in items)
    if total_fields == 0:
        raise HTTPException(status_code=409, detail={"code": "no_fields", "message": "Không có trường dữ liệu nào để tính tỷ lệ lỗi."})

    error_fields = sum(item.changed_field_count or 0 for item in items)
    error_reports = sum(1 for item in items if (item.changed_field_count or 0) > 0)

    policy = get_effective_policy(db, project_id=project_id)
    threshold = policy["error_threshold_percent"]
    rate = (Decimal(error_fields) * 100 / Decimal(total_fields)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    row = CaseEntryQcResult(
        project_id=project_id,
        case_id=case_id,
        round=2,
        reports_total=sampling.population_count,
        reports_assessed=sampling.sample_size,
        error_reports=error_reports,
        total_fields=total_fields,
        error_fields=error_fields,
        rate_percent=rate,
        threshold_percent=threshold,
        passed=bool(rate < threshold),
        created_by_user_id=actor["id"]
    )
    repo.add_round(row)
    db.commit()

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
        "created_by_name": actor.get("full_name") or actor.get("username")
    }
