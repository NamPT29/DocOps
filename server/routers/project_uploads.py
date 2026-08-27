import logging
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
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
upload_timing_logger = logging.getLogger("server.upload_timing")
upload_timing_logger.setLevel(logging.INFO)
upload_timing_logger.info(
    "Project upload timing enabled",
    extra={"event_data": {"name": "project_upload_timing_ready"}},
)


def _upload_request_source(request: Request) -> str:
    headers = getattr(request, "headers", {})
    if headers.get("cf-ray") or headers.get("cf-connecting-ip"):
        return "cloudflare"
    if (
        headers.get("via")
        or headers.get("x-forwarded-for")
        or headers.get("x-forwarded-proto")
    ):
        return "proxy"
    return "direct"


def _elapsed_ms(marks: dict[str, float], name: str) -> float | None:
    value = marks.get(name)
    started = marks.get("request_started")
    if value is None or started is None:
        return None
    return round((value - started) * 1000, 2)


def _duration_ms(
    marks: dict[str, float],
    started_name: str,
    completed_name: str,
) -> float | None:
    started = marks.get(started_name)
    completed = marks.get(completed_name)
    if started is None or completed is None:
        return None
    return round((completed - started) * 1000, 2)


def _upload_timing_event(
    *,
    marks: dict[str, float],
    request_source: str,
    session_id: str,
    file_id: int,
    offset: int,
    chunk_bytes: int,
    outcome: str,
    state: str | None,
    error_type: str,
) -> dict:
    return {
        "name": "project_upload_chunk_timing",
        "request_source": request_source,
        "session_id": session_id,
        "file_id": file_id,
        "offset": offset,
        "chunk_bytes": chunk_bytes,
        "outcome": outcome,
        "state": state,
        "error_type": error_type,
        "request_started_ms": 0.0,
        "body_received_ms": _elapsed_ms(marks, "body_received"),
        "file_lock_acquired_ms": _elapsed_ms(marks, "file_lock_acquired"),
        "file_written_ms": _elapsed_ms(marks, "file_written"),
        "fsync_completed_ms": _elapsed_ms(marks, "fsync_completed"),
        "sha256_completed_ms": _elapsed_ms(marks, "sha256_completed"),
        "database_committed_ms": _elapsed_ms(marks, "database_committed"),
        "request_to_handler_ms": _duration_ms(
            marks, "request_started", "handler_started"
        ),
        "rate_limit_ms": _duration_ms(
            marks, "rate_limit_started", "rate_limit_completed"
        ),
        "body_read_ms": _duration_ms(
            marks, "body_receive_started", "body_received"
        ),
        "lock_wait_ms": _duration_ms(
            marks, "file_lock_started", "file_lock_acquired"
        ),
        "file_write_ms": _duration_ms(
            marks, "file_write_started", "file_written"
        ),
        "file_flush_ms": _duration_ms(
            marks, "file_written", "flush_completed"
        ),
        "fsync_ms": _duration_ms(
            marks, "fsync_started", "fsync_completed"
        ),
        "sha256_ms": _duration_ms(
            marks, "sha256_started", "sha256_completed"
        ),
        "database_update_ms": _duration_ms(
            marks, "database_update_started", "database_commit_started"
        ),
        "database_commit_ms": _duration_ms(
            marks, "database_commit_started", "database_committed"
        ),
        "total_ms": _duration_ms(marks, "request_started", "request_completed"),
    }


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
    handler_started = time.perf_counter()
    request_state = getattr(request, "state", None)
    marks = {
        "request_started": getattr(
            request_state,
            "request_started_at",
            handler_started,
        ),
        "handler_started": handler_started,
    }
    chunk = b""
    outcome = "aborted"
    result_state = None
    error_type = "-"
    status_code = 500
    try:
        marks["rate_limit_started"] = time.perf_counter()
        await run_in_threadpool(
            enforce_project_upload_chunk_rate_limit,
            current_user["id"],
        )
        marks["rate_limit_completed"] = time.perf_counter()
        marks["body_receive_started"] = time.perf_counter()
        chunk = await request.body()
        marks["body_received"] = time.perf_counter()
        result = await run_in_threadpool(
            write_upload_chunk,
            db,
            session_id=session_id,
            file_id=file_id,
            offset=upload_offset,
            chunk=chunk,
            timing_marks=marks,
        )
        outcome = "ok"
        result_state = result.get("state")
        status_code = 200
        return result
    except HTTPException as exc:
        outcome = "http_error"
        error_type = type(exc).__name__
        status_code = exc.status_code
        raise
    except Exception as exc:
        outcome = "error"
        error_type = type(exc).__name__
        raise
    finally:
        marks["request_completed"] = time.perf_counter()
        upload_timing_logger.info(
            "Project upload chunk timing",
            extra={
                "status_code": status_code,
                "error_type": error_type,
                "event_data": _upload_timing_event(
                    marks=marks,
                    request_source=_upload_request_source(request),
                    session_id=session_id,
                    file_id=file_id,
                    offset=upload_offset,
                    chunk_bytes=len(chunk),
                    outcome=outcome,
                    state=result_state,
                    error_type=error_type,
                ),
            },
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
