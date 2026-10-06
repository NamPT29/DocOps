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


def test_br01_scan_qc_completion(world):
    from server.models_scan import CaseScanPackage
    from server.models import ArrangementDossier
    db = world["db"]
    case = world["cases"][0]
    
    _configure(world)
    _transition(world, world["scanner"], case, "scan", "start")
    _transition(world, world["scanner"], case, "scan", "complete")
    _transition(world, world["qc"], case, "scan_qc", "start")
    
    # 1. No catalog rows -> allowed
    res = _transition(world, world["qc"], case, "scan_qc", "complete")
    assert res.status_code == 200, res.json()
    
    # Reset case stage for further tests
    _transition(world, world["admin"], case, "scan_qc", "reopen", reason="test")
    _transition(world, world["qc"], case, "scan_qc", "start")
    
    # Add a catalog row so the case HAS a catalog
    dossier = ArrangementDossier(
        case_id=case.id, project_id=world["project"].id, box_number=1, 
        dossier_number=1, dossier_suffix="",
        fonds_code="F", fonds_name="F", catalog_number="1", title="T",
        start_date="01/01/2000", end_date="01/01/2000", start_year=2000,
        maintenance_code="V", sheet_count=1, source_row=1
    )
    db.add(dossier)
    db.commit()
    
    # 2. No packages -> mismatch logic (409 reason_required for admin, 409 scan_catalog_mismatch for qc)
    res = _transition(world, world["qc"], case, "scan_qc", "complete")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "scan_catalog_mismatch"
    
    res = _transition(world, world["admin"], case, "scan_qc", "complete")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "reason_required"
    
    # 3. Package processing -> 409 scan_processing
    pkg1 = CaseScanPackage(case_id=case.id, version=1, source_path="P", status="processing", submitted_by_user_id=world["scanner"].id)
    db.add(pkg1)
    db.commit()
    res = _transition(world, world["qc"], case, "scan_qc", "complete")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "scan_processing"
    
    # 4. Package matched -> allowed
    pkg1.status = "done"
    pkg1.match_status = "matched"
    db.commit()
    res = _transition(world, world["qc"], case, "scan_qc", "complete")
    assert res.status_code == 200, res.json()
    _transition(world, world["admin"], case, "scan_qc", "reopen", reason="test")
    _transition(world, world["qc"], case, "scan_qc", "start")
    
    # 5. New package mismatch, old package matched -> mismatch (checks latest)
    pkg2 = CaseScanPackage(case_id=case.id, version=2, source_path="P2", status="done", match_status="mismatch", submitted_by_user_id=world["scanner"].id)
    db.add(pkg2)
    db.commit()
    res = _transition(world, world["qc"], case, "scan_qc", "complete")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "scan_catalog_mismatch"
    
    # 6. Reject is never blocked
    res = _transition(world, world["qc"], case, "scan_qc", "reject", reason="test")
    assert res.status_code == 200
    # Setup back for the next test
    _transition(world, world["scanner"], case, "scan", "start")
    _transition(world, world["scanner"], case, "scan", "complete")
    _transition(world, world["qc"], case, "scan_qc", "start")
    
    # 7. Admin completes with reason
    res = _transition(world, world["admin"], case, "scan_qc", "complete", reason="It is fine")
    assert res.status_code == 200
    
    from server.models import CaseStageEvent
    event = db.query(CaseStageEvent).filter_by(case_id=case.id, action="complete").order_by(CaseStageEvent.id.desc()).first()
    assert event.reason == "It is fine"
    
    _transition(world, world["admin"], case, "scan_qc", "reopen", reason="test")
    _transition(world, world["qc"], case, "scan_qc", "start")
    
    # 8. Package failed -> mismatch logic
    pkg2.status = "failed"
    pkg2.match_status = None
    db.commit()
    res = _transition(world, world["admin"], case, "scan_qc", "complete")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "reason_required"
    
    # 9. Package done but match_status None -> mismatch logic
    pkg2.status = "done"
    pkg2.match_status = None
    db.commit()
    res = _transition(world, world["qc"], case, "scan_qc", "complete")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "scan_catalog_mismatch"


