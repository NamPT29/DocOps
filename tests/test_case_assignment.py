from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    CaseInputAssignment,
    CaseStageState,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectMember,
    ProjectPolicy,
    ProjectReportUnit,
    ProjectStage,
    Submission,
    SubmissionReviewAssignment,
    Template,
    User,
)
from server.utils.folder_utils import folder_path_key
from server.services.project_admin_service import update_project_members
from server.services.project_assignment_service import (
    assign_case_input,
    assign_unassigned_project_cases,
    list_action_needed_cases,
    list_ready_input_cases,
    revoke_case_input,
)
from server.services.project_policy_service import update_project_policy
from server.services.review_workflow_service import ReviewWorkflowService
from server.repositories.review_repository import ReviewRepository
from server.repositories.submission_view_repository import SubmissionViewRepository
from server.routers.submissions import api_update_submission, SubmitRequest


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'case-assignment.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def create_user(db, username, role="user", account_type="staff", is_locked=False, expires_on=None):
    user = User(
        username=username,
        password="hash",
        role=role,
        account_type=account_type,
        is_locked=is_locked,
        expires_on=expires_on,
    )
    db.add(user)
    db.flush()
    return user


def seed_test_project(db, *, name="Test Project", case_count=3):
    admin = create_user(db, f"admin-{name.lower().replace(' ', '-')}", role="admin")
    input1 = create_user(db, f"input1-{name.lower().replace(' ', '-')}")
    input2 = create_user(db, f"input2-{name.lower().replace(' ', '-')}")
    reviewer = create_user(db, f"rev-{name.lower().replace(' ', '-')}")
    template = Template(name=f"Template {name}", filename="template.xlsm")
    db.add(template)
    db.flush()

    project = Project(
        name=name,
        root_folder_name=f"root-{name.lower().replace(' ', '-')}",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        case_level=1,
        report_mode="pdf",
        created_by_user_id=admin.id,
    )
    db.add(project)
    db.flush()

    db.add_all([
        ProjectMember(project_id=project.id, user_id=input1.id, member_role="input"),
        ProjectMember(project_id=project.id, user_id=input2.id, member_role="input"),
        ProjectMember(project_id=project.id, user_id=reviewer.id, member_role="reviewer"),
    ])

    cases = []
    for i in range(1, case_count + 1):
        case = ProjectCase(
            project_id=project.id,
            case_key=f"box-{i:03d}",
            display_name=f"Hộp {i:03d}",
        )
        db.add(case)
        db.flush()

        report = ProjectReportUnit(
            project_id=project.id,
            case_id=case.id,
            report_key=f"box-{i:03d}/doc1.pdf",
            display_name="doc1.pdf",
        )
        db.add(report)
        db.flush()

        doc = AssignedDocument(
            original_filename="doc1.pdf",
            uuid_filename=f"doc-{project.id}-{case.id}.pdf",
            assigned_to_user_id=None,
            template_id=template.id,
            status="pending",
        )
        db.add(doc)
        db.flush()

        asset = ProjectDocumentAsset(
            project_id=project.id,
            case_id=case.id,
            report_unit_id=report.id,
            assigned_document_id=doc.id,
            relative_path=f"box-{i:03d}/doc1.pdf",
            normalized_relative_path=f"box-{i:03d}/doc1.pdf",
            original_filename="doc1.pdf",
            storage_filename=doc.uuid_filename,
            content_sha256="0" * 64,
            byte_size=1024,
            status="active",
        )
        db.add(asset)
        cases.append(case)

    db.flush()
    return admin, input1, input2, reviewer, project, cases, template


def test_case_input_assignment_lifecycle_and_due_at(database):
    admin, input1, input2, reviewer, project, cases, _ = seed_test_project(database, name="P1", case_count=1)
    case = cases[0]

    # Assign case to input1
    result = assign_case_input(
        database,
        project_id=project.id,
        case_id=case.id,
        user_id=input1.id,
        actor_user_id=admin.id,
    )
    assert result["status"] == "ok"
    assert case.assigned_input_user_id == input1.id

    assignment = database.scalars(
        select(CaseInputAssignment).where(
            CaseInputAssignment.case_id == case.id,
            CaseInputAssignment.ended_at.is_(None),
        )
    ).one()
    assert assignment.user_id == input1.id
    assert assignment.assigned_by_user_id == admin.id
    assert assignment.deadline_days == 2  # default QC-01
    assert assignment.due_at == assignment.assigned_at + timedelta(days=2)

    # Changing policy afterward does NOT alter existing due_at
    update_project_policy(
        database,
        project_id=project.id,
        values={"box_deadline_days": 10},
        actor_user_id=admin.id,
    )
    database.refresh(assignment)
    assert assignment.deadline_days == 2


