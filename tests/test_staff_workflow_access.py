import pytest
from fastapi.testclient import TestClient

from server.models import Project, ProjectMember, ProjectStage, ProjectStageMember, User

@pytest.fixture(scope="function")
def sqlite_engine(tmp_path):
    from sqlalchemy import create_engine
    db_path = tmp_path / "test.db"
    return create_engine(f"sqlite:///{db_path}")

@pytest.fixture(scope="function")
def db_session(sqlite_engine):
    from alembic.config import Config
    from alembic import command
    from server.database import SessionLocal

    alembic_cfg = Config("alembic.ini")
    with sqlite_engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    Session = type(SessionLocal)(bind=sqlite_engine)
    db = Session()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        sqlite_engine.dispose()

@pytest.fixture(scope="function")
def client(db_session):
    from server.main import app
    from server.database import get_db
    
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)

def test_staff_workflow_access(client: TestClient, db_session):
    # Setup users
    admin = User(id=1, username="admin@test.com", password="", full_name="Admin", role="admin", account_type="staff")
    staff_member = User(id=2, username="staff_m@test.com", password="", full_name="Staff M", role="user", account_type="staff")
    staff_not = User(id=3, username="staff_n@test.com", password="", full_name="Staff N", role="user", account_type="staff")
    ctv = User(id=4, username="ctv@test.com", password="", full_name="CTV", role="user", account_type="ctv")
    db_session.add_all([admin, staff_member, staff_not, ctv])
    
    # Setup projects
    p1 = Project(id=1, name="Project 1", root_folder_name="P1", template_id=1, template_name_snapshot="T", template_filename_snapshot="t", case_level=1, report_mode="pdf", created_by_user_id=1)
    p2 = Project(id=2, name="Project 2", root_folder_name="P2", template_id=1, template_name_snapshot="T", template_filename_snapshot="t", case_level=1, report_mode="pdf", created_by_user_id=1)
    db_session.add_all([p1, p2])
    db_session.flush()

    # Stage configs for P1
    db_session.add(ProjectStage(project_id=1, stage_key="scan", position=1, is_enabled=True))
    db_session.add(ProjectStage(project_id=1, stage_key="entry_qc", position=2, is_enabled=True))
    
    # Staff Member is scan member and reviewer of P1
    db_session.add(ProjectStageMember(project_id=1, stage_key="scan", user_id=staff_member.id))
    db_session.add(ProjectMember(project_id=1, user_id=staff_member.id, member_role="reviewer"))
    
    # CTV is scan member (but shouldn't be allowed by service)
    db_session.add(ProjectStageMember(project_id=1, stage_key="scan", user_id=ctv.id))
    db_session.commit()

    # Need auth override since we rely on get_current_user and it checks email
    from server.routers.auth import get_current_user, get_admin_user
    
    def override_current(user):
        return lambda: {"id": user.id, "username": user.username, "role": user.role, "account_type": user.account_type}
        
    def override_admin(user):
        def _get():
            if user.role != "admin":
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Yêu cầu quyền Quản trị viên")
            return {"id": user.id, "username": user.username, "role": user.role, "account_type": user.account_type}
        return _get

    def get_as(user, path):
        client.app.dependency_overrides[get_current_user] = override_current(user)
        client.app.dependency_overrides[get_admin_user] = override_admin(user)
        resp = client.get(path)
        return resp
        
    def post_as(user, path, json):
        client.app.dependency_overrides[get_current_user] = override_current(user)
        client.app.dependency_overrides[get_admin_user] = override_admin(user)
        resp = client.post(path, json=json)
        return resp

    # 1. GET /api/workflow/my-projects
    resp_staff = get_as(staff_member, "/api/workflow/my-projects")
    assert resp_staff.status_code == 200
    data = resp_staff.json()["data"]
    assert len(data) == 1
    assert data[0]["project_id"] == 1
    assert "scan" in data[0]["stages"]
    assert data[0]["is_reviewer"] is True

    resp_not = get_as(staff_not, "/api/workflow/my-projects")
    assert resp_not.status_code == 200
    assert len(resp_not.json()["data"]) == 0

    resp_ctv = get_as(ctv, "/api/workflow/my-projects")
    assert resp_ctv.status_code == 200
    assert len(resp_ctv.json()["data"]) == 0
    
    # 2. GET /api/documents/server-folders
    assert get_as(staff_member, "/api/documents/server-folders").status_code == 200
    assert get_as(staff_not, "/api/documents/server-folders").status_code == 403
    assert get_as(ctv, "/api/documents/server-folders").status_code == 403
    assert get_as(admin, "/api/documents/server-folders").status_code == 200

    # 3. GET /api/projects/1/cases/1/scan-packages
    # We expect 404 for admin/staff_member if case doesn't exist, but 403 for unauthorized
    assert get_as(staff_not, "/api/projects/1/cases/1/scan-packages").status_code == 403
    assert get_as(ctv, "/api/projects/1/cases/1/scan-packages").status_code == 403
    assert get_as(staff_member, "/api/projects/1/cases/1/scan-packages").status_code == 404
    assert get_as(admin, "/api/projects/1/cases/1/scan-packages").status_code == 404

    # 4. POST /api/projects/1/cases/1/scan-packages
    assert post_as(staff_not, "/api/projects/1/cases/1/scan-packages", {"folder_path": "abc"}).status_code == 403
    assert post_as(ctv, "/api/projects/1/cases/1/scan-packages", {"folder_path": "abc"}).status_code == 403
    
    # For my-work, entry_qc should be tested.
    resp = get_as(staff_member, "/api/projects/1/workflow/my-work")
    assert resp.status_code == 200