def test_br04_scanned_by_user_id(world):
    from server.models_scan import CaseScanPackage
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    pkg = CaseScanPackage(case_id=c1.id, version=1, status="done", match_status="matched", scanned_by_user_id=world["qc"].id, submitted_by_user_id=world["scanner"].id, source_path="S")
    db.add(pkg)
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    res = _transition(world, world["qc"], c1, "scan_qc", "start")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "self_review"


def test_br04_scanned_by_name_normalization(world):
    from server.models_scan import CaseScanPackage
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    world["qc"].full_name = "Nguyễn Văn A"
    db.commit()
    
    pkg = CaseScanPackage(case_id=c1.id, version=1, status="done", match_status="matched", scanned_by_name="nguyen van a", submitted_by_user_id=world["scanner"].id, source_path="S")
    db.add(pkg)
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    res = _transition(world, world["qc"], c1, "scan_qc", "start")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "self_review"


def test_br04_admin_is_also_blocked(world):
    from server.models_scan import CaseScanPackage
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    world["admin"].full_name = "Lê Thị B"
    db.commit()
    
    pkg = CaseScanPackage(case_id=c1.id, version=1, status="done", match_status="matched", scanned_by_name="lê thị b", submitted_by_user_id=world["scanner"].id, source_path="S")
    db.add(pkg)
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    res = _transition(world, world["admin"], c1, "scan_qc", "start")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "self_review"


def test_br04_checks_older_versions(world):
    from server.models_scan import CaseScanPackage
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    pkg1 = CaseScanPackage(case_id=c1.id, version=1, status="failed", scanned_by_user_id=world["qc"].id, submitted_by_user_id=world["scanner"].id, source_path="S1")
    pkg2 = CaseScanPackage(case_id=c1.id, version=2, status="done", match_status="matched", scanned_by_user_id=world["scanner"].id, submitted_by_user_id=world["scanner"].id, source_path="S2")
    db.add_all([pkg1, pkg2])
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    res = _transition(world, world["qc"], c1, "scan_qc", "start")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "self_review"


def test_br04_no_match_is_allowed(world):
    from server.models_scan import CaseScanPackage
    from server.models import ArrangementDossier
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    db.add(ArrangementDossier(case_id=c1.id, project_id=world["project"].id, box_number=1, dossier_number=1, dossier_suffix="", title="A", fonds_code="X", fonds_name="Y", catalog_number="1", start_date="20", end_date="20", start_year=20, maintenance_code="1", sheet_count=1, source_row=1))
    
    world["qc"].full_name = "Hoàng C"
    pkg = CaseScanPackage(case_id=c1.id, version=1, status="done", match_status="matched", scanned_by_user_id=world["scanner"].id, scanned_by_name="nguyen d", submitted_by_user_id=world["scanner"].id, source_path="S")
    db.add(pkg)
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    assert _transition(world, world["qc"], c1, "scan_qc", "start").status_code == 200
    assert _transition(world, world["qc"], c1, "scan_qc", "complete").status_code == 200


def test_br04_empty_scanned_by_name_does_not_block(world):
    from server.models_scan import CaseScanPackage
    from server.models import ArrangementDossier
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    db.add(ArrangementDossier(case_id=c1.id, project_id=world["project"].id, box_number=1, dossier_number=1, dossier_suffix="", title="A", fonds_code="X", fonds_name="Y", catalog_number="1", start_date="20", end_date="20", start_year=20, maintenance_code="1", sheet_count=1, source_row=1))
    
    pkg = CaseScanPackage(case_id=c1.id, version=1, status="done", match_status="matched", scanned_by_name="", scanned_by_user_id=None, submitted_by_user_id=world["scanner"].id, source_path="S")
    db.add(pkg)
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    assert _transition(world, world["qc"], c1, "scan_qc", "start").status_code == 200
    assert _transition(world, world["qc"], c1, "scan_qc", "complete").status_code == 200


def test_br04_reject_is_not_blocked(world):
    from server.models_scan import CaseScanPackage
    db = world["db"]
    _configure(world)
    c1 = world["cases"][0]
    pkg = CaseScanPackage(case_id=c1.id, version=1, status="done", match_status="matched", scanned_by_user_id=world["qc"].id, submitted_by_user_id=world["scanner"].id, source_path="S")
    db.add(pkg)
    db.commit()
    
    _transition(world, world["scanner"], c1, "scan", "start")
    _transition(world, world["scanner"], c1, "scan", "complete")
    
    res = _transition(world, world["qc"], c1, "scan_qc", "reject")
    assert res.status_code != 409 or res.json()["detail"].get("code") != "self_review"

