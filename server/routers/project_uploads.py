from fastapi import APIRouter, Depends, Header, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.database import get_db
from server.routers.auth import get_admin_user
from server.services.project_upload_service import (
    create_or_resume_upload_session,
    finalize_upload_session,
    get_upload_session,
    write_upload_chunk,
)
from server.services.api_rate_limit_service import (
    enforce_heavy_api_rate_limit,
    enforce_project_upload_chunk_rate_limit,
)


router = APIRouter(tags=["project-uploads"])


class ProjectManifestItemRequest(BaseModel):
    relative_path: str
    size: int
    sha256: str
    last_modified: str | int | None = None


class ProjectUploadSessionRequest(BaseModel):
    client_session_key: str
    files: list[ProjectManifestItemRequest] = Field(default_factory=list)


@router.post("/api/projects/{project_id}/upload-sessions")
def api_create_project_upload_session(
    project_id: int,
    request: ProjectUploadSessionRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    enforce_heavy_api_rate_limit("project-upload-session", current_user["id"], cost=5)
    return {
        "status": "ok",
        "session": create_or_resume_upload_session(
            db,
            project_id=project_id,
            created_by_user_id=current_user["id"],
            client_session_key=request.client_session_key,
            raw_items=[
                {
                    "relative_path": item.relative_path,
                    "size": item.size,
                    "sha256": item.sha256,
                    "last_modified": item.last_modified,
                }
                for item in request.files
            ],
        ),
    }


@router.get("/api/project-upload-sessions/{session_id}")
def api_get_project_upload_session(
    session_id: str,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "session": get_upload_session(db, session_id=session_id)}


@router.put("/api/project-upload-sessions/{session_id}/files/{file_id}")
async def api_upload_project_file_chunk(
    session_id: str,
    file_id: int,
    request: Request,
    upload_offset: int = Header(..., alias="X-Upload-Offset"),
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    await run_in_threadpool(
        enforce_project_upload_chunk_rate_limit,
        current_user["id"],
    )
    chunk = await request.body()
    return await run_in_threadpool(
        write_upload_chunk,
        db,
        session_id=session_id,
        file_id=file_id,
        offset=upload_offset,
        chunk=chunk,
    )


@router.post("/api/project-upload-sessions/{session_id}/finalize")
def api_finalize_project_upload_session(
    session_id: str,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    enforce_heavy_api_rate_limit("project-upload-finalize", current_user["id"], cost=10)
    return {
        "status": "ok",
        "session": finalize_upload_session(db, session_id=session_id),
    }
