"""Khóa sửa hồ sơ sau bàn giao (lát K1a, revision 0017_project_handover_lock)."""
import json
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.main import app
from server.models import (
    AssignedDocument,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    Submission,
    Template,
    User,
)
from server.routers import project_uploads
from server.routers.auth import get_current_user
from server.services import entry_qc_service, handover_lock_service
from server.services.project_service import list_projects
from server.services.submission_service import SubmissionService

LOCKED_AT = datetime(2026, 10, 8, 2, 0)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'lock.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db):
    admin = User(username="admin", password="x", role="admin", full_name="Quản trị", account_type="staff")
    staff = User(username="nv", password="x", role="user", full_name="Nhân viên", account_type="staff")
    template = Template(name="T", filename="t.xlsx", config_json=json.dumps({"cover_cols": [1], "cover_folder_level": 1}))
    db.add_all([admin, staff, template])
    db.flush()

    def project(name):
        row = Project(
            name=name, root_folder_name=name, template_id=template.id, template_name_snapshot="T",
            template_filename_snapshot="t.xlsx", case_level=1, report_mode="pdf", created_by_user_id=admin.id, status="ongoing",
        )
        db.add(row)
        db.flush()
        case_row = ProjectCase(project_id=row.id, case_key="0001", display_name="0001")
        db.add(case_row)
        db.flush()
        unit = ProjectReportUnit(project_id=row.id, case_id=case_row.id, report_key="0001", display_name="0001")
        db.add(unit)
        db.flush()
        return row, case_row, unit

    locked, locked_case, locked_unit = project("Đã bàn giao")
    other, other_case, other_unit = project("Đang làm")

    def document(project_row, case_row, unit, name, *, status="completed", submission_status=None):
        doc = AssignedDocument(original_filename=name, uuid_filename=f"u-{project_row.id}-{name}",
                               assigned_to_user_id=admin.id, status=status)
        db.add(doc)
        db.flush()
        asset = ProjectDocumentAsset(
            project_id=project_row.id, case_id=case_row.id, report_unit_id=unit.id, assigned_document_id=doc.id,
            relative_path=f"0001/001/{name}", normalized_relative_path=f"0001/001/{name}".casefold(), original_filename=name,
            storage_filename=f"s-{project_row.id}-{name}", content_sha256="0" * 64, byte_size=1,
        )
        db.add(asset)
        submission = None
        if submission_status:
            submission = Submission(
                template_id=template.id, assigned_document_id=doc.id, created_by_user_id=admin.id,
                data_json=json.dumps({"col_0": "Bìa cũ", "col_1": "a"}), status=submission_status,
                folder_path="0001/001", folder_path_key="k",
            )
            db.add(submission)
        db.flush()
        return doc, asset, submission

    _doc1, _asset1, draft = document(locked, locked_case, locked_unit, "1.pdf", submission_status="draft")
    _doc2, _asset2, completed = document(locked, locked_case, locked_unit, "2.pdf", submission_status="completed")
    new_doc, new_asset, _none = document(locked, locked_case, locked_unit, "3.pdf", status="pending")
    _doc3, _asset3, other_draft = document(other, other_case, other_unit, "1.pdf", submission_status="draft")
    legacy = Submission(template_id=template.id, created_by_user_id=admin.id, data_json="{}", status="pending_review")
    db.add(legacy)
    locked.handover_locked_at = LOCKED_AT
    locked.handover_locked_by_user_id = admin.id
    db.commit()
    return SimpleNamespace(
        admin=admin, staff=staff, template=template, locked=locked, other=other, draft=draft, completed=completed,
        new_doc=new_doc, new_asset=new_asset, other_draft=other_draft, legacy=legacy,
    )


def as_user(user):
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "session_id": "s"}


@pytest.fixture()
def client(db, world, monkeypatch):
    # Bộ giới hạn tần suất dùng CSDL toàn cục; test không đụng tới.
    monkeypatch.setattr(project_uploads, "enforce_heavy_api_rate_limit", lambda *args, **kwargs: None)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: as_user(world.admin)
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def snapshot(db):
    db.expire_all()
    return (
        sorted((s.id, s.status, s.data_json, s.is_checked) for s in db.query(Submission).all()),
        sorted((a.id, a.status) for a in db.query(ProjectDocumentAsset).all()),
        sorted((d.id, d.status) for d in db.query(AssignedDocument).all()),
    )


