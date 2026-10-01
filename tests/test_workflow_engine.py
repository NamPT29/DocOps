import pytest

from server.services import workflow_engine as engine

ALL = list(engine.STAGE_KEYS)


def test_availability_follows_enabled_order_and_skips_disabled_stages():
    enabled = ["scan", "scan_qc", "data_entry"]
    assert engine.is_available("scan", {}, enabled)
    assert not engine.is_available("scan_qc", {}, enabled)
    assert engine.is_available("scan_qc", {"scan": engine.DONE}, enabled)
    assert not engine.is_available("handover", {}, enabled)  # disabled stage
    assert engine.previous_enabled("data_entry", enabled) == "scan_qc"
    assert engine.next_enabled("scan", enabled) == "scan_qc"


def test_start_requires_previous_stage_done():
    with pytest.raises(engine.WorkflowError) as blocked:
        engine.apply_action("scan", engine.START, {}, ALL)
    assert blocked.value.code == "stage_blocked"
    assert engine.apply_action(
        "scan", engine.START, {"arrangement": engine.DONE}, ALL
    ) == {"scan": engine.IN_PROGRESS}


def test_complete_only_from_in_progress():
    with pytest.raises(engine.WorkflowError):
        engine.apply_action("arrangement", engine.COMPLETE, {}, ALL)
    assert engine.apply_action(
        "arrangement", engine.COMPLETE, {"arrangement": engine.IN_PROGRESS}, ALL
    ) == {"arrangement": engine.DONE}


def test_qc_reject_sends_reviewed_stage_back_and_needs_reason():
    statuses = {"arrangement": engine.DONE, "scan": engine.DONE, "scan_qc": engine.IN_PROGRESS}
    with pytest.raises(engine.WorkflowError) as missing:
        engine.apply_action("scan_qc", engine.REJECT, statuses, ALL)
    assert missing.value.code == "reason_required"
    assert engine.apply_action(
        "scan_qc", engine.REJECT, statuses, ALL, reason="thiếu trang"
    ) == {"scan_qc": engine.PENDING, "scan": engine.REJECTED}


def test_work_stage_cannot_reject_and_rejected_stage_can_restart():
    with pytest.raises(engine.WorkflowError):
        engine.apply_action(
            "scan", engine.REJECT,
            {"arrangement": engine.DONE, "scan": engine.IN_PROGRESS}, ALL, reason="x",
        )
    assert engine.apply_action(
        "scan", engine.START,
        {"arrangement": engine.DONE, "scan": engine.REJECTED}, ALL,
    ) == {"scan": engine.IN_PROGRESS}


def test_reject_and_reopen_blocked_when_downstream_started():
    statuses = {
        "arrangement": engine.DONE, "scan": engine.DONE, "scan_qc": engine.IN_PROGRESS,
        "data_entry": engine.IN_PROGRESS,
    }
    with pytest.raises(engine.WorkflowError) as error:
        engine.apply_action("scan_qc", engine.REJECT, statuses, ALL, reason="x")
    assert error.value.code == "downstream_started"
    with pytest.raises(engine.WorkflowError) as reopen:
        engine.apply_action(
            "arrangement", engine.REOPEN, statuses, ALL, reason="x"
        )
    assert reopen.value.code == "downstream_started"


def test_derived_and_disabled_stages_reject_manual_transitions():
    with pytest.raises(engine.WorkflowError) as derived:
        engine.apply_action("data_entry", engine.START, {"scan_qc": engine.DONE}, ALL)
    assert derived.value.code == "stage_derived"
    with pytest.raises(engine.WorkflowError) as disabled:
        engine.apply_action("scan", engine.START, {}, ["handover"])
    assert disabled.value.code == "stage_disabled"
    with pytest.raises(engine.WorkflowError) as unknown:
        engine.apply_action("nope", engine.START, {}, ALL)
    assert unknown.value.code == "unknown_stage"


def test_derive_entry_statuses():
    derive = engine.derive_entry_statuses
    assert derive(0, 0, 0, 0, 0) == {"data_entry": "pending", "entry_qc": "pending"}
    assert derive(3, 1, 1, 0, 0) == {"data_entry": "in_progress", "entry_qc": "pending"}
    assert derive(2, 2, 2, 0, 0) == {"data_entry": "done", "entry_qc": "pending"}
    assert derive(2, 2, 2, 1, 0) == {"data_entry": "done", "entry_qc": "in_progress"}
    assert derive(2, 2, 2, 0, 2) == {"data_entry": "done", "entry_qc": "done"}
    # entry_qc cannot progress while entry is still incomplete
    assert derive(3, 2, 2, 0, 2)["entry_qc"] == "pending"
