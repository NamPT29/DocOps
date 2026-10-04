from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from server.database import get_db
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
    limit: int = 100,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": list_action_needed_cases(db, project_id=project_id, limit=limit),
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
    return {
        "status": "ok",
        "data": hard_delete_project_pdf(
            db,
            project_id=project_id,
            asset_id=asset_id,
            deleted_by_user_id=current_user["id"],
        ),
    }
