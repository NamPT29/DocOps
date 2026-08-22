from typing import Literal

from fastapi import HTTPException

from server.repositories.project_access_repository import ProjectAccessRepository


ProjectMemberRole = Literal["input", "reviewer"]


def require_project_member_role(
    db,
    *,
    project_id: int,
    current_user: dict,
    member_role: ProjectMemberRole,
) -> dict:
    """Require an active project role in addition to the user's global capability."""

    repository = ProjectAccessRepository(db)
    if not repository.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    if current_user.get("role") == "admin":
        return current_user
    if not repository.user_has_active_role(
        project_id,
        current_user["id"],
        member_role,
    ):
        role_label = "nhập liệu" if member_role == "input" else "kiểm tra"
        raise HTTPException(
            status_code=403,
            detail=f"Bạn không được phân quyền {role_label} trong dự án này",
        )
    return current_user