BLOCKED = [
    ("submit", "POST", lambda w: "/api/submit", lambda w: {"template_id": w.template.id, "data": {"_pdf_uuid": w.new_doc.uuid_filename}}),
    ("update", "PUT", lambda w: f"/api/submissions/{w.draft.id}", lambda w: {"template_id": w.template.id, "data": {"col_0": "Mới"}}),
    ("review-content", "PUT", lambda w: f"/api/submissions/{w.draft.id}/review-content", lambda w: {"data": {"col_0": "Mới"}}),
    ("confirm-review", "PUT", lambda w: f"/api/submissions/{w.draft.id}/confirm-review", lambda w: {"data": {}}),
    ("toggle_check", "PUT", lambda w: f"/api/submissions/{w.draft.id}/toggle_check", lambda w: None),
    ("reopen-review", "PUT", lambda w: f"/api/submissions/{w.completed.id}/reopen-review", lambda w: None),
    ("input-confirmation", "PUT", lambda w: f"/api/submissions/{w.draft.id}/input-confirmation", lambda w: {"data": {}}),
    ("errors", "PUT", lambda w: f"/api/submissions/{w.draft.id}/errors", lambda w: {"wrong_sections": ["Bìa"]}),
    ("delete", "DELETE", lambda w: f"/api/submissions/{w.draft.id}", lambda w: None),
    ("bulk-action", "POST", lambda w: "/api/submissions/bulk-action",
     lambda w: {"submission_ids": [w.other_draft.id, w.draft.id], "action": "delete"}),
    ("upload-sessions", "POST", lambda w: f"/api/projects/{w.locked.id}/upload-sessions",
     lambda w: {"client_session_key": "k", "files": [{"relative_path": "0001/001/9.pdf", "size": 1, "sha256": "0" * 64}]}),
    ("delete-asset", "DELETE", lambda w: f"/api/projects/{w.locked.id}/assets/{w.new_asset.id}", lambda w: None),
]


def send(client, method, url, body):
    return client.request(method, url, json=body) if body is not None else client.request(method, url)


@pytest.mark.parametrize("name,method,url,body", BLOCKED, ids=[item[0] for item in BLOCKED])
def test_every_edit_path_returns_423_and_writes_nothing(db, world, client, name, method, url, body):
    before = snapshot(db)
    response = send(client, method, url(world), body(world))
    assert response.status_code == 423, (name, response.status_code, response.text)
    assert response.json()["detail"] == {
        "code": "project_handed_over",
        "message": "Dự án đã bàn giao, không sửa được hồ sơ. Admin mở khóa nếu cần sửa.",
    }
    assert snapshot(db) == before


@pytest.mark.parametrize("name,method,url,body", BLOCKED, ids=[item[0] for item in BLOCKED])
def test_every_edit_path_is_open_again_after_unlock(db, world, client, name, method, url, body):
    world.locked.handover_locked_at = None
    db.commit()
    response = send(client, method, url(world), body(world))
    assert response.status_code != 423, (name, response.text)


def test_unlocked_paths_really_work(db, world, client):
    world.locked.handover_locked_at = None
    db.commit()
    assert client.delete(f"/api/submissions/{world.draft.id}").status_code == 200
    assert client.post("/api/submit", json={"template_id": world.template.id, "data": {"_pdf_uuid": world.new_doc.uuid_filename}}).status_code == 200
    db.expire_all()
    assert db.get(Submission, world.draft.id) is None
    assert db.query(Submission).filter(Submission.assigned_document_id == world.new_doc.id).count() == 1


def test_bulk_action_with_one_locked_submission_changes_nothing(db, world, client):
    response = client.post("/api/submissions/bulk-action", json={"submission_ids": [world.other_draft.id, world.draft.id], "action": "delete"})
    assert response.status_code == 423
    db.expire_all()
    assert db.get(Submission, world.other_draft.id) is not None, "hồ sơ của dự án chưa khóa cũng không bị xóa"
    assert client.post("/api/submissions/bulk-action", json={"submission_ids": [world.other_draft.id], "action": "delete"}).status_code == 200


def test_view_lease_and_unlinked_submissions_are_not_blocked(db, world, client):
    assert client.put(f"/api/submissions/{world.draft.id}/view").status_code == 200
    assert client.delete(f"/api/submissions/{world.draft.id}/view").status_code == 200
    response = client.put(f"/api/submissions/{world.legacy.id}/errors", json={"wrong_sections": ["Bìa"]})
    assert response.status_code != 423, "hồ sơ không gắn file dự án không bị khóa"
    assert client.get(f"/api/submissions/{world.draft.id}").status_code == 200, "xem vẫn được"


