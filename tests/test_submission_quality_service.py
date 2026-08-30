import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base
from server.models import (
    AssignedDocument,
    Project,
    ProjectCase,
    ProjectDocumentAsset,
    ProjectReportUnit,
    Submission,
    SubmissionQualityAssessment,
    SubmissionReviewAssignment,
    SubmissionReviewFieldHistory,
    SubmissionReviewHistory,
    Template,
    User,
)
from server.routers import submissions
from server.services.personnel_statistics_service import get_personnel_statistics
from server.services.submission_quality_service import SubmissionQualityService


@pytest.fixture()
def quality_case():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    input_user = User(username="quality-input", password="hash", role="user")
    reviewer = User(username="quality-reviewer", password="hash", role="user")
    template = Template(
        name="Quality form",
        filename="quality.xlsx",
        config_json=json.dumps({"hidden_cols": [21]}),
    )
    db.add_all([input_user, reviewer, template])
    db.flush()

    schema = [{
        "category": "Thông tin",
        "fields": [
            {
                "col_index": index,
                "name": f"col_{index}",
                "label": f"Trường {index + 1}",
                "type": "text",
            }
            for index in range(21)
        ],
    }]
    project = Project(
        name="Quality project",
        root_folder_name="quality-project",
        template_id=template.id,
        template_name_snapshot=template.name,
        template_filename_snapshot=template.filename,
        template_config_json_snapshot=json.dumps({}),
        form_schema_json_snapshot=json.dumps(schema),
        case_level=1,
        report_mode="folder_level",
        report_level=2,
        status="ready",
        created_by_user_id=input_user.id,
    )
    db.add(project)
    db.flush()
    case_row = ProjectCase(
        project_id=project.id,
        case_key="001",
        display_name="001",
        assigned_input_user_id=input_user.id,
        assigned_reviewer_user_id=reviewer.id,
    )
    db.add(case_row)
    db.flush()
    report = ProjectReportUnit(
        project_id=project.id,
        case_id=case_row.id,
        report_key="001/report",
        display_name="report",
    )
    document = AssignedDocument(
        original_filename="quality.pdf",
        uuid_filename="quality.pdf",
        assigned_to_user_id=input_user.id,
        template_id=template.id,
        status="completed",
    )
    db.add_all([report, document])
    db.flush()
    db.add(ProjectDocumentAsset(
        project_id=project.id,
        case_id=case_row.id,
        report_unit_id=report.id,
        assigned_document_id=document.id,
        relative_path="001/report/quality.pdf",
        normalized_relative_path="001/report/quality.pdf",
        original_filename="quality.pdf",
        storage_filename="quality-storage.pdf",
        content_sha256="a" * 64,
        byte_size=10,
    ))
    baseline = {f"col_{index}": f"value-{index}" for index in range(21)}
    submission = Submission(
        data_json=json.dumps(baseline),
        template_id=template.id,
        created_by_user_id=input_user.id,
        assigned_document_id=document.id,
        status="pending_review",
    )
    db.add(submission)
    db.flush()
    db.add(SubmissionReviewAssignment(
        submission_id=submission.id,
        reviewer_user_id=reviewer.id,
    ))
    db.commit()
    try:
        yield db, submission, baseline, input_user, reviewer
    finally:
        db.close()
        engine.dispose()


