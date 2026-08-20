from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.database import get_db
from server.routers.auth import get_admin_user, get_current_user
from server.services.project_service import create_project, list_projects
from server.services.project_admin_service import (
    hard_delete_project_pdf,
    list_project_assets,
    update_project_members,
)
from server.services.project_workspace_service import get_project_workspace


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


@router.get("/{project_id}/workspace")
def api_get_project_workspace(
    project_id: int,
    current_user: dict = Depends(get_current_user),
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