def test_round2_check_is_blocked(db, world, monkeypatch):
    monkeypatch.setattr(entry_qc_service, "_check_round2_item_access", lambda *args: (None, None, world.completed))
    with pytest.raises(HTTPException) as error:
        entry_qc_service.check_round2_item(db, world.locked.id, 1, world.completed.id, {"col_0": "x"}, as_user(world.admin))
    assert error.value.status_code == 423


def test_cover_sync_skips_locked_project(db, world):
    source = world.other_draft
    data = {"col_0": "Bìa mới", "col_1": "a"}
    SubmissionService.sync_cover_data(source, world.template.id, data, db)
    db.commit()
    db.expire_all()
    assert json.loads(db.get(Submission, world.draft.id).data_json)["col_0"] == "Bìa cũ", "dự án đã khóa không bị đồng bộ bìa"
    world.locked.handover_locked_at = None
    db.commit()
    SubmissionService.sync_cover_data(source, world.template.id, data, db)
    db.commit()
    db.expire_all()
    assert json.loads(db.get(Submission, world.draft.id).data_json)["col_0"] == "Bìa mới"


def test_lock_requires_done_package_and_unlock_requires_reason(db, world, client, monkeypatch, caplog):
    world.locked.handover_locked_at = None
    db.commit()
    url = f"/api/projects/{world.locked.id}/handover-lock"
    monkeypatch.setattr(handover_lock_service, "read_job", lambda project_id: None)
    response = client.post(url, json={"note": "Biên bản số 1"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "package_required"
    monkeypatch.setattr(handover_lock_service, "read_job", lambda project_id: {"state": "error"})
    assert client.post(url, json={}).status_code == 409
    monkeypatch.setattr(handover_lock_service, "read_job", lambda project_id: {"state": "done"})
    response = client.post(url, json={"note": "  Biên bản số 1  "})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["handover_locked_at"].endswith("Z") and data["handover_lock_note"] == "Biên bản số 1"
    assert client.post(url, json={}).json()["detail"]["code"] == "already_locked"
    listed = {item["id"]: item for item in list_projects(db, current_user=as_user(world.admin))}
    assert listed[world.locked.id]["handover_locked_at"].endswith("Z")
    assert listed[world.other.id]["handover_locked_at"] is None

    for body in (None, {}, {"reason": "   "}):
        response = client.request("DELETE", url, json=body) if body is not None else client.delete(url)
        assert response.status_code == 400 and response.json()["detail"]["code"] == "reason_required"
    with caplog.at_level(logging.INFO, logger="server.audit.handover_lock"):
        response = client.request("DELETE", url, json={"reason": "Khách yêu cầu sửa trích yếu"})
    assert response.status_code == 200 and response.json()["data"]["handover_locked_at"] is None
    assert any("Khách yêu cầu sửa trích yếu" in record.getMessage() for record in caplog.records)
    db.expire_all()
    assert db.get(Project, world.locked.id).handover_locked_at is None
    assert client.request("DELETE", url, json={"reason": "x"}).json()["detail"]["code"] == "not_locked"


def test_lock_endpoints_are_admin_only(db, world, client):
    app.dependency_overrides[get_current_user] = lambda: as_user(world.staff)
    url = f"/api/projects/{world.other.id}/handover-lock"
    assert client.post(url, json={}).status_code == 403
    assert client.request("DELETE", url, json={"reason": "x"}).status_code == 403
    assert client.post("/api/projects/999/handover-lock", json={}).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: as_user(world.admin)
    assert client.post("/api/projects/999/handover-lock", json={}).status_code == 404


def test_handover_lock_revision_is_additive():
    pytest.importorskip("alembic")
    from pathlib import Path

    from alembic import command

    from server.migration_runner import _alembic_config, current_database_revision

    engine = create_engine("sqlite+pysqlite:///:memory:")
    config = _alembic_config(Path(__file__).resolve().parents[1])
    columns = {"handover_locked_at", "handover_locked_by_user_id", "handover_lock_note"}
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0016_case_paper_handoffs")
        assert not columns & {column["name"] for column in inspect(connection).get_columns("projects")}
        command.upgrade(config, "0017_project_handover_lock")
        assert current_database_revision(connection) == "0017_project_handover_lock"
        assert columns <= {column["name"] for column in inspect(connection).get_columns("projects")}
        assert any(fk["constrained_columns"] == ["handover_locked_by_user_id"] and fk["referred_table"] == "users"
                   for fk in inspect(connection).get_foreign_keys("projects"))
        command.downgrade(config, "0016_case_paper_handoffs")
        assert not columns & {column["name"] for column in inspect(connection).get_columns("projects")}
        command.upgrade(config, "0017_project_handover_lock")
        assert columns <= {column["name"] for column in inspect(connection).get_columns("projects")}