def test_case_input_assignment_unique_active_constraint(database):
    admin, input1, input2, reviewer, project, cases, _ = seed_test_project(database, name="P2", case_count=1)
    case = cases[0]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    first = CaseInputAssignment(
        project_id=project.id,
        case_id=case.id,
        user_id=input1.id,
        assigned_by_user_id=admin.id,
        assigned_at=now,
        due_at=now + timedelta(days=2),
        deadline_days=2,
    )
    database.add(first)
    database.commit()

    # Second active assignment on same case should violate partial unique index
    second = CaseInputAssignment(
        project_id=project.id,
        case_id=case.id,
        user_id=input2.id,
        assigned_by_user_id=admin.id,
        assigned_at=now,
        due_at=now + timedelta(days=2),
        deadline_days=2,
    )
    database.add(second)
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_auto_assign_respects_r3_conditions(database):
    admin, input1, input2, reviewer, project, cases, _ = seed_test_project(database, name="P3", case_count=3)

    # Condition (a): locked or expired CTV is skipped
    input2.is_locked = True
    database.commit()

    result = assign_unassigned_project_cases(database, project_id=project.id, changed_by_user_id=admin.id)
    assert result["input_assigned"] == 3
    # All cases given to input1 since input2 is locked
    assert all(c.assigned_input_user_id == input1.id for c in cases)

    # Condition (c): Case previously revoked (with CaseInputAssignment row) is NOT auto-assigned again
    revoke_case_input(
        database,
        project_id=project.id,
        case_id=cases[0].id,
        reason_code="member_unavailable",
        note=None,
        new_user_id=None,
        actor_user_id=admin.id,
    )
    assert cases[0].assigned_input_user_id is None

    # Run auto-assign again
    result2 = assign_unassigned_project_cases(database, project_id=project.id, changed_by_user_id=admin.id)
    # cases[0] was NOT auto-assigned because it has assignment history!
    assert result2["input_assigned"] == 0
    assert cases[0].assigned_input_user_id is None

    # Condition (b): workflow-enabled projects are skipped entirely
    database.add(ProjectStage(project_id=project.id, stage_key="data_entry", position=1, is_enabled=True))
    database.commit()
    result3 = assign_unassigned_project_cases(database, project_id=project.id, changed_by_user_id=admin.id)
    assert result3 == {"input_assigned": 0, "reviewer_assigned": 0}

    # Condition 2 (d): Removing an input member in a workflow-enabled project sets their cases to unassigned
    # and does NOT auto-transfer to others
    update_project_members(
        database,
        project_id=project.id,
        input_user_ids=[],  # remove input1
        reviewer_user_ids=[reviewer.id],
        changed_by_user_id=admin.id,
    )
    database.refresh(cases[1])
    database.refresh(cases[2])
    assert cases[1].assigned_input_user_id is None
    assert cases[2].assigned_input_user_id is None


def test_action_needed_cases_and_constant_queries(database):
    admin, input1, input2, reviewer, project, cases, template = seed_test_project(database, name="P4", case_count=3)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Case 0: Overdue with draft report -> action needed
    cases[0].assigned_input_user_id = input1.id
    database.add(
        CaseInputAssignment(
            project_id=project.id,
            case_id=cases[0].id,
            user_id=input1.id,
            assigned_by_user_id=admin.id,
            assigned_at=now - timedelta(days=5),
            due_at=now - timedelta(days=3),
            deadline_days=2,
        )
    )
    # Add a draft submission for case 0
    asset0 = database.scalars(
        select(ProjectDocumentAsset).where(ProjectDocumentAsset.case_id == cases[0].id)
    ).first()
    sub0 = Submission(
        template_id=template.id,
        assigned_document_id=asset0.assigned_document_id,
        data_json="{}",
        status="draft",
        created_by_user_id=input1.id,
    )
    database.add(sub0)

    # Case 1: Overdue but completed -> NOT action needed
    cases[1].assigned_input_user_id = input1.id
    database.add(
        CaseInputAssignment(
            project_id=project.id,
            case_id=cases[1].id,
            user_id=input1.id,
            assigned_by_user_id=admin.id,
            assigned_at=now - timedelta(days=5),
            due_at=now - timedelta(days=3),
            deadline_days=2,
        )
    )
    asset1 = database.scalars(
        select(ProjectDocumentAsset).where(ProjectDocumentAsset.case_id == cases[1].id)
    ).first()
    sub1 = Submission(
        template_id=template.id,
        assigned_document_id=asset1.assigned_document_id,
        data_json="{}",
        status="completed",
        created_by_user_id=input1.id,
        submitted_by_user_id=input1.id,
    )
    database.add(sub1)

    # Case 2: Not overdue, but assignee is locked CTV -> action needed
    input2.account_type = "ctv"
    input2.is_locked = True
    cases[2].assigned_input_user_id = input2.id
    database.add(
        CaseInputAssignment(
            project_id=project.id,
            case_id=cases[2].id,
            user_id=input2.id,
            assigned_by_user_id=admin.id,
            assigned_at=now,
            due_at=now + timedelta(days=2),
            deadline_days=2,
        )
    )
    database.commit()

    # Query action-needed cases
    action_cases = list_action_needed_cases(database, project_id=project.id)
    case_ids = [c["case_id"] for c in action_cases]
    assert cases[0].id in case_ids
    assert cases[1].id not in case_ids
    assert cases[2].id in case_ids


