from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from server.settings import settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRATCH_DIR = settings.export_work_dir.resolve()
EXPORT_LOCK_PATH = EXPORT_SCRATCH_DIR / "export_all.lock"
_JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ACTIVE_STATES = {"queued", "running"}
_CLEANUP_RETRY_ATTEMPTS = 10
_CLEANUP_RETRY_DELAY_SECONDS = 0.05
_EXPORT_JOB_STARTUP_TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)


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


def _process_is_running(pid: object) -> bool:
    try:
        normalized_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if normalized_pid <= 0:
        return False
    try:
        os.kill(normalized_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _active_export_job_is_stale(payload: dict) -> bool:
    worker_pid = payload.get("worker_pid")
    if worker_pid is not None:
        return not _process_is_running(worker_pid)

    timestamp = payload.get("updated_at") or payload.get("created_at")
    if not timestamp:
        return True
    try:
        updated_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return age_seconds > _EXPORT_JOB_STARTUP_TIMEOUT_SECONDS


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
            try:
                active_job = read_export_job(active_job_id) if active_job_id else None
            except ValueError:
                active_job = None
            if (
                active_job
                and active_job.get("state") in _ACTIVE_STATES
                and not _active_export_job_is_stale(active_job)
            ):
                raise ExportJobBusyError(active_job_id or None)
            if active_job and active_job.get("state") in _ACTIVE_STATES:
                update_export_job(
                    active_job_id,
                    state="error",
                    worker_pid=None,
                    message="Tác vụ xuất đã dừng ngoài dự kiến; khóa đã được thu hồi",
                )
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
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creation_flags,
            )
        worker_pid = getattr(process, "pid", None)
        if worker_pid:
            payload = update_export_job(job_id, worker_pid=worker_pid)
    except Exception as exc:
        update_export_job(
            job_id,
            state="error",
            message=f"Không thể khởi động tác vụ xuất: {exc}",
        )
        release_export_lock(job_id)
        raise
    return payload


def _unlink_export_artifact(path: Path) -> bool:
    for attempt in range(_CLEANUP_RETRY_ATTEMPTS):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt + 1 < _CLEANUP_RETRY_ATTEMPTS:
                time.sleep(_CLEANUP_RETRY_DELAY_SECONDS)
                continue
            logger.warning("Không thể dọn file xuất đang bị khóa: %s", path)
            return False
        except OSError as exc:
            logger.warning("Không thể dọn file xuất %s: %s", path, exc)
            return False
    return False


def cleanup_export_job(job_id: str) -> dict:
    payload = read_export_job(job_id) or {}
    extension = payload.get("extension")
    paths = [export_job_status_path(job_id), EXPORT_SCRATCH_DIR / f"export_job_{job_id}.log"]
    if extension in {".xlsx", ".xlsm"}:
        paths.append(export_job_output_path(job_id, extension))
    removed = 0
    retained = []
    for path in paths:
        if _unlink_export_artifact(path):
            removed += 1
        else:
            retained.append(str(path))
    return {"removed": removed, "retained": retained}


def cleanup_stale_export_jobs(*, max_age_hours: int = 24) -> dict:
    """Remove export job artifacts whose terminal state is older than *max_age_hours*.

    Scans ``EXPORT_SCRATCH_DIR`` for ``export_job_*.json`` status files.
    A job is eligible for cleanup when its state is ``completed`` or ``error``
    **and** its ``updated_at`` timestamp is older than *max_age_hours*.

    Jobs in ``queued`` or ``running`` state are **never** touched.
    """
    if max_age_hours <= 0:
        raise ValueError("Thời gian lưu tác vụ xuất phải lớn hơn 0 giờ")
    if not EXPORT_SCRATCH_DIR.is_dir():
        return {"cleaned": 0, "skipped": 0, "errors": 0}

    terminal_states = {"completed", "error"}
    cleaned = 0
    skipped = 0
    errors = 0

    for status_file in EXPORT_SCRATCH_DIR.glob("export_job_*.json"):
        raw_job_id = status_file.stem.removeprefix("export_job_")
        if not _JOB_ID_PATTERN.fullmatch(raw_job_id):
            continue

        try:
            payload = read_export_job(raw_job_id)
        except Exception:
            errors += 1
            continue

        if not payload:
            skipped += 1
            continue

        state = payload.get("state")
        if state not in terminal_states:
            skipped += 1
            continue

        timestamp = payload.get("updated_at") or payload.get("created_at")
        try:
            updated_at = datetime.fromisoformat(
                str(timestamp).replace("Z", "+00:00")
            )
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
        except (AttributeError, TypeError, ValueError):
            logger.warning(
                "Bỏ qua export job %s vì timestamp không hợp lệ", raw_job_id
            )
            errors += 1
            continue

        age_hours = (
            datetime.now(timezone.utc) - updated_at
        ).total_seconds() / 3600
        if age_hours < max_age_hours:
            skipped += 1
            continue

        try:
            result = cleanup_export_job(raw_job_id)
            if result["retained"]:
                errors += 1
            else:
                cleaned += 1
        except Exception:
            logger.warning(
                "Không thể dọn export job cũ %s", raw_job_id, exc_info=True
            )
            errors += 1

    if cleaned:
        logger.info(
            "Startup cleanup: đã dọn %d export job cũ (bỏ qua %d, lỗi %d)",
            cleaned,
            skipped,
            errors,
        )
    return {"cleaned": cleaned, "skipped": skipped, "errors": errors}
