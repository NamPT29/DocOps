from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.database import get_db
from server.routers.auth import get_admin_user, get_current_user
from server.services import project_assignment_service, workflow_service

router = APIRouter(prefix="/api/projects/{project_id}/workflow", tags=["workflow"])
catalog_router = APIRouter(prefix="/api/workflow", tags=["workflow"])


class WorkflowConfigRequest(BaseModel):
    enabled_stages: list[str]
    members: dict[str, list[int]] = Field(default_factory=dict)


class TransitionRequest(BaseModel):
    action: Literal["start", "complete", "reject", "reopen"]
    reason: str | None = None


class AssignRequest(BaseModel):
    user_id: int | None = None


@catalog_router.get("/stages")
def api_stage_catalog(current_user: dict = Depends(get_current_user)):
    return {"status": "ok", "data": workflow_service.stage_catalog()}


@router.get("")
def api_get_workflow(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.get_workflow_config(db, project_id=project_id),
    }


@router.put("")
def api_configure_workflow(
    project_id: int,
    request: WorkflowConfigRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.configure_workflow(
            db,
            project_id=project_id,
            enabled_stage_keys=request.enabled_stages,
            members=request.members,
            actor_user_id=current_user["id"],
        ),
    }


@router.get("/overview")
def api_workflow_overview(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.get_overview(db, project_id=project_id),
    }


@router.get("/cases")
def api_workflow_cases(
    project_id: int,
    stage_key: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.list_cases(
            db,
            project_id=project_id,
            stage_key=stage_key,
            status=status,
            page=page,
            page_size=page_size,
        ),
    }


@router.get("/my-work")
def api_workflow_my_work(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.list_my_work(db, project_id=project_id, user=current_user),
    }


@router.get("/cases/{case_id}/events")
def api_workflow_case_events(
    project_id: int,
    case_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.list_case_events(
            db, project_id=project_id, case_id=case_id
        ),
    }


@router.post("/cases/{case_id}/stages/{stage_key}/transition")
def api_workflow_transition(
    project_id: int,
    case_id: int,
    stage_key: str,
    request: TransitionRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.transition_case_stage(
            db,
            project_id=project_id,
            case_id=case_id,
            stage_key=stage_key,
            action=request.action,
            actor=current_user,
            reason=request.reason,
        ),
    }


@router.put("/cases/{case_id}/stages/{stage_key}/assignee")
def api_workflow_assign(
    project_id: int,
    case_id: int,
    stage_key: str,
    request: AssignRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": workflow_service.assign_case_stage(
            db,
            project_id=project_id,
            case_id=case_id,
            stage_key=stage_key,
            user_id=request.user_id,
            actor=current_user,
        ),
    }


@router.get("/ready-input-cases")
def api_workflow_ready_input_cases(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": project_assignment_service.list_ready_input_cases(
            db, project_id=project_id
        ),
    }

from server.services import entry_qc_service

@router.get("/cases/{case_id}/entry-qc")
def api_get_entry_qc(
    project_id: int,
    case_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": entry_qc_service.get_entry_qc_summary(db, project_id=project_id, case_id=case_id, actor=current_user)
    }

@router.post("/cases/{case_id}/entry-qc/round1")
def api_finalize_entry_qc_round1(
    project_id: int,
    case_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": entry_qc_service.finalize_round1(db, project_id=project_id, case_id=case_id, actor=current_user)
    }

class EntryQcResolveRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

@router.post("/cases/{case_id}/entry-qc/resolve")
def api_resolve_entry_qc_round1(
    project_id: int,
    case_id: int,
    request: EntryQcResolveRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": entry_qc_service.resolve_round1(db, project_id=project_id, case_id=case_id, actor=current_user, reason=request.reason)
    }

@router.post("/cases/{case_id}/entry-qc/round2/sample")
def api_sample_entry_qc_round2(
    project_id: int,
    case_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": entry_qc_service.sample_round2(db, project_id=project_id, case_id=case_id, actor=current_user)
    }

class EntryQcItemCheckRequest(BaseModel):
    data: dict

@router.put("/cases/{case_id}/entry-qc/round2/items/{submission_id}")
def api_check_entry_qc_round2_item(
    project_id: int,
    case_id: int,
    submission_id: int,
    request: EntryQcItemCheckRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "data": entry_qc_service.check_round2_item(db, project_id=project_id, case_id=case_id, submission_id=submission_id, request_data=request.data, actor=current_user)
    }

@router.get("/cases/{case_id}/entry-qc/round2/items/{submission_id}")
def api_get_entry_qc_round2_item(
    project_id: int,
    case_id: int,
    submission_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import FileResponse
    return {
        "status": "ok",
        "data": entry_qc_service.get_round2_item(db, project_id=project_id, case_id=case_id, submission_id=submission_id, actor=current_user)
    }

@router.get("/cases/{case_id}/entry-qc/round2/items/{submission_id}/pdf")
def api_get_entry_qc_round2_item_pdf(
    project_id: int,
    case_id: int,
    submission_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import FileResponse
    return entry_qc_service.get_round2_item_pdf(db, project_id=project_id, case_id=case_id, submission_id=submission_id, actor=current_user)

@router.post("/cases/{case_id}/entry-qc/round2")
def api_finalize_entry_qc_round2(
    project_id: int,
    case_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": entry_qc_service.finalize_round2(db, project_id=project_id, case_id=case_id, actor=current_user)
    }

@router.post("/cases/{case_id}/entry-qc/round2/resolve")
def api_resolve_entry_qc_round2(
    project_id: int,
    case_id: int,
    request: EntryQcResolveRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": entry_qc_service.resolve_round2(db, project_id=project_id, case_id=case_id, actor=current_user, reason=request.reason)
    }