def test_revoke_and_reassign_flow_and_document_sync(database):
    admin, input1, input2, reviewer, project, cases, _ = seed_test_project(database, name="P5", case_count=1)
    case = cases[0]

    # Assign to input1
    assign_case_input(
        database,
        project_id=project.id,
        case_id=case.id,
        user_id=input1.id,
        actor_user_id=admin.id,
    )

    doc = database.scalars(
        select(AssignedDocument).where(AssignedDocument.uuid_filename == f"doc-{project.id}-{case.id}.pdf")
    ).one()
    # Check document sync (Condition 1)
    assert doc.assigned_to_user_id == input1.id

    # Reassign to input2
    revoke_case_input(
        database,
        project_id=project.id,
        case_id=case.id,
        reason_code="other",
        note="Chuyển việc cho CTV mới",
        new_user_id=input2.id,
        actor_user_id=admin.id,
    )
    database.refresh(case)
    database.refresh(doc)
    assert case.assigned_input_user_id == input2.id
    assert doc.assigned_to_user_id == input2.id

    # Revoke to empty
    revoke_case_input(
        database,
        project_id=project.id,
        case_id=case.id,
        reason_code="member_unavailable",
        note=None,
        new_user_id=None,
        actor_user_id=admin.id,
    )
    database.refresh(case)
    database.refresh(doc)
    assert case.assigned_input_user_id is None
    assert doc.assigned_to_user_id is None

    # Appears in ready-input cases
    ready = list_ready_input_cases(database, project_id=project.id)
    ready_ids = [c["case_id"] for c in ready["cases"]]
    assert case.id in ready_ids


def test_ready_input_cases_workflow_prerequisites(database):
    admin, input1, input2, reviewer, project, cases, _ = seed_test_project(database, name="P6", case_count=1)
    case = cases[0]

    # Enable scan_qc and data_entry
    database.add_all([
        ProjectStage(project_id=project.id, stage_key="scan_qc", position=1, is_enabled=True),
        ProjectStage(project_id=project.id, stage_key="data_entry", position=2, is_enabled=True),
    ])
    # scan_qc is pending -> case NOT ready
    database.add(
        CaseStageState(
            project_id=project.id,
            case_id=case.id,
            stage_key="scan_qc",
            status="pending",
        )
    )
    database.commit()

    ready = list_ready_input_cases(database, project_id=project.id)
    assert len(ready["cases"]) == 0

    # Complete scan_qc -> case IS ready
    state = database.scalars(
        select(CaseStageState).where(
            CaseStageState.case_id == case.id,
            CaseStageState.stage_key == "scan_qc",
        )
    ).one()
    state.status = "done"
    database.commit()

    ready = list_ready_input_cases(database, project_id=project.id)
    assert len(ready["cases"]) == 1
    assert ready["cases"][0]["case_id"] == case.id