def test_quality_uses_visible_fields_at_or_above_five_percent_and_final_values(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    assessment = SubmissionQualityService.ensure_baseline(submission, baseline, db)

    one_change = {**baseline, "col_0": "corrected"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        one_change,
        reviewer.id,
        db,
    )
    assert assessment.visible_field_count == 20
    assert assessment.changed_field_count == 1
    assert assessment.is_error_report is True  # 1/20 is exactly 5%.

    SubmissionQualityService.assess_confirmed_review(
        submission,
        baseline,
        reviewer.id,
        db,
    )
    assert assessment.changed_field_count == 0
    assert assessment.is_error_report is False  # Latest valid result is below 5%.

    two_changes = {**baseline, "col_0": "corrected", "col_1": "corrected"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        two_changes,
        reviewer.id,
        db,
    )
    assert assessment.changed_field_count == 2
    assert assessment.is_error_report is True
    assert assessment.input_user_id == input_user.id


def test_custom_error_threshold_is_shared_by_review_and_input_confirmation(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    template = db.get(Template, submission.template_id)
    template.config_json = json.dumps({
        "hidden_cols": [21],
        "error_report_threshold_percent": 10,
    })
    db.commit()

    reviewed = {
        **baseline,
        "col_0": "reviewed-0",
        "col_1": "reviewed-1",
    }
    assessment = SubmissionQualityService.assess_confirmed_review(
        submission,
        reviewed,
        reviewer.id,
        db,
    )
    assert assessment.visible_field_count == 20
    assert assessment.changed_field_count == 2
    assert assessment.is_error_report is True

    submission.data_json = json.dumps(reviewed)
    submission.status = "pending_input_confirmation"
    SubmissionQualityService.apply_input_correction(
        submission,
        {"col_0": baseline["col_0"]},
        input_user.id,
        db,
    )
    assert assessment.changed_field_count == 1
    assert assessment.is_error_report is False


def test_manual_wrong_field_payload_is_not_part_of_review_contract():
    request = submissions.ReviewContentRequest(
        data={},
        wrong_fields=["col_0"],
    )

    assert request.__dict__ == {"data": {}}


def test_quality_keeps_original_submitter_after_current_owner_changes(quality_case):
    db, submission, baseline, input_user, _reviewer = quality_case
    new_owner = User(username="quality-new-owner", password="hash", role="user")
    db.add(new_owner)
    db.flush()
    assessment = SubmissionQualityService.ensure_baseline(submission, baseline, db)

    submission.created_by_user_id = new_owner.id
    db.commit()
    db.refresh(assessment)

    assert submission.created_by_user_id == new_owner.id
    assert assessment.input_user_id == input_user.id


def test_input_user_detail_history_and_unread_badge_are_seen_on_open(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    reviewed = {**baseline, "col_0": "reviewer value", "col_1": "other change"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        reviewed,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps(reviewed)
    submission.status = "pending_input_confirmation"
    submission.is_checked = True
    db.commit()

    before_open = submissions.api_get_submissions(
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )
    assert before_open["unread_review_count"] == 1
    assert before_open["data"][0]["quality"]["is_unread"] is True

    detail = submissions.api_get_submission(
        submission.id,
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )
    assert detail["quality"]["reviewed_changes"] == ["col_0", "col_1"]
    assert detail["quality"]["corrected_fields"] == []
    assert detail["quality"]["is_unread"] is True

    after_open = submissions.api_get_submissions(
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )
    assert after_open["unread_review_count"] == 0
    assert after_open["data"][0]["quality"]["is_unread"] is False

    SubmissionQualityService.apply_input_correction(
        submission,
        {"col_0": baseline["col_0"]},
        input_user.id,
        db,
    )
    db.commit()

    completed_detail = submissions.api_get_submission(
        submission.id,
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )
    assert completed_detail["quality"]["corrected_fields"] == ["col_0"]
    after_confirmation = submissions.api_get_submissions(
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )
    assert after_confirmation["unread_review_count"] == 0


def test_input_user_is_notified_even_when_reviewer_makes_no_changes(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    SubmissionQualityService.assess_confirmed_review(
        submission,
        baseline,
        reviewer.id,
        db,
    )
    submission.status = "pending_input_confirmation"
    submission.is_checked = True
    db.commit()

    listing = submissions.api_get_submissions(
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )

    assert listing["unread_review_count"] == 1
    assert listing["data"][0]["quality"]["is_unread"] is True


def test_non_input_open_does_not_expose_or_clear_input_quality(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    reviewed = {**baseline, "col_0": "reviewer value"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        reviewed,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps(reviewed)
    submission.status = "pending_input_confirmation"
    submission.is_checked = True
    db.commit()

    reviewer_detail = submissions.api_get_submission(
        submission.id,
        current_user={"id": reviewer.id, "role": "user"},
        db=db,
    )
    assert reviewer_detail["quality"] is None

    input_list = submissions.api_get_submissions(
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )
    assert input_list["unread_review_count"] == 1

    stranger = User(username="quality-stranger", password="hash", role="user")
    db.add(stranger)
    db.commit()
    with pytest.raises(Exception) as error:
        submissions.api_get_submission(
            submission.id,
            current_user={"id": stranger.id, "role": "user"},
            db=db,
        )
    assert error.value.status_code == 403


def test_transferred_assignee_corrects_only_reviewer_changes_without_owning_error(
    quality_case,
):
    db, submission, baseline, original_input, reviewer = quality_case
    reviewed = {**baseline, "col_0": "reviewer value"}
    SubmissionQualityService.ensure_baseline(submission, baseline, db)
    SubmissionQualityService.assess_confirmed_review(
        submission,
        reviewed,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps({**reviewed, "_pdf_uuid": "quality.pdf"})
    submission.status = "pending_input_confirmation"
    submission.is_checked = True
    new_input = User(username="quality-new-input", password="hash", role="user")
    db.add(new_input)
    db.flush()
    case_row = db.query(ProjectCase).one()
    case_row.assigned_input_user_id = new_input.id
    db.commit()

    assert submission.created_by_user_id == original_input.id
    new_input_listing = submissions.api_get_submissions(
        current_user={"id": new_input.id, "role": "user"},
        db=db,
    )
    original_input_listing = submissions.api_get_submissions(
        current_user={"id": original_input.id, "role": "user"},
        db=db,
    )
    assert new_input_listing["pagination"]["total"] == 1
    assert new_input_listing["unread_review_count"] == 1
    assert new_input_listing["data"][0]["quality"]["is_unread"] is True
    assert original_input_listing["pagination"]["total"] == 0
    assert original_input_listing["unread_review_count"] == 0
    assert submissions.api_get_submission(
        submission.id,
        current_user={"id": new_input.id, "role": "user"},
        db=db,
    )["quality"]["reviewed_changes"] == ["col_0"]

    with pytest.raises(Exception) as invalid_field:
        SubmissionQualityService.apply_input_correction(
            submission,
            {"col_1": "not reviewer changed"},
            new_input.id,
            db,
        )
    assert invalid_field.value.status_code == 400
    assert invalid_field.value.detail["code"] == "invalid_correction_fields"

    correction, _stored = SubmissionQualityService.apply_input_correction(
        submission,
        {"col_0": "third still-wrong value"},
        new_input.id,
        db,
    )
    db.commit()

    assert correction.input_user_id == original_input.id
    assert correction.confirmed_by_user_id == new_input.id
    assert correction.reviewer_error_count == 1
    assert submission.status == "completed"
    assert submission.is_checked is True
    field_history = db.query(SubmissionReviewFieldHistory).filter_by(
        event_id=correction.id,
        field_name="col_0",
    ).one()
    assert field_history.reviewer_error is True
    assert db.query(SubmissionReviewHistory).filter_by(
        event_type="input_confirmed",
    ).count() == 1

    statistics = {row["user_id"]: row for row in get_personnel_statistics(db)}
    assert statistics[original_input.id]["submitted_report_count"] == 1
    assert statistics[original_input.id]["input_error_report_count"] == 1
    assert statistics[new_input.id]["submitted_report_count"] == 0
    assert statistics[new_input.id]["input_error_report_count"] == 0
    assert statistics[reviewer.id]["reviewer_error_field_count"] == 1

    submission.status = "pending_review"
    with pytest.raises(Exception) as no_second_correction:
        SubmissionQualityService.apply_input_correction(
            submission,
            {"col_0": baseline["col_0"]},
            new_input.id,
            db,
        )
    assert no_second_correction.value.status_code == 409


def test_input_user_can_confirm_completed_without_changing_reviewer_data(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    reviewed = {**baseline, "col_0": "reviewer value"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        reviewed,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps(reviewed)
    submission.status = "pending_input_confirmation"

    confirmation, stored = SubmissionQualityService.apply_input_correction(
        submission,
        {},
        input_user.id,
        db,
    )

    assert confirmation.event_type == "input_confirmed"
    assert confirmation.input_user_id == input_user.id
    assert confirmation.confirmed_by_user_id == input_user.id
    assert confirmation.changed_field_count == 0
    assert stored["col_0"] == "reviewer value"
    assert submission.status == "completed"


def test_input_confirmation_endpoint_completes_review_cycle(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    reviewed = {**baseline, "col_0": "reviewer value"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        reviewed,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps(reviewed)
    submission.status = "pending_input_confirmation"
    db.commit()
    with pytest.raises(Exception) as missing_lease:
        submissions.api_confirm_input_correction(
            submission.id,
            submissions.ReviewContentRequest(data={"col_0": baseline["col_0"]}),
            lease_token=None,
            current_user={"id": input_user.id, "role": "user"},
            db=db,
        )
    assert missing_lease.value.status_code == 409
    assert missing_lease.value.detail["code"] == "submission_lease_required"
    lease_token = submissions.api_claim_submission_view(
        submission.id,
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )["lease_token"]

    result = submissions.api_confirm_input_correction(
        submission.id,
        submissions.ReviewContentRequest(data={"col_0": baseline["col_0"]}),
        lease_token=lease_token,
        current_user={"id": input_user.id, "role": "user"},
        db=db,
    )

    db.refresh(submission)
    assert result == {
        "status": "ok",
        "submission_status": "completed",
        "is_checked": True,
    }
    assert submission.status == "completed"
    assert json.loads(submission.data_json)["col_0"] == baseline["col_0"]


def test_reopened_submission_can_be_confirmed_once_in_each_review_cycle(quality_case):
    db, submission, baseline, input_user, reviewer = quality_case
    first_review = {**baseline, "col_0": "first review"}
    SubmissionQualityService.assess_confirmed_review(
        submission,
        first_review,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps(first_review)
    submission.status = "pending_input_confirmation"
    SubmissionQualityService.apply_input_correction(
        submission,
        {},
        input_user.id,
        db,
    )

    second_review = {**first_review, "col_1": "second review"}
    submission.status = "pending_review"
    SubmissionQualityService.assess_confirmed_review(
        submission,
        second_review,
        reviewer.id,
        db,
    )
    submission.data_json = json.dumps(second_review)
    submission.status = "pending_input_confirmation"
    SubmissionQualityService.apply_input_correction(
        submission,
        {},
        input_user.id,
        db,
    )
    db.commit()

    confirmations = db.query(SubmissionReviewHistory).filter_by(
        event_type="input_confirmed",
    ).all()
    assert len(confirmations) == 2
    assert confirmations[0].review_event_id != confirmations[1].review_event_id
    assert {row.confirmed_by_user_id for row in confirmations} == {input_user.id}
    assert submission.status == "completed"
