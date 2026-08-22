from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from server.settings import settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRATCH_DIR = settings.export_work_dir.resolve()
EXPORT_LOCK_PATH = EXPORT_SCRATCH_DIR / "export_all.lock"
_JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ACTIVE_STATES = {"queued", "running"}


class ExportJobBusyError(RuntimeError):
    def __init__(self, job_id: str | None = None):
        super().__init__("Một tác vụ xuất toàn bộ khác đang chạy")
        self.job_id = job_id


def _validate_job_id(job_id: str) -> str:
    normalized = str(job_id or "").strip().lower()
    if not _JOB_ID_PATTERN.fullmatch(normalized):
        raise ValueError("Mã tác vụ xuất không hợp lệ")
    return normalized


def export_job_status_path(job_id: str) -> Path:
    return EXPORT_SCRATCH_DIR / f"export_job_{_validate_job_id(job_id)}.json"


def export_job_output_path(job_id: str, extension: str) -> Path:
    normalized_extension = str(extension or "").lower()
    if normalized_extension not in {".xlsx", ".xlsm"}:
        raise ValueError("Định dạng file xuất không hợp lệ")
    return EXPORT_SCRATCH_DIR / f"export_job_{_validate_job_id(job_id)}{normalized_extension}"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_export_job(job_id: str, payload: dict) -> dict:
    EXPORT_SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    path = export_job_status_path(job_id)
    temp_path = path.with_suffix(f".json.tmp-{os.getpid()}")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(temp_path, path)
    return payload


def read_export_job(job_id: str) -> dict | None:
    path = export_job_status_path(job_id)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def update_export_job(job_id: str, **changes) -> dict:
    payload = read_export_job(job_id) or {"job_id": _validate_job_id(job_id)}
    payload.update(changes)
    payload["updated_at"] = _utc_timestamp()
    return write_export_job(job_id, payload)


def public_export_job(payload: dict) -> dict:
    fields = (
        "job_id",
        "state",
        "template_id",
        "project_id",
        "include_pending_review",
        "rows_total",
        "filename",
        "message",
        "created_at",
        "updated_at",
    )
    return {field: payload.get(field) for field in fields if field in payload}


def _acquire_export_lock(job_id: str) -> None:
    EXPORT_SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            descriptor = os.open(
                EXPORT_LOCK_PATH,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            try:
                active_job_id = EXPORT_LOCK_PATH.read_text(encoding="utf-8").strip()
            except OSError:
                active_job_id = ""
            active_job = read_export_job(active_job_id) if active_job_id else None
            if not active_job or active_job.get("state") in _ACTIVE_STATES:
                raise ExportJobBusyError(active_job_id or None)
            try:
                EXPORT_LOCK_PATH.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(job_id)
        return
    raise ExportJobBusyError()


def release_export_lock(job_id: str) -> None:
    try:
        active_job_id = EXPORT_LOCK_PATH.read_text(encoding="utf-8").strip()
        if active_job_id == _validate_job_id(job_id):
            EXPORT_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def start_export_job(
    *,
    template_id: int,
    extension: str,
    include_pending_review: bool,
    folder_path: str | None,
    start_date: str | None,
    end_date: str | None,
    requested_by_user_id: int,
    project_id: int | None = None,
) -> dict:
    job_id = uuid.uuid4().hex
    _acquire_export_lock(job_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if project_id is not None:
        filename_prefix = "DuAn_TatCa" if include_pending_review else "DuAn_HoanChinh"
        filename = f"{filename_prefix}_{project_id}_{timestamp}{extension}"
    else:
        filename_prefix = "BaoCao_TatCa" if include_pending_review else "BaoCao"
        filename = f"{filename_prefix}_{template_id}_{timestamp}{extension}"
    payload = {
        "job_id": job_id,
        "state": "queued",
        "template_id": template_id,
        "project_id": project_id,
        "include_pending_review": include_pending_review,
        "rows_total": 0,
        "filename": filename,
        "extension": extension,
        "requested_by_user_id": requested_by_user_id,
        "message": "Đang xếp hàng tạo file Excel",
        "created_at": _utc_timestamp(),
        "updated_at": _utc_timestamp(),
    }
    write_export_job(job_id, payload)

    command = [
        sys.executable,
        "-m",
        "server.export_worker",
        "--job-id",
        job_id,
        "--template-id",
        str(template_id),
        "--extension",
        extension,
    ]
    if include_pending_review:
        command.append("--include-pending-review")
    if project_id is not None:
        command.extend(("--project-id", str(project_id)))
    for option, value in (
        ("--folder-path", folder_path),
        ("--start-date", start_date),
        ("--end-date", end_date),
    ):
        if value:
            command.extend((option, value))

    log_path = EXPORT_SCRATCH_DIR / f"export_job_{job_id}.log"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with log_path.open("ab") as log_handle:
            subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creation_flags,
            )
    except Exception as exc:
        update_export_job(
            job_id,
            state="error",
            message=f"Không thể khởi động tác vụ xuất: {exc}",
        )
        release_export_lock(job_id)
        raise
    return payload


def cleanup_export_job(job_id: str) -> None:
    payload = read_export_job(job_id) or {}
    extension = payload.get("extension")
    paths = [export_job_status_path(job_id), EXPORT_SCRATCH_DIR / f"export_job_{job_id}.log"]
    if extension in {".xlsx", ".xlsm"}:
        paths.append(export_job_output_path(job_id, extension))
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
