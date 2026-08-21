import os
from pathlib import Path

from fastapi import HTTPException

from server.repositories.project_reporting_repository import (
    PROJECT_COMPLETED_STATUSES,
    PROJECT_REVIEW_STATUSES,
    ProjectReportingRepository,
)
from server.repositories.submission_view_repository import SubmissionViewRepository
from server.services.submission_service import SubmissionService


PROJECT_REPORT_VIEWS = {
    "review": PROJECT_REVIEW_STATUSES,
    "completed": PROJECT_COMPLETED_STATUSES,
}


def get_project_or_404(db, project_id):
    project = ProjectReportingRepository(db).get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return project


def _statuses_for_view(view):
    try:
        return PROJECT_REPORT_VIEWS[view]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Chế độ xem hồ sơ không hợp lệ") from exc


def list_project_submission_folders(db, *, project_id, view):
    project = get_project_or_404(db, project_id)
    rows = ProjectReportingRepository(db).folder_groups(
        project.id,
        _statuses_for_view(view),
    )
    return {
        "project": {"id": project.id, "name": project.name},
        "view": view,
        "folders": [
            {
                "folder_path": case_key,
                "folder_name": display_name or case_key.rstrip("/").rsplit("/", 1)[-1],
                "submission_count": submission_count,
            }
            for case_key, display_name, submission_count in rows
        ],
    }


def get_project_submissions(
    db,
    *,
    project_id,
    view,
    folder_path,
    page,
    page_size,
):
    if page < 1:
        raise HTTPException(status_code=400, detail="Số trang phải lớn hơn hoặc bằng 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="Số hồ sơ mỗi trang phải từ 1 đến 100")
    project = get_project_or_404(db, project_id)
    rows, total, total_pages, current_page = ProjectReportingRepository(db).paginate(
        project.id,
        _statuses_for_view(view),
        folder_path=folder_path,
        page=page,
        page_size=page_size,
    )
    submissions = [submission for submission, _case_row in rows]
    case_by_submission_id = {
        submission.id: case_row
        for submission, case_row in rows
    }
    document_metadata, assignment_map, user_map, template_map = (
        SubmissionService._fetch_submission_relations(submissions, db)
    )
    viewer_map = SubmissionViewRepository(db).active_map(
        [submission.id for submission in submissions]
    ) if view == "review" else {}
    data = []
    for index, submission in enumerate(submissions):
        item = SubmissionService._build_submission_response(
            submission,
            index,
            current_page,
            page_size,
            document_metadata,
            assignment_map,
            user_map,
            template_map,
        )
        case_row = case_by_submission_id[submission.id]
        item["folder_path"] = case_row.case_key
        item["folder_name"] = case_row.display_name
        item["viewer"] = viewer_map.get(submission.id)
        data.append(item)

    first_item = (current_page - 1) * page_size + 1 if total else 0
    return {
        "project": {"id": project.id, "name": project.name},
        "view": view,
        "folder_path": folder_path,
        "data": data,
        "pagination": {
            "page": current_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "from": first_item,
            "to": first_item + len(data) - 1 if data else 0,
        },
    }


def resolve_project_template_path(project):
    template_root = Path(os.getenv("TEMPLATE_STORAGE_PATH", "templates")).resolve()
    snapshot_name = str(project.template_filename_snapshot or "").replace("\\", "/")
    snapshot_path = (template_root / snapshot_name).resolve()
    try:
        snapshot_path.relative_to(template_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Đường dẫn biểu mẫu dự án không hợp lệ") from exc
    if not snapshot_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy biểu mẫu của dự án")
    if snapshot_path.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail="Định dạng file mẫu không được hỗ trợ")
    return snapshot_path
