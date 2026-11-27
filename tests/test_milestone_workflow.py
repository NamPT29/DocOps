"""Milestone regression: two boxes, one catalog discrepancy and one full handover."""
import hashlib
import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from test_arrangement_catalog import apply, db, dossier, world
from test_handover_package import SCHEMA, pdf_bytes
from test_project_upload_service import raw_item
from server.models import ProjectCase, ProjectMember, ProjectPolicy, ProjectDocumentAsset, Submission, User
from server.routers import submissions
from server.services import workflow_service as workflow, entry_qc_service as qc
from server.services import project_upload_service as upload, handover_package_service as package
from server.services.handover_lock_service import lock_project
from server.services.project_assignment_service import assign_case_input
from server.services.scan_ingestion_service import submit_scan_package, process_scan_package_background


def test_catalog_to_locked_handover(world, tmp_path, monkeypatch):
    db, project = world.db, world.project
    pid = project.id
    admin = dict(id=world.admin.id, role="admin", username="pm", full_name="PM", session_id="demo-admin")
    staff = dict(id=world.staff.id, role="user", username="nv1", full_name="NV1", session_id="demo-staff")
    project.form_schema_json_snapshot = json.dumps(SCHEMA, ensure_ascii=False)
    db.add(ProjectPolicy(project_id=pid, organ_code="DEMO"))
    for role, user in [("input", world.staff), ("reviewer", world.admin)]:
        db.add(ProjectMember(project_id=pid, user_id=user.id, member_role=role))
    db.commit()
    scan_root = tmp_path / "scan"
    handover = tmp_path / "handover"
    for key, path in [("DOCUMENT_SOURCE_ROOT", scan_root), ("PDF_STORAGE_PATH", tmp_path/"storage"), ("HANDOVER_DIR", handover)]:
        path.mkdir()
        monkeypatch.setenv(key, str(path))
    factory = sessionmaker(bind=db.get_bind())
    workflow.configure_workflow(db, project_id=pid, enabled_stage_keys=list(workflow.engine.STAGES_BY_KEY),
                                members={"scan":[world.staff.id]}, actor_user_id=admin["id"])
    apply(world, [dossier(1, 12), dossier(2, 12)])
    boxes = db.query(ProjectCase).order_by(ProjectCase.id).all()
    assert len(boxes) == 2

    def transition(box, stage, action, actor=admin):
        return workflow.transition_case_stage(db, project_id=pid, case_id=box.id, stage_key=stage, action=action, actor=actor)

    content = pdf_bytes(1)
    for number, box in enumerate(boxes, 1):
        transition(box, "arrangement", "start")
        transition(box, "arrangement", "complete")
        folder = scan_root / "nv1" / str(number)
        sub = folder / ("12" if number == 1 else "99")
        sub.mkdir(parents=True)
        (sub/"1.pdf").write_bytes(content)
        batch = submit_scan_package(db, project_id=pid, case_id=box.id, folder_path=folder.relative_to(scan_root).as_posix(), actor=staff)
        process_scan_package_background(batch.id, session_factory=factory)
        db.refresh(batch)
        assert batch.match_status == ("matched" if number == 1 else "mismatch")
        transition(box, "scan", "complete", staff)
        transition(box, "scan_qc", "start")
        if number == 2:
            with pytest.raises(HTTPException) as rejected:
                transition(box, "scan_qc", "complete")
            assert rejected.value.status_code == 409
        else:
            transition(box, "scan_qc", "complete")

    box = boxes[0]
    session = upload.create_or_resume_upload_session(db, project_id=pid, created_by_user_id=admin["id"],
                client_session_key="demo", raw_items=[raw_item("1/12/1.pdf", content)])
    upload.write_upload_chunk(db, session_id=session["id"], file_id=session["files"][0]["file_id"], offset=0, chunk=content)
    upload.finalize_upload_session(db, session_id=session["id"])
    assign_case_input(db, project_id=pid, case_id=box.id, user_id=staff["id"], actor_user_id=admin["id"])
    asset = db.query(ProjectDocumentAsset).one()
    values = {"_pdf_uuid": asset.storage_filename, "col_8":"Báo cáo", "col_9":"Về việc bàn giao"}
    request = submissions.SubmitRequest(template_id=project.template_id, data=values)
    submissions.api_submit(request, staff, db)
    sid = db.query(Submission).one().id
    def lease(actor):
        return submissions.api_claim_submission_view(sid, current_user=actor, db=db)["lease_token"]
    request.status = "pending_review"
    submissions.api_update_submission(sid, request, lease(staff), staff, db)
    submissions.api_release_submission_view(sid, current_user=staff, db=db)
    result = submissions.api_confirm_submission_review(sid, submissions.ReviewContentRequest(data={}), lease(admin), admin, db)
    assert result["submission_status"] == "completed"
    qc.finalize_round1(db, pid, box.id, admin)
    qc.sample_round2(db, pid, box.id, admin)
    with pytest.raises(HTTPException) as self_review:
        qc.check_round2_item(db, pid, box.id, sid, {}, admin)
    assert self_review.value.detail["code"] == "self_review"
    reviewer = User(username="qc2", full_name="QC2", password="x", role="admin")
    db.add(reviewer)
    db.commit()
    second = dict(id=reviewer.id, username="qc2", role="admin", full_name="QC2", session_id="demo-qc2")
    qc.check_round2_item(db, pid, box.id, sid, {}, second)
    qc.finalize_round2(db, pid, box.id, second)
    for stage in ["normalization", "handover"]:
        transition(box, stage, "start")
        transition(box, stage, "complete")
    package.start_package(db, project_id=pid, current_user=admin, session_factory=factory, runner=package.run_package)
    manifest, = handover.rglob("SHA256SUMS.txt")
    rows = manifest.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    digest, path = rows[0].split("  ", 1)
    assert hashlib.sha256((manifest.parent/path).read_bytes()).hexdigest() == digest
    assert list(manifest.parent.glob("*.docx"))
    assert (manifest.parent/"Metadata_NN-SIP.xlsx").is_file()
    lock_project(db, project_id=pid, note="Đã bàn giao", actor=admin)
    with pytest.raises(HTTPException) as locked:
        submissions.api_update_submission(sid, request, None, staff, db)
    assert locked.value.status_code == 423
