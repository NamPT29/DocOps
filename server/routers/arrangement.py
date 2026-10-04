"""Arrangement catalogue (mục lục chỉnh lý) API (FR-ARR-01, QC-16). Admin only."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from server.database import get_db
from server.routers.auth import get_admin_user
from server.services.arrangement_catalog_parser import MAX_CATALOG_BYTES
from server.services.arrangement_catalog_service import (
    get_box_dossiers,
    get_catalog,
    import_catalog,
    preview_catalog,
)

router = APIRouter(prefix="/api/projects", tags=["arrangement"])


def _read_catalog_file(file: UploadFile) -> tuple[str, bytes]:
    name = str(file.filename or "").strip()
    if not name.casefold().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Chỉ nhận file Excel .xlsx (theo mẫu QC-16).")
    content = file.file.read(MAX_CATALOG_BYTES + 1)
    if len(content) > MAX_CATALOG_BYTES:
        raise HTTPException(status_code=413, detail="File mục lục vượt quá 5 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="File mục lục rỗng.")
    return name, content


@router.get("/{project_id}/arrangement/catalog")
def api_get_catalog(
    project_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": get_catalog(db, project_id=project_id)}


@router.get("/{project_id}/arrangement/catalog/boxes/{box_number}")
def api_get_box_dossiers(
    project_id: int,
    box_number: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "status": "ok",
        "data": get_box_dossiers(db, project_id=project_id, box_number=box_number),
    }


@router.post("/{project_id}/arrangement/catalog/preview")
def api_preview_catalog(
    project_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    name, content = _read_catalog_file(file)
    return {
        "status": "ok",
        "data": preview_catalog(db, project_id=project_id, file_name=name, content=content),
    }


@router.post("/{project_id}/arrangement/catalog/import")
def api_import_catalog(
    project_id: int,
    file: UploadFile = File(...),
    plan_token: str = Form(...),
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    name, content = _read_catalog_file(file)
    return {
        "status": "ok",
        "data": import_catalog(
            db,
            project_id=project_id,
            file_name=name,
            content=content,
            plan_token=plan_token,
            actor_user_id=current_user["id"],
        ),
    }