def test_submitted_by_user_id_and_null_safe_review_queue(database):
    admin, input1, input2, reviewer, project, cases, template = seed_test_project(database, name="P7", case_count=1)
    case = cases[0]

    # Create submission in draft by input1
    asset = database.scalars(
        select(ProjectDocumentAsset).where(ProjectDocumentAsset.case_id == case.id)
    ).first()
    sub = Submission(
        template_id=template.id,
        assigned_document_id=asset.assigned_document_id,
        data_json="{}",
        status="draft",
        created_by_user_id=input1.id,
        submitted_by_user_id=None,
        folder_path="box-001",
        folder_path_key=folder_path_key("box-001"),
    )
    database.add(sub)
    database.commit()
    assert sub.submitted_by_user_id is None

    # Condition 4: A submission with submitted_by_user_id IS NULL still shows in reviewer queue!
    sub.status = "pending_review"
    database.add(SubmissionReviewAssignment(submission_id=sub.id, reviewer_user_id=reviewer.id))
    database.commit()

    repo = ReviewRepository(database)
    # reviewer should see sub in submitted counts even when submitted_by_user_id is NULL
    counts = repo.reviewer_submitted_counts(reviewer_id=reviewer.id, template_id=None)
    assert len(counts) == 1
    assert counts[0][1] == 1

    # Submit via API transition draft -> pending_review records submitted_by_user_id
    sub.status = "draft"
    case.assigned_input_user_id = input2.id
    doc = database.scalars(
        select(AssignedDocument).where(AssignedDocument.id == asset.assigned_document_id)
    ).one()
    doc.assigned_to_user_id = input2.id
    database.commit()

    # User input2 submits it
    presence = SubmissionViewRepository(database).claim(sub.id, input2.id)
    database.commit()
    api_update_submission(
        sub_id=sub.id,
        req=SubmitRequest(
            data={},
            status="pending_review",
        ),
        lease_token=presence.lease_token,
        current_user={"id": input2.id, "role": "user", "username": input2.username},
        db=database,
    )
    database.refresh(sub)
    assert sub.status == "pending_review"
    assert sub.submitted_by_user_id == input2.id

    # input2 cannot review it (R6: submitted_by_user_id == reviewer_id)
    assert not ReviewWorkflowService.can_review_submission(sub, {"id": input2.id, "role": "user"}, database)

    # input1 cannot review it (R6: created_by_user_id == reviewer_id)
    assert not ReviewWorkflowService.can_review_submission(sub, {"id": input1.id, "role": "user"}, database)

    # reviewer CAN review it
    assert ReviewWorkflowService.can_review_submission(sub, {"id": reviewer.id, "role": "user"}, database)

    # Re-saving while pending_review does not overwrite submitted_by_user_id
    SubmissionViewRepository(database).release(sub.id, input2.id)
    admin_presence = SubmissionViewRepository(database).claim(sub.id, admin.id)
    database.commit()
    api_update_submission(
        sub_id=sub.id,
        req=SubmitRequest(
            data={"note": "updated"},
            status="pending_review",
        ),
        lease_token=admin_presence.lease_token,
        current_user={"id": admin.id, "role": "admin", "username": admin.username},
        db=database,
    )
    database.refresh(sub)
    assert sub.submitted_by_user_id == input2.id


def test_assign_case_input_validations_br04_and_account_policy(database):
    admin, input1, input2, reviewer, project, cases, _ = seed_test_project(database, name="P8", case_count=1)
    case = cases[0]
    database.add(ProjectMember(project_id=project.id, user_id=reviewer.id, member_role="input"))
    case.assigned_reviewer_user_id = reviewer.id
    database.commit()

    # Assigning to reviewer violates BR-04
    with pytest.raises(HTTPException) as exc_info:
        assign_case_input(
            database,
            project_id=project.id,
            case_id=case.id,
            user_id=reviewer.id,
            actor_user_id=admin.id,
        )
    assert exc_info.value.status_code == 409
    assert "BR-04" in exc_info.value.detail

    # Assigning to locked user
    input1.is_locked = True
    database.commit()
    with pytest.raises(HTTPException) as exc_info:
        assign_case_input(
            database,
            project_id=project.id,
            case_id=case.id,
            user_id=input1.id,
            actor_user_id=admin.id,
        )
    assert exc_info.value.status_code == 409
    assert "khóa" in exc_info.value.detail

    # Assigning to expired CTV
    input2.account_type = "ctv"
    input2.expires_on = date.today() - timedelta(days=1)
    database.commit()
    with pytest.raises(HTTPException) as exc_info:
        assign_case_input(
            database,
            project_id=project.id,
            case_id=case.id,
            user_id=input2.id,
            actor_user_id=admin.id,
        )
    assert exc_info.value.status_code == 409
    assert "hết hạn" in exc_info.value.detail
