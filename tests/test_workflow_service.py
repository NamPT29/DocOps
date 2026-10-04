from datetime import timedelta

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db, get_utc_now
from server.models import (
    AssignedDocument,
    CaseStageEvent,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectReportUnit,
    Submission,
    Template,
    User,
    UserLoginSession,
)
from server.routers import workflow
from server.routers.auth import ALGORITHM, SECRET_KEY

ALL_STAGES = [
    "arrangement", "scan", "scan_qc", "data_entry", "entry_qc", "normalization", "handover",
]


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'workflow.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_TOKENS = {}


def _token(db, user):
    key = (id(db), user.id)
    if key in _TOKENS:
        return _TOKENS[key]
    login = UserLoginSession(
        session_id=f"s-{user.id}", user_id=user.id, browser_id=f"b-{user.id}",
        expires_at=get_utc_now() + timedelta(minutes=10),
    )
    db.add(login)
    db.commit()
    _TOKENS[key] = jwt.encode(
        {"sub": str(user.id), "sid": login.session_id}, SECRET_KEY, algorithm=ALGORITHM
    )
    return _TOKENS[key]


@pytest.fixture()
def world(db):
    admin = User(username="wf-admin", password="x", role="admin")
    scanner = User(username="wf-scanner", password="x", role="user")
    qc = User(username="wf-qc", password="x", role="user")
    outsider = User(username="wf-out", password="x", role="user")
    template = Template(name="t", filename="t.xlsx", is_active=True)
    db.add_all([admin, scanner, qc, outsider, template])
    db.flush()
    project = Project(
        name="P", root_folder_name="p", template_id=template.id,
        template_name_snapshot="t", template_filename_snapshot="t.xlsx",
        case_level=1, report_mode="pdf", created_by_user_id=admin.id,
    )
    db.add(project)
    db.flush()
    cases = []
    for key in ("001", "002"):
        case = ProjectCase(project_id=project.id, case_key=key, display_name=key)
        db.add(case)
        cases.append(case)
    db.flush()
    db.commit()

    app = FastAPI()
    app.include_router(workflow.router)
    app.include_router(workflow.catalog_router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    def headers(user):
        return {"Authorization": f"Bearer {_token(db, user)}"}

    return {
        "db": db, "client": client, "headers": headers, "project": project,
        "cases": cases, "admin": admin, "scanner": scanner, "qc": qc, "outsider": outsider,
    }


def _configure(world, enabled=None, members=None):
    if enabled is None:
        enabled = ["scan", "scan_qc", "data_entry", "entry_qc"]
    members = members if members is not None else {
        "scan": [world["scanner"].id], "scan_qc": [world["qc"].id],
    }
    return world["client"].put(
        f"/api/projects/{world['project'].id}/workflow",
        json={"enabled_stages": enabled, "members": members},
        headers=world["headers"](world["admin"]),
    )


def _transition(world, user, case, stage, action, reason=None):
    return world["client"].post(
        f"/api/projects/{world['project'].id}/workflow/cases/{case.id}/stages/{stage}/transition",
        json={"action": action, "reason": reason},
        headers=world["headers"](user),
    )


def test_new_tables_match_migrated_schema(tmp_path):
    pytest.importorskip("alembic")
    from server.migration_runner import upgrade_database
    from pathlib import Path

    engine = create_engine("sqlite+pysqlite:///:memory:")
    upgrade_database(engine, base_dir=Path(__file__).resolve().parents[1])
    migrated = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not table.info.get("revision"):
            continue
        assert {c["name"] for c in migrated.get_columns(table.name)} == {
            c.name for c in table.columns
        }
        assert {i["name"] for i in migrated.get_indexes(table.name)} >= {
            i.name for i in table.indexes
        }


def test_config_requires_admin_and_validates(world):
    client, project = world["client"], world["project"]
    forbidden = client.put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["scan"]},
        headers=world["headers"](world["scanner"]),
    )
    assert forbidden.status_code == 403

    assert _configure(world, enabled=[]).status_code == 400
    assert _configure(world, enabled=["nope"]).status_code == 400
    # a QC stage needs the stage it reviews
    assert _configure(world, enabled=["scan_qc"]).status_code == 400
    # BA 3.3: admins may work any stage; normalization/handover are admin-only
    assert _configure(world, members={"scan": [world["admin"].id]}).status_code == 200
    staff_on_admin_stage = _configure(
        world,
        enabled=["normalization", "handover"],
        members={"handover": [world["scanner"].id]},
    )
    assert staff_on_admin_stage.status_code == 400
    assert "chỉ dành cho: Admin" in staff_on_admin_stage.json()["detail"]

    ok = _configure(world)
    assert ok.status_code == 200
    stages = {s["key"]: s for s in ok.json()["data"]["stages"]}
    assert stages["scan"]["enabled"] and stages["scan"]["member_user_ids"] == [world["scanner"].id]
    assert not stages["handover"]["enabled"]
    assert ok.json()["data"]["configured"] is True