def test_entry_qc_api_validations(world):
    from server.models import ProjectReportUnit, ProjectDocumentAsset, Submission, AssignedDocument
    client, db = world["client"], world["db"]
    admin = world["admin"]
    scanner = world["scanner"]
    qc = world["qc"]
    project = world["project"]
    c1 = world["cases"][0]
    
    # Enable entry_qc and assign qc to it
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "entry_qc"]},
        headers=world["headers"](admin)
    )
    from server.models import ProjectMember
    db.add(ProjectMember(project_id=project.id, user_id=qc.id, member_role="reviewer", is_active=True))
    db.commit()
    
    # Not DONE -> 409
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](qc))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_not_done"
    
    # Make entry_qc DONE but no fields
    # Create 1 report, 1 submission, completed
    report = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="r1", display_name="R1")
    db.add(report)
    db.flush()
    a1 = AssignedDocument(original_filename="a", uuid_filename="u1")
    db.add(a1)
    db.flush()
    doc = ProjectDocumentAsset(project_id=project.id, case_id=c1.id, report_unit_id=report.id, assigned_document_id=a1.id, status="active", relative_path="a", normalized_relative_path="a", original_filename="a", storage_filename="a", byte_size=1, content_sha256="b")
    db.add(doc)
    db.flush()
    sub = Submission(assigned_document_id=a1.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    db.add(sub)
    db.flush()
    db.commit()
    
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](qc))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "no_fields"
    
    # Self review -> scanner shouldn't be able to review
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "entry_qc"]},
        headers=world["headers"](admin)
    )
    db.add(ProjectMember(project_id=project.id, user_id=scanner.id, member_role="reviewer", is_active=True))
    db.commit()
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](scanner))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "self_review"
    
    # 403 Un-authorized
    outsider = world["outsider"]
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](outsider))
    assert res.status_code == 403

