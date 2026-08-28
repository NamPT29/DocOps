from __future__ import annotations

import argparse
import os
import time

from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError


load_dotenv()

from server.database import SessionLocal
from server.repositories import LookupRepository, SubmissionRepository
from server.repositories.project_reporting_repository import ProjectReportingRepository
from server.services.excel_service import export_submissions_to_excel
from server.services.export_job_service import (
    export_job_output_path,
    read_export_job,
    release_export_lock,
    update_export_job,
)
from server.services.project_reporting_service import resolve_project_template_path


def _positive_int_environment(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _positive_float_environment(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _is_retryable_export_error(exc: Exception) -> bool:
    return isinstance(exc, (OSError, OperationalError, TimeoutError, ConnectionError))


def run_export_job(args) -> int:
    job_id = args.job_id
    output_path = export_job_output_path(job_id, args.extension)
    max_attempts = _positive_int_environment("EXPORT_JOB_MAX_ATTEMPTS", 3)
    retry_delay = _positive_float_environment("EXPORT_JOB_RETRY_DELAY_SECONDS", 1.0)
    try:
        for attempt in range(1, max_attempts + 1):
            db = None
            try:
                db = SessionLocal()
                update_export_job(
                    job_id,
                    state="running",
                    worker_pid=os.getpid(),
                    attempt=attempt,
                    max_attempts=max_attempts,
                    message="Đang đọc dữ liệu báo cáo",
                )
                if args.project_id is not None:
                    project_repository = ProjectReportingRepository(db)
                    project = project_repository.get_project(args.project_id)
                    if not project:
                        raise RuntimeError("Không tìm thấy dự án")
                    if project.template_id != args.template_id:
                        raise RuntimeError("Biểu mẫu xuất không thuộc dự án")
                    template_file_path = str(resolve_project_template_path(project))
                    submissions = project_repository.submissions_for_export(
                        project.id,
                        include_pending_review=args.include_pending_review,
                    )
                else:
                    template = LookupRepository(db).get_template(args.template_id)
                    if not template:
                        raise RuntimeError("Không tìm thấy template mẫu")
                    template_file_path = os.path.join("templates", template.filename)
                    submissions = SubmissionRepository(db).approved_for_export(
                        template_id=args.template_id,
                        folder_path=args.folder_path,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_pending_review=args.include_pending_review,
                    )
                if not submissions:
                    raise RuntimeError("Không có báo cáo phù hợp để xuất")
                update_export_job(
                    job_id,
                    state="running",
                    rows_total=len(submissions),
                    message=f"Đang tạo Excel từ {len(submissions):,} báo cáo",
                )
                export_submissions_to_excel(
                    template_file_path,
                    submissions,
                    str(output_path),
                )
                payload = read_export_job(job_id) or {}
                update_export_job(
                    job_id,
                    state="completed",
                    rows_total=len(submissions),
                    filename=payload.get("filename") or output_path.name,
                    message="File Excel đã sẵn sàng để tải xuống",
                )
                return 0
            except Exception as exc:
                try:
                    output_path.unlink()
                except FileNotFoundError:
                    pass
                if db is not None:
                    db.rollback()
                if attempt < max_attempts and _is_retryable_export_error(exc):
                    update_export_job(
                        job_id,
                        state="running",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        message=(
                            f"Lần xuất {attempt} bị gián đoạn; "
                            f"đang thử lại ({attempt + 1}/{max_attempts})"
                        ),
                    )
                    time.sleep(retry_delay * attempt)
                    continue
                update_export_job(
                    job_id,
                    state="error",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    message=f"Không thể xuất báo cáo: {exc}",
                )
                return 1
            finally:
                if db is not None:
                    db.close()
    finally:
        release_export_lock(job_id)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--template-id", required=True, type=int)
    parser.add_argument("--extension", required=True, choices=(".xlsx", ".xlsm"))
    parser.add_argument("--include-pending-review", action="store_true")
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--folder-path")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_export_job(parse_args()))