def test_ctv_only_joins_stages_that_allow_ctv(world):
    # FR-AUT-03: allowed_roles "staff" means Hành chính, so CTV is excluded.
    ctv = User(
        username="wf-ctv", password="x", role="user", account_type="ctv",
        expires_on=get_utc_now().date() + timedelta(days=30),
    )
    world["db"].add(ctv)
    world["db"].commit()

    refused = _configure(world, members={"scan": [ctv.id], "scan_qc": [world["qc"].id]})
    assert refused.status_code == 400
    assert "chỉ dành cho: Admin, Hành chính" in refused.json()["detail"]
    # Hành chính keeps working the same stage.
    assert _configure(world).status_code == 200


def test_full_cycle_with_reject_rework_and_audit(world):
    _configure(world)
    c1 = world["cases"][0]
    scanner, qc, admin = world["scanner"], world["qc"], world["admin"]

    # QC cannot start before scanning is done
    assert _transition(world, qc, c1, "scan_qc", "start").status_code == 409
    # an outsider has no rights on the stage
    assert _transition(world, world["outsider"], c1, "scan", "start").status_code == 403

    assert _transition(world, scanner, c1, "scan", "start").status_code == 200
    assert _transition(world, scanner, c1, "scan", "complete").status_code == 200
    assert _transition(world, qc, c1, "scan_qc", "start").status_code == 200
    # reject needs a reason
    assert _transition(world, qc, c1, "scan_qc", "reject").status_code == 400
    rejected = _transition(world, qc, c1, "scan_qc", "reject", "thiếu trang 3")
    assert rejected.status_code == 200
    assert rejected.json()["data"]["statuses"] == {"scan_qc": "pending", "scan": "rejected"}

    overview = world["client"].get(
        f"/api/projects/{world['project'].id}/workflow/overview",
        headers=world["headers"](admin),
    ).json()["data"]
    scan = next(s for s in overview["stages"] if s["key"] == "scan")
    assert scan["counts"]["rejected"] == 1 and scan["rework_total"] == 1

    # rework, then QC passes
    assert _transition(world, scanner, c1, "scan", "start").status_code == 200
    assert _transition(world, scanner, c1, "scan", "complete").status_code == 200
    assert _transition(world, qc, c1, "scan_qc", "start").status_code == 200
    assert _transition(world, qc, c1, "scan_qc", "complete").status_code == 200

    events = world["client"].get(
        f"/api/projects/{world['project'].id}/workflow/cases/{c1.id}/events",
        headers=world["headers"](admin),
    ).json()["data"]
    assert [e["action"] for e in reversed(events)][:3] == ["start", "complete", "start"]
    assert any(e["action"] == "returned" and e["to_status"] == "rejected" for e in events)

    # only admins can reopen, and a reason is required
    assert _transition(world, scanner, c1, "scan", "reopen", "x").status_code == 403
    assert _transition(world, admin, c1, "scan", "reopen").status_code == 400


def test_qc_cannot_review_work_they_did_themselves(world):
    db = world["db"]
    # give the QC user scanner rights too, then have them scan and try to self-review
    _configure(world, members={
        "scan": [world["scanner"].id, world["qc"].id], "scan_qc": [world["qc"].id],
    })
    c1 = world["cases"][0]
    qc = world["qc"]
    assert _transition(world, qc, c1, "scan", "start").status_code == 200
    assert _transition(world, qc, c1, "scan", "complete").status_code == 200
    blocked = _transition(world, qc, c1, "scan_qc", "start")
    assert blocked.status_code == 403
    assert db.query(CaseStageEvent).filter_by(stage_key="scan_qc").count() == 0


def test_my_work_lists_only_actionable_cases(world):
    _configure(world)
    c1, c2 = world["cases"]
    project_id = world["project"].id
    mine = world["client"].get(
        f"/api/projects/{project_id}/workflow/my-work", headers=world["headers"](world["scanner"])
    ).json()["data"]
    assert {(i["case_id"], i["stage_key"]) for i in mine} == {(c1.id, "scan"), (c2.id, "scan")}
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    mine = world["client"].get(
        f"/api/projects/{project_id}/workflow/my-work", headers=world["headers"](world["scanner"])
    ).json()["data"]
    assert {(i["case_id"], i["stage_key"]) for i in mine} == {(c2.id, "scan")}
    qc_work = world["client"].get(
        f"/api/projects/{project_id}/workflow/my-work", headers=world["headers"](world["qc"])
    ).json()["data"]
    assert {(i["case_id"], i["stage_key"]) for i in qc_work} == {(c1.id, "scan_qc")}
    other = world["client"].get(
        f"/api/projects/{project_id}/workflow/my-work", headers=world["headers"](world["outsider"])
    ).json()["data"]
    assert other == []


def test_admin_assignment_requires_stage_membership(world):
    _configure(world)
    c1 = world["cases"][0]
    url = f"/api/projects/{world['project'].id}/workflow/cases/{c1.id}/stages/scan/assignee"
    admin_headers = world["headers"](world["admin"])
    assert world["client"].put(url, json={"user_id": world["qc"].id}, headers=admin_headers).status_code == 400
    assert world["client"].put(url, json={"user_id": world["scanner"].id}, headers=admin_headers).status_code == 200
    # another member cannot complete a case assigned to someone else
    _transition(world, world["scanner"], c1, "scan", "start")
    assert _transition(world, world["scanner"], c1, "scan", "complete").status_code == 200


