from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from server.database import get_db, get_utc_now
from server.routers.auth import get_admin_user, get_current_user
from server.routers.project_access import get_project_input_member
from server.services.project_service import create_project, list_projects, update_project_status
from server.services.project_admin_service import (
    delete_project,
    hard_delete_project_pdf,
    list_project_assets,
    update_project_members,
)
from server.services.project_policy_service import get_project_policy, update_project_policy
from server.services.normalization_plan_service import ascii_name, build_plan, plan_workbook
from server.services.project_dashboard_service import build_dashboard
from server.services.reconciliation_service import build_reconciliation, reconciliation_workbook
from server.services.handover_lock_service import ensure_project_editable, lock_project, unlock_project
from server.services.payroll_service import compute_payroll, get_rates, parse_period, payroll_workbook, update_rates
from server.services.payroll_period_service import create_period, delete_period, list_periods, period_workbook
from server.services.handover_package_service import read_job, report_path, start_package
from server.services.project_workspace_service import get_project_workspace
from server.services.export_job_service import (
    ExportJobBusyError,
    public_export_job,
    start_export_job,
)
from server.services.project_assignment_service import (
    assign_case_input,
    list_action_needed_cases,
    revoke_case_input,
)
from server.services.api_rate_limit_service import enforce_heavy_api_rate_limit
from server.services.project_reporting_service import (
    get_project_or_404,
    get_project_submissions,
    list_project_submission_folders,
    resolve_project_template_path,
)


router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    name: str | None = None
    root_folder_name: str
    template_id: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    case_level: int
    report_mode: Literal["folder_level", "pdf"]
    report_level: int | None = None
    input_user_ids: list[int] = Field(default_factory=list)
    reviewer_user_ids: list[int] = Field(default_factory=list)


class ProjectMembersUpdateRequest(BaseModel):
    input_user_ids: list[int] = Field(default_factory=list)
    reviewer_user_ids: list[int] = Field(default_factory=list)


class ProjectStatusUpdateRequest(BaseModel):
    status: Literal["new", "in_progress", "completed", "overdue"]


class CaseAssignInputRequest(BaseModel):
    user_id: int


class CaseRevokeInputRequest(BaseModel):
    reason: str
    note: str | None = None
    new_user_id: int | None = None


