import json
import os
import secrets
import shutil
from pathlib import Path

from fastapi import HTTPException

from server.models import Project, ProjectMember
from server.repositories.dictionary_repository import DictionaryRepository
from server.repositories.project_repository import ProjectRepository
from server.repositories.template_repository import TemplateRepository
from server.repositories.user_repository import UserRepository
from server.services.excel_service import get_form_schema


def _clean_folder_name(root_folder_name):
    value = str(root_folder_name or "").strip().rstrip("/\\")
    value = value.replace("\\", "/").split("/")[-1].strip()
    if not value or value in {".", ".."}:
        raise HTTPException(status_code=400, detail="Tên thư mục dự án không hợp lệ")
    return value


def _validate_project_levels(case_level, report_mode, report_level):
    if not isinstance(case_level, int) or isinstance(case_level, bool) or case_level < 1:
        raise HTTPException(status_code=400, detail="Cấp hồ sơ phải lớn hơn hoặc bằng 1")
    if report_mode not in {"folder_level", "pdf"}:
        raise HTTPException(status_code=400, detail="Kiểu báo cáo không hợp lệ")
    if report_mode == "pdf":
        if report_level is not None:
            raise HTTPException(status_code=400, detail="Chế độ mỗi PDF không dùng cấp báo cáo")
        return
    if (
        not isinstance(report_level, int)
        or isinstance(report_level, bool)
        or report_level <= case_level
    ):
        raise HTTPException(status_code=400, detail="Cấp báo cáo phải lớn hơn cấp hồ sơ")


def _validate_project_members(db, input_user_ids, reviewer_user_ids):
    input_ids = set(input_user_ids or [])
    reviewer_ids = set(reviewer_user_ids or [])
    requested_ids = input_ids | reviewer_ids
    users = UserRepository(db).user_map(requested_ids)
    missing_ids = sorted(requested_ids - set(users))
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Không tìm thấy người dùng: {', '.join(map(str, missing_ids))}",
        )
    invalid_input_ids = sorted(
        user_id for user_id in input_ids if users[user_id].role == "admin"
    )
    if invalid_input_ids:
        raise HTTPException(
            status_code=400,
            detail="Quản trị viên không được phân làm người nhập",
        )
    return sorted(input_ids), sorted(reviewer_ids)


def _build_template_snapshot(db, template):
    template_root = Path(os.getenv("TEMPLATE_STORAGE_PATH", "templates")).resolve()
    source_name = os.path.basename(template.filename or "")
    source_path = (template_root / source_name).resolve()
    try:
        source_path.relative_to(template_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn biểu mẫu không hợp lệ")
    if not source_path.is_file():
        raise HTTPException(status_code=400, detail="Không tìm thấy file biểu mẫu")

    try:
        config = json.loads(template.config_json) if template.config_json else {}
    except (TypeError, ValueError):
        config = {}
    dictionaries = DictionaryRepository(db).option_map_for_template(template.id)
    try:
        schema = get_form_schema(str(source_path), dictionaries, config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Không thể đọc biểu mẫu: {exc}")

    snapshot_dir = template_root / "project_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    extension = source_path.suffix.casefold()
    snapshot_name = f"project-{secrets.token_hex(16)}{extension}"
    snapshot_path = snapshot_dir / snapshot_name
    shutil.copy2(source_path, snapshot_path)
    return {
        "filename": f"project_snapshots/{snapshot_name}",
        "absolute_path": snapshot_path,
        "config_json": json.dumps(config, ensure_ascii=False),
        "schema_json": json.dumps(schema, ensure_ascii=False),
    }


def create_project(
    db,
    *,
    name,
    root_folder_name,
    template_id,
    start_date,
    end_date,
    case_level,
    report_mode,
    report_level,
    input_user_ids,
    reviewer_user_ids,
    created_by_user_id,
):
    folder_name = _clean_folder_name(root_folder_name)
    project_name = str(name or "").strip() or folder_name
    _validate_project_levels(case_level, report_mode, report_level)
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="Ngày kết thúc không được trước ngày bắt đầu")

    input_ids, reviewer_ids = _validate_project_members(
        db,
        input_user_ids,
        reviewer_user_ids,
    )
    template_repository = TemplateRepository(db)
    template_repository.lock_for_update(template_id)
    template = template_repository.get(template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=404, detail="Biểu mẫu không tồn tại hoặc đã ngừng sử dụng")

    snapshot = _build_template_snapshot(db, template)
    project = Project(
        name=project_name,
        root_folder_name=folder_name,
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=snapshot["filename"],
        template_config_json_snapshot=snapshot["config_json"],
        form_schema_json_snapshot=snapshot["schema_json"],
        start_date=start_date,
        end_date=end_date,
        case_level=case_level,
        report_mode=report_mode,
        report_level=report_level,
        status="ready",
        created_by_user_id=created_by_user_id,
    )
    try:
        db.add(project)
        db.flush()
        db.add_all(
            [
                ProjectMember(project_id=project.id, user_id=user_id, member_role="input")
                for user_id in input_ids
            ]
            + [
                ProjectMember(project_id=project.id, user_id=user_id, member_role="reviewer")
                for user_id in reviewer_ids
            ]
        )
        db.commit()
        db.refresh(project)
        return project
    except Exception:
        db.rollback()
        try:
            snapshot["absolute_path"].unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _serialize_project(project, members, metrics):
    return {
        "id": project.id,
        "name": project.name,
        "root_folder_name": project.root_folder_name,
        "template_id": project.template_id,
        "template_name": project.template_name_snapshot,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        "case_level": project.case_level,
        "report_mode": project.report_mode,
        "report_level": project.report_level,
        "status": project.status,
        "input_user_ids": members["input"],
        "reviewer_user_ids": members["reviewer"],
        "metrics": metrics,
    }


def list_projects(db, *, current_user):
    repository = ProjectRepository(db)
    if current_user.get("role") == "admin":
        projects = repository.list_all()
    else:
        projects = repository.list_for_user(current_user["id"])
    project_ids = [project.id for project in projects]
    members_by_project = repository.member_ids_by_role(project_ids)
    metrics_by_project = repository.metrics_by_project(project_ids)
    return [
        _serialize_project(
            project,
            members_by_project[project.id],
            metrics_by_project[project.id],
        )
        for project in projects
    ]