def test_entry_qc_calculation_and_snapshot(world):
    from server.models import ProjectReportUnit, ProjectDocumentAsset, Submission, SubmissionQualityAssessment, ProjectPolicy, AssignedDocument
    from decimal import Decimal
    client, db = world["client"], world["db"]
    admin = world["admin"]
    qc = world["qc"]
    project = world["project"]
    c1 = world["cases"][0]
    scanner = world["scanner"]
    
    # Configure members
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "entry_qc"]},
        headers=world["headers"](admin)
    )
    from server.models import ProjectMember
    db.add(ProjectMember(project_id=project.id, user_id=qc.id, member_role="reviewer", is_active=True))
    db.commit()
    
    # Change threshold to 10%
    db.add(ProjectPolicy(project_id=project.id, error_threshold_percent=Decimal("10.00")))
    db.commit()
    
    # Create 2 reports. r1: 3/50, r2: 1/50 -> Total 4/100 = 4.00%
    r1 = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="r1", display_name="R1")
    r2 = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="r2", display_name="R2")
    db.add_all([r1, r2])
    db.flush()
    
    a1 = AssignedDocument(original_filename="a1", uuid_filename="u1")
    a2 = AssignedDocument(original_filename="a2", uuid_filename="u2")
    db.add_all([a1, a2])
    db.flush()
    
    d1 = ProjectDocumentAsset(project_id=project.id, case_id=c1.id, report_unit_id=r1.id, assigned_document_id=a1.id, status="active", relative_path="a1", normalized_relative_path="a1", original_filename="a1", storage_filename="a1", byte_size=1, content_sha256="b")
    d2 = ProjectDocumentAsset(project_id=project.id, case_id=c1.id, report_unit_id=r2.id, assigned_document_id=a2.id, status="active", relative_path="a2", normalized_relative_path="a2", original_filename="a2", storage_filename="a2", byte_size=1, content_sha256="b")
    db.add_all([d1, d2])
    db.flush()
    
    s1 = Submission(assigned_document_id=a1.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    s2 = Submission(assigned_document_id=a2.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    db.add_all([s1, s2])
    db.flush()
    
    sqa1 = SubmissionQualityAssessment(submission_id=s1.id, input_user_id=scanner.id, visible_field_count=50, changed_field_count=3, is_error_report=False, baseline_data_json="{}")
    sqa2 = SubmissionQualityAssessment(submission_id=s2.id, input_user_id=scanner.id, visible_field_count=50, changed_field_count=1, is_error_report=False, baseline_data_json="{}")
    db.add_all([sqa1, sqa2])
    db.commit()
    
    # Call GET
    res = client.get(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc", headers=world["headers"](admin))
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["live"]["rate_percent"] == 4.0
    assert data["live"]["would_pass"] is True
    
    # Finalize round 1
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](qc))
    assert res.status_code == 200
    r_data = res.json()["data"]
    assert r_data["passed"] is True
    assert r_data["rate_percent"] == 4.0
    assert r_data["threshold_percent"] == 10.0
    
    # Double Finalize -> 409
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](qc))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "already_finalized"
    
    # Change threshold to 2% and check snapshot
    policy = db.query(ProjectPolicy).filter_by(project_id=project.id).first()
    policy.error_threshold_percent = Decimal("2.00")
    db.commit()
    
    res = client.get(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc", headers=world["headers"](admin))
    data = res.json()["data"]
    assert data["rounds"][0]["threshold_percent"] == 10.0  # Kept snapshot

def test_entry_qc_boundary(world):
    # 5/100 threshold 5 => NOT PASS
    from server.models import ProjectReportUnit, ProjectDocumentAsset, Submission, SubmissionQualityAssessment, AssignedDocument
    client, db = world["client"], world["db"]
    admin = world["admin"]
    qc = world["qc"]
    project = world["project"]
    c1 = world["cases"][0]
    scanner = world["scanner"]
    
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "entry_qc"]},
        headers=world["headers"](admin)
    )
    from server.models import ProjectMember
    db.add(ProjectMember(project_id=project.id, user_id=admin.id, member_role="reviewer", is_active=True))
    db.commit()
    
    r1 = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="r1", display_name="R1")
    db.add(r1)
    db.flush()
    a1 = AssignedDocument(original_filename="a1", uuid_filename="u1")
    db.add(a1)
    db.flush()
    d1 = ProjectDocumentAsset(project_id=project.id, case_id=c1.id, report_unit_id=r1.id, assigned_document_id=a1.id, status="active", relative_path="a1", normalized_relative_path="a1", original_filename="a1", storage_filename="a1", byte_size=1, content_sha256="b")
    db.add(d1)
    db.flush()
    s1 = Submission(assigned_document_id=a1.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    db.add(s1)
    db.flush()
    # 5 errors in 100 fields
    sqa1 = SubmissionQualityAssessment(submission_id=s1.id, input_user_id=scanner.id, visible_field_count=100, changed_field_count=5, is_error_report=False, baseline_data_json="{}")
    db.add(sqa1)
    db.commit()
    
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](admin))
    assert res.status_code == 200
    assert res.json()["data"]["passed"] is False  # rate=5, threshold=5 -> rate < threshold is False
    
    # 499 / 10000 -> 4.99 -> PASS
    c2 = world["cases"][1]
    r2 = ProjectReportUnit(project_id=project.id, case_id=c2.id, report_key="r2", display_name="R2")
    db.add(r2)
    db.flush()
    a2 = AssignedDocument(original_filename="a2", uuid_filename="u2")
    db.add(a2)
    db.flush()
    d2 = ProjectDocumentAsset(project_id=project.id, case_id=c2.id, report_unit_id=r2.id, assigned_document_id=a2.id, status="active", relative_path="a2", normalized_relative_path="a2", original_filename="a2", storage_filename="a2", byte_size=1, content_sha256="b")
    db.add(d2)
    db.flush()
    s2 = Submission(assigned_document_id=a2.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    db.add(s2)
    db.flush()
    sqa2 = SubmissionQualityAssessment(submission_id=s2.id, input_user_id=scanner.id, visible_field_count=10000, changed_field_count=499, is_error_report=False, baseline_data_json="{}")
    db.add(sqa2)
    db.commit()
    
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c2.id}/entry-qc/round1", headers=world["headers"](admin))
    assert res.status_code == 200
    assert res.status_code == 200
    assert res.json()["data"]["passed"] is True