def test_entry_stages_are_derived_from_submissions(world):
    db = world["db"]
    project, c1, c2 = world["project"], *world["cases"]
    report = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="001/a", display_name="a")
    db.add(report)
    db.flush()
    document = AssignedDocument(
        original_filename="a.pdf", uuid_filename="a-uuid.pdf", template_id=project.template_id,
        status="pending",
    )
    db.add(document)
    db.flush()
    db.add(ProjectDocumentAsset(
        project_id=project.id, case_id=c1.id, report_unit_id=report.id,
        assigned_document_id=document.id, relative_path="001/a.pdf",
        normalized_relative_path="001/a.pdf", original_filename="a.pdf",
        storage_filename="a-uuid.pdf", content_sha256="0" * 64, byte_size=1, status="active",
    ))
    db.commit()

    _configure(world, enabled=["data_entry", "entry_qc"], members={})

    def overview():
        data = world["client"].get(
            f"/api/projects/{project.id}/workflow/overview",
            headers=world["headers"](world["admin"]),
        ).json()["data"]
        return {s["key"]: s["counts"] for s in data["stages"] if s["enabled"]}

    assert overview()["data_entry"]["pending"] == 2

    submission = Submission(
        data_json="{}", template_id=project.template_id,
        assigned_document_id=document.id, status="pending_review",
    )
    db.add(submission)
    db.commit()
    counts = overview()
    assert counts["data_entry"]["done"] == 1 and counts["data_entry"]["pending"] == 1
    assert counts["entry_qc"]["in_progress"] == 1

    submission.status = "completed"
    db.commit()
    assert overview()["entry_qc"]["done"] == 1

    manual = _transition(world, world["admin"], c1, "data_entry", "start")
    assert manual.status_code == 409
    assert manual.json()["detail"]["code"] == "stage_derived"


def test_first_configuration_backfills_upstream_stages_for_cases_with_pdfs(world):
    db = world["db"]
    project, c1, c2 = world["project"], *world["cases"]
    report = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="001/a", display_name="a")
    db.add(report)
    db.flush()
    db.add(ProjectDocumentAsset(
        project_id=project.id, case_id=c1.id, report_unit_id=report.id,
        relative_path="001/a.pdf", normalized_relative_path="001/a.pdf",
        original_filename="a.pdf", storage_filename="b-uuid.pdf",
        content_sha256="1" * 64, byte_size=1, status="active",
    ))
    db.commit()

    result = _configure(world)
    assert result.json()["data"]["backfilled_states"] == 2  # scan + scan_qc for case 001
    cases = world["client"].get(
        f"/api/projects/{project.id}/workflow/cases", headers=world["headers"](world["admin"])
    ).json()["data"]["items"]
    by_key = {item["case_key"]: item for item in cases}
    assert by_key["001"]["stages"]["scan_qc"]["status"] == "done"
    assert by_key["001"]["stages"]["scan"]["status"] == "done"
    assert by_key["002"]["stages"]["scan"]["status"] == "pending"

    # reconfiguring later must not backfill again
    again = _configure(world)
    assert again.json()["data"]["backfilled_states"] == 0


def test_catalog_and_unknown_project(world):
    catalog = world["client"].get(
        "/api/workflow/stages", headers=world["headers"](world["outsider"])
    ).json()["data"]
    assert [s["key"] for s in catalog] == ALL_STAGES
    missing = world["client"].get(
        "/api/projects/9999/workflow", headers=world["headers"](world["admin"])
    )
    assert missing.status_code == 404


def test_admin_is_also_bound_by_no_self_review(world):
    """BR-04: an admin who scanned a case cannot pass its scan check either."""
    _configure(world)
    c1 = world["cases"][0]
    admin = world["admin"]
    assert _transition(world, admin, c1, "scan", "start").status_code == 200
    assert _transition(world, admin, c1, "scan", "complete").status_code == 200
    blocked = _transition(world, admin, c1, "scan_qc", "start")
    assert blocked.status_code == 403
    # a different person can check it
    assert _transition(world, world["qc"], c1, "scan_qc", "start").status_code == 200


def test_admin_start_keeps_existing_assignee(world):
    _configure(world)
    c1 = world["cases"][0]
    url = f"/api/projects/{world['project'].id}/workflow/cases/{c1.id}/stages/scan/assignee"
    world["client"].put(url, json={"user_id": world["scanner"].id}, headers=world["headers"](world["admin"]))
    assert _transition(world, world["admin"], c1, "scan", "start").status_code == 200
    cases = world["client"].get(
        f"/api/projects/{world['project'].id}/workflow/cases",
        headers=world["headers"](world["admin"]),
    ).json()["data"]["items"]
    scan = next(item for item in cases if item["case_id"] == c1.id)["stages"]["scan"]
    assert scan["assigned_user_id"] == world["scanner"].id
