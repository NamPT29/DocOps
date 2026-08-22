from fastapi import Depends
from sqlalchemy.orm import Session

from server.database import get_db
from server.routers.auth import get_input_user
from server.services.project_access_service import require_project_member_role


def get_project_input_member(
    project_id: int,
    current_user: dict = Depends(get_input_user),
    db: Session = Depends(get_db),
) -> dict:
    return require_project_member_role(
        db,
        project_id=project_id,
        current_user=current_user,
        member_role="input",
    )