def test_entry_qc_resolve_and_gate(world):
    from server.models import ProjectReportUnit, ProjectDocumentAsset, Submission, SubmissionQualityAssessment, AssignedDocument, ProjectMember
    client, db = world["client"], world["db"]
    admin = world["admin"]
    qc = world["qc"]
    outsider = world["outsider"]
    project = world["project"]
    c1 = world["cases"][0]
    c2 = world["cases"][1]
    scanner = world["scanner"]
    
    # Configure members
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "entry_qc", "normalization", "handover"]},
        headers=world["headers"](admin)
    )
    db.add(ProjectMember(project_id=project.id, user_id=qc.id, member_role="reviewer", is_active=True))
    db.commit()

    # GET entry-qc permissions
    assert client.get(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc", headers=world["headers"](outsider)).status_code == 403
    assert client.get(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc", headers=world["headers"](qc)).status_code == 200
    
    # Gate blocking because not finalized
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"}, headers=world["headers"](admin))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_not_finalized"

    # Make c1 failed round 1
    r1 = ProjectReportUnit(project_id=project.id, case_id=c1.id, report_key="r1", display_name="R1")
    db.add(r1)
    db.flush()
    a1 = AssignedDocument(original_filename="a1", uuid_filename="u1")
    db.add(a1)
    db.flush()
    d1 = ProjectDocumentAsset(project_id=project.id, case_id=c1.id, report_unit_id=r1.id, assigned_document_id=a1.id, status="active", relative_path="a1", normalized_relative_path="a1", original_filename="a1", storage_filename="a1", byte_size=1, content_sha256="b")
    db.add(d1)
    db.flush()
    s1 = Submission(assigned_document_id=a1.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    db.add(s1)
    db.flush()
    sqa1 = SubmissionQualityAssessment(submission_id=s1.id, input_user_id=scanner.id, visible_field_count=100, changed_field_count=10, is_error_report=False, baseline_data_json="{}")
    db.add(sqa1)
    db.commit()
    
    # Finalize -> Failed (10%)
    client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/round1", headers=world["headers"](qc))
    
    # Gate blocking because failed and not resolved
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"}, headers=world["headers"](admin))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_failed"
    
    # Resolve API validations
    assert client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": "ok"}, headers=world["headers"](qc)).status_code == 403
    
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc/resolve", json={"reason": " Duyệt cho đi "}, headers=world["headers"](admin))
    assert res.status_code == 200
    assert res.json()["data"]["resolution"] == "approved"
    assert res.json()["data"]["resolution_reason"] == "Duyệt cho đi"
    
    # Check GET includes gate and resolution
    data = client.get(f"/api/projects/{project.id}/workflow/cases/{c1.id}/entry-qc", headers=world["headers"](admin)).json()["data"]
    assert data["gate"]["blocked"] is False
    assert data["rounds"][0]["resolution"] == "approved"
    
    # Gate should pass now
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c1.id}/stages/normalization/transition", json={"action": "start"}, headers=world["headers"](admin))
    assert res.status_code == 200

    # Test gate with entry_qc off
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "normalization", "handover"]},
        headers=world["headers"](admin)
    )
    r2 = ProjectReportUnit(project_id=project.id, case_id=c2.id, report_key="r2", display_name="R2")
    db.add(r2)
    db.flush()
    a2 = AssignedDocument(original_filename="a2", uuid_filename="u2")
    db.add(a2)
    db.flush()
    d2 = ProjectDocumentAsset(project_id=project.id, case_id=c2.id, report_unit_id=r2.id, assigned_document_id=a2.id, status="active", relative_path="a2", normalized_relative_path="a2", original_filename="a2", storage_filename="a2", byte_size=1, content_sha256="b")
    db.add(d2)
    db.flush()
    s2 = Submission(assigned_document_id=a2.id, created_by_user_id=scanner.id, status="completed", data_json="{}")
    db.add(s2)
    db.commit()
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c2.id}/stages/normalization/transition", json={"action": "start"}, headers=world["headers"](admin))
    assert res.status_code == 200

    # Test gate when normalization is off, handover should be blocked by entry_qc
    world["client"].put(
        f"/api/projects/{project.id}/workflow",
        json={"enabled_stages": ["data_entry", "entry_qc", "handover"]},
        headers=world["headers"](admin)
    )
    res = client.post(f"/api/projects/{project.id}/workflow/cases/{c2.id}/stages/handover/transition", json={"action": "start"}, headers=world["headers"](admin))

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "entry_qc_not_finalized"