@router.post("")
def api_create_project(
    request: ProjectCreateRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    project = create_project(
        db,
        name=request.name,
        root_folder_name=request.root_folder_name,
        template_id=request.template_id,
        start_date=request.start_date,
        end_date=request.end_date,
        case_level=request.case_level,
        report_mode=request.report_mode,
        report_level=request.report_level,
        input_user_ids=request.input_user_ids,
        reviewer_user_ids=request.reviewer_user_ids,
        created_by_user_id=current_user["id"],
    )
    return {"status": "ok", "project_id": project.id}


@router.get("")
def api_list_projects(
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": list_projects(db, current_user=current_user)}


@router.get("/mine")
def api_list_my_projects(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": list_projects(db, current_user=current_user)}


@router.get("/action-needed-cases")
def api_list_action_needed_cases(
    project_id: int | None = None,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": list_action_needed_cases(db, project_id=project_id),
    }


@router.post("/{project_id}/cases/{case_id}/assign-input")
def api_assign_case_input(
    project_id: int,
    case_id: int,
    request: CaseAssignInputRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return assign_case_input(
        db,
        project_id=project_id,
        case_id=case_id,
        user_id=request.user_id,
        actor_user_id=current_user["id"],
    )


@router.post("/{project_id}/cases/{case_id}/revoke-input")
def api_revoke_case_input(
    project_id: int,
    case_id: int,
    request: CaseRevokeInputRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return revoke_case_input(
        db,
        project_id=project_id,
        case_id=case_id,
        reason_code=request.reason,
        note=request.note,
        new_user_id=request.new_user_id,
        actor_user_id=current_user["id"],
    )


@router.put("/{project_id}")
@router.put("/{project_id}/status")
def api_update_project_status(
    project_id: int,
    request: ProjectStatusUpdateRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": update_project_status(
            db,
            project_id=project_id,
            status=request.status,
        ),
    }


@router.delete("/{project_id}")
def api_delete_project(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": delete_project(db, project_id=project_id),
    }


@router.get("/{project_id}/normalization-plan")
def api_get_normalization_plan(
    project_id: int,
    format: Literal["xlsx", "json"] = "xlsx",
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Kế hoạch chuẩn hóa (G1, chỉ đọc): mã hồ sơ, mã văn bản, đường dẫn bàn giao QC-03/QC-04."""
    plan = build_plan(db, project_id=project_id)
    if format == "json":
        return {"status": "ok", "data": {key: plan[key] for key in ("project", "organ_code", "root", "summary")}}
    filename = f"Ke_hoach_chuan_hoa_{ascii_name(plan['project']['name']) or project_id}.xlsx"
    return Response(
        content=plan_workbook(plan),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class WorkRatesRequest(BaseModel):
    rates: dict[str, Any]


@router.get("/{project_id}/work-rates")
def api_get_work_rates(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Đơn giá loại 1 (P1); loại 2 = loại 1 × hệ số giấy xấu của Chính sách dự án."""
    return {"status": "ok", "data": get_rates(db, project_id=project_id)}


@router.put("/{project_id}/work-rates")
def api_update_work_rates(
    project_id: int,
    request: WorkRatesRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": update_rates(db, project_id=project_id, rates=request.rates, actor=current_user)}


@router.get("/{project_id}/payroll-preview")
def api_get_payroll_preview(
    project_id: int,
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    format: Literal["json", "xlsx"] = "json",
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Bảng tạm tính chi trả theo sản lượng (P1, không lưu)."""
    start, end = parse_period(date_from, date_to)
    result = compute_payroll(db, project_id=project_id, date_from=start, date_to=end)
    if format == "json":
        return {"status": "ok", "data": result}
    filename = f"Tam_tinh_chi_tra_{project_id}_{start.isoformat()}_{end.isoformat()}.xlsx"
    return Response(
        content=payroll_workbook(result),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class PayrollPeriodRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date_from: str = Field(alias="from")
    date_to: str = Field(alias="to")


@router.post("/{project_id}/payroll-periods")
def api_create_payroll_period(
    project_id: int,
    request: PayrollPeriodRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Chốt kỳ chi trả (P2): tính như tạm tính rồi lưu kèm tham số."""
    return {"status": "ok", "data": create_period(
        db, project_id=project_id, date_from=request.date_from, date_to=request.date_to, actor=current_user,
    )}


@router.get("/{project_id}/payroll-periods")
def api_list_payroll_periods(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": list_periods(db, project_id=project_id)}


@router.get("/{project_id}/payroll-periods/{period_id}.xlsx")
def api_download_payroll_period(
    project_id: int,
    period_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Excel của kỳ đã chốt: đúng số đã lưu, không tính lại."""
    content, result = period_workbook(db, project_id=project_id, period_id=period_id)
    period = result["period"]
    filename = f"Chi_tra_{project_id}_{period['from']}_{period['to']}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{project_id}/payroll-periods/{period_id}")
def api_delete_payroll_period(
    project_id: int,
    period_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": delete_period(db, project_id=project_id, period_id=period_id)}


class HandoverLockRequest(BaseModel):
    note: str | None = None


class HandoverUnlockRequest(BaseModel):
    reason: str | None = None


@router.post("/{project_id}/handover-lock")
def api_lock_project_handover(
    project_id: int,
    request: HandoverLockRequest | None = None,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Khóa sửa hồ sơ sau bàn giao (K1): cần một lần đóng gói bàn giao đã xong."""
    note = request.note if request else None
    return {"status": "ok", "data": lock_project(db, project_id=project_id, note=note, actor=current_user)}


@router.delete("/{project_id}/handover-lock")
def api_unlock_project_handover(
    project_id: int,
    request: HandoverUnlockRequest | None = None,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Mở khóa bàn giao (K1): bắt buộc lý do, ghi nhật ký audit."""
    reason = request.reason if request else None
    return {"status": "ok", "data": unlock_project(db, project_id=project_id, reason=reason, actor=current_user)}


@router.get("/{project_id}/reconciliation")
def api_get_reconciliation(
    project_id: int,
    format: Literal["xlsx", "json"] = "xlsx",
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Đối soát R1–R4 (chỉ đọc; giả định reviewer, chờ đối chiếu BA)."""
    report = build_reconciliation(db, project_id=project_id)
    if format == "json":
        return {"status": "ok", "data": {"project": report["project"], "summary": report["summary"]}}
    filename = f"Doi_soat_{ascii_name(report['project']['name']) or project_id}.xlsx"
    return Response(
        content=reconciliation_workbook(report),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/dashboard")
def api_get_project_dashboard(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Bảng tiến độ dự án (D1, chỉ đọc): hộp theo bước, văn bản, sản lượng 14 ngày, dự kiến xong."""
    return {"status": "ok", "data": build_dashboard(db, project_id, get_utc_now())}


@router.post("/{project_id}/handover-package")
def api_start_handover_package(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Đóng gói bàn giao (G2): chép file theo kế hoạch chuẩn hóa, SHA-256, metadata NN-SIP; chạy nền."""
    from server.database import SessionLocal

    job = start_package(db, project_id=project_id, current_user=current_user, session_factory=SessionLocal)
    return {"status": "ok", "data": job}


@router.get("/{project_id}/handover-package")
def api_get_handover_package(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
):
    return {"status": "ok", "data": read_job(project_id) or {"project_id": project_id, "state": "none"}}


@router.get("/{project_id}/handover-package/report")
def api_download_handover_report(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
):
    """Biên bản bàn giao (G3) của lần đóng gói xong gần nhất."""
    return FileResponse(
        report_path(project_id),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"Bien_ban_ban_giao_du_an_{project_id}.docx",
    )


@router.get("/{project_id}/submission-folders")
def api_list_project_submission_folders(
    project_id: int,
    view: Literal["review", "completed"],
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": list_project_submission_folders(
            db,
            project_id=project_id,
            view=view,
        ),
    }


@router.get("/{project_id}/submissions")
def api_list_project_submissions(
    project_id: int,
    view: Literal["review", "completed"],
    folder_path: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": get_project_submissions(
            db,
            project_id=project_id,
            view=view,
            folder_path=folder_path,
            page=page,
            page_size=page_size,
        ),
    }


@router.post("/{project_id}/export-jobs", status_code=202)
def api_start_project_export_job(
    project_id: int,
    include_pending_review: bool = False,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    enforce_heavy_api_rate_limit("project-export", current_user["id"], cost=30)
    project = get_project_or_404(db, project_id)
    snapshot_path = resolve_project_template_path(project)
    try:
        job = start_export_job(
            template_id=project.template_id,
            extension=snapshot_path.suffix.casefold(),
            include_pending_review=include_pending_review,
            folder_path=None,
            start_date=None,
            end_date=None,
            requested_by_user_id=current_user["id"],
            project_id=project.id,
        )
    except ExportJobBusyError as exc:
        detail = "Một tác vụ xuất khác đang chạy. Vui lòng chờ tác vụ hiện tại hoàn tất."
        if exc.job_id:
            detail += f" Mã tác vụ: {exc.job_id}"
        raise HTTPException(status_code=409, detail=detail) from exc
    return {"status": "ok", "job": public_export_job(job)}


@router.get("/{project_id}/workspace")
def api_get_project_workspace(
    project_id: int,
    current_user: dict = Depends(get_project_input_member),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": get_project_workspace(
            db,
            project_id=project_id,
            current_user=current_user,
        ),
    }


@router.put("/{project_id}/members")
def api_update_project_members(
    project_id: int,
    request: ProjectMembersUpdateRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": update_project_members(
            db,
            project_id=project_id,
            input_user_ids=request.input_user_ids,
            reviewer_user_ids=request.reviewer_user_ids,
            changed_by_user_id=current_user["id"],
        ),
    }


class ProjectPolicyRequest(BaseModel):
    """Every project setting; null or empty = follow QC-01 (FR-PRJ-03).

    Values stay loosely typed so the service reports range and format errors
    in Vietnamese, field by field.
    """

    model_config = ConfigDict(extra="forbid")

    error_threshold_percent: Any = None
    sample_rate_percent: Any = None
    box_deadline_days: Any = None
    organ_code: Any = None
    file_notation: Any = None
    export_profile: Any = None
    bad_paper_factor: Any = None
    overtime_factor: Any = None
    sunday_factor: Any = None
    entry_qc_round2_enabled: Any = None


@router.get("/{project_id}/policy")
def api_get_project_policy(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": get_project_policy(db, project_id=project_id)}


@router.put("/{project_id}/policy")
def api_update_project_policy(
    project_id: int,
    request: ProjectPolicyRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": update_project_policy(
            db,
            project_id=project_id,
            values=request.model_dump(),
            actor_user_id=current_user["id"],
        ),
    }


@router.get("/{project_id}/assets")
def api_list_project_assets(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": list_project_assets(db, project_id=project_id)}


@router.delete("/{project_id}/assets/{asset_id}")
def api_delete_project_asset(
    project_id: int,
    asset_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    ensure_project_editable(db, project_id)
    return {
        "status": "ok",
        "data": hard_delete_project_pdf(
            db,
            project_id=project_id,
            asset_id=asset_id,
            deleted_by_user_id=current_user["id"],
        ),
    }


class ScanPackageCreateRequest(BaseModel):
    folder_path: str
    scan_user_name_level: int = 1


@router.post("/{project_id}/cases/{case_id}/scan-packages")
def api_create_scan_package(
    project_id: int,
    case_id: int,
    request: ScanPackageCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.services.scan_ingestion_service import submit_scan_package, process_scan_package_background
    from server.services.workflow_service import enforce_can_create_scan_package

    enforce_can_create_scan_package(db, project_id, current_user)

    pkg = submit_scan_package(
        db,
        project_id=project_id,
        case_id=case_id,
        folder_path=request.folder_path,
        scan_user_name_level=request.scan_user_name_level,
        actor=current_user,
    )
    
    background_tasks.add_task(process_scan_package_background, pkg.id)
    
    return {"status": "ok", "package_id": pkg.id}


@router.get("/{project_id}/cases/{case_id}/scan-packages")
def api_list_scan_packages(
    project_id: int,
    case_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.repositories.scan_repository import get_case_by_id, list_scan_packages
    from server.services.workflow_service import enforce_can_view_scan_packages
    import json
    
    enforce_can_view_scan_packages(db, project_id, current_user)

    case = get_case_by_id(db, project_id, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Hộp không thuộc dự án này hoặc không tồn tại.")
    
    packages = list_scan_packages(db, case_id)
    return {
        "status": "ok",
        "data": [
            {
                "id": p.id,
                "version": p.version,
                "status": p.status,
                "scanned_by_name": p.scanned_by_name,
                "total_files": p.total_files,
                "processed_files": p.processed_files,
                "failed_files": p.failed_files,
                "total_pages": p.total_pages,
                "total_a4_equivalent": p.total_a4_equivalent,
                "warning_flags": json.loads(p.warning_flags) if p.warning_flags else [],
                "error_message": p.error_message,
                "started_at": p.started_at,
                "finished_at": p.finished_at,
                "match_status": p.match_status,
                "match_summary": json.loads(p.match_summary) if p.match_summary else None,
            }
            for p in packages
        ]
    }
