"""Pure state machine for the digitization pipeline; it never touches the database.

Pipeline: chỉnh lý -> scan -> check scan -> nhập liệu -> check nhập liệu ->
chuẩn hóa -> bàn giao. A case advances through the *enabled* stages in order.
"""

from dataclasses import dataclass

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
REJECTED = "rejected"
STATUSES = (PENDING, IN_PROGRESS, DONE, REJECTED)

START = "start"
COMPLETE = "complete"
REJECT = "reject"
REOPEN = "reopen"
ACTIONS = (START, COMPLETE, REJECT, REOPEN)


class WorkflowError(Exception):
    """A transition is not allowed; ``code`` is stable for API clients."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StageDef:
    key: str
    label: str
    kind: str  # "work" | "qc" | "delivery"
    reviews: str | None = None  # QC stage -> the work stage it verifies
    derived: bool = False  # status comes from existing submissions, not stored
    member_role: str | None = None  # legacy project_members role, if any
    # Roles allowed to work this stage (BA 3.3): "admin", "staff" (hành chính), "ctv".
    allowed_roles: tuple = ("admin", "staff")


STAGE_CATALOG = (
    StageDef("arrangement", "Chỉnh lý", "work"),
    StageDef("scan", "Scan", "work"),
    StageDef("scan_qc", "Check scan", "qc", reviews="scan"),
    StageDef("data_entry", "Nhập liệu", "work", derived=True, member_role="input",
             allowed_roles=("admin", "staff", "ctv")),
    StageDef("entry_qc", "Check nhập liệu", "qc", reviews="data_entry", derived=True,
             member_role="reviewer"),
    StageDef("normalization", "Chuẩn hóa", "work", allowed_roles=("admin",)),
    StageDef("handover", "Bàn giao", "delivery", allowed_roles=("admin",)),
)
STAGES_BY_KEY = {stage.key: stage for stage in STAGE_CATALOG}
STAGE_KEYS = tuple(stage.key for stage in STAGE_CATALOG)


def get_stage(stage_key):
    stage = STAGES_BY_KEY.get(stage_key)
    if stage is None:
        raise WorkflowError("unknown_stage", f"Bước quy trình không hợp lệ: {stage_key}")
    return stage


def ordered_enabled(enabled_keys):
    wanted = set(enabled_keys)
    return [key for key in STAGE_KEYS if key in wanted]


def previous_enabled(stage_key, enabled_keys):
    previous = None
    for key in ordered_enabled(enabled_keys):
        if key == stage_key:
            return previous
        previous = key
    return None


def next_enabled(stage_key, enabled_keys):
    keys = ordered_enabled(enabled_keys)
    if stage_key in keys:
        index = keys.index(stage_key)
        if index + 1 < len(keys):
            return keys[index + 1]
    return None


def is_available(stage_key, statuses, enabled_keys):
    """A stage can be worked once the previous enabled stage is done."""
    if stage_key not in enabled_keys:
        return False
    previous = previous_enabled(stage_key, enabled_keys)
    return previous is None or statuses.get(previous, PENDING) == DONE


def later_started(stage_key, statuses, enabled_keys, *, ignore=()):
    """Enabled stages after ``stage_key`` that already moved past pending."""
    keys = ordered_enabled(enabled_keys)
    if stage_key not in keys:
        return []
    return [
        key
        for key in keys[keys.index(stage_key) + 1:]
        if key not in ignore and statuses.get(key, PENDING) != PENDING
    ]


def apply_action(stage_key, action, statuses, enabled_keys, *, reason=None):
    """Return ``{stage_key: new_status}`` changes for one action.

    ``statuses`` maps every enabled stage to its current status (derived stages
    included). Raises ``WorkflowError`` when the action is not allowed.
    """
    stage = get_stage(stage_key)
    if action not in ACTIONS:
        raise WorkflowError("unknown_action", f"Thao tác không hợp lệ: {action}")
    if stage_key not in enabled_keys:
        raise WorkflowError("stage_disabled", f"Bước '{stage.label}' chưa được bật cho dự án")
    if stage.derived:
        raise WorkflowError(
            "stage_derived",
            f"Bước '{stage.label}' được tính từ dữ liệu nhập liệu, không chuyển thủ công",
        )
    current = statuses.get(stage_key, PENDING)

    if action == START:
        if current not in (PENDING, REJECTED):
            raise WorkflowError("invalid_transition", "Chỉ bắt đầu được bước đang chờ hoặc bị trả lại")
        if not is_available(stage_key, statuses, enabled_keys):
            raise WorkflowError("stage_blocked", "Bước trước chưa hoàn tất")
        return {stage_key: IN_PROGRESS}

    if action == COMPLETE:
        if current != IN_PROGRESS:
            raise WorkflowError("invalid_transition", "Chỉ hoàn tất được bước đang thực hiện")
        return {stage_key: DONE}

    if action == REJECT:
        if stage.kind != "qc" or stage.reviews is None:
            raise WorkflowError("invalid_transition", "Chỉ bước kiểm tra mới được trả lại")
        if current != IN_PROGRESS:
            raise WorkflowError("invalid_transition", "Chỉ trả lại được khi đang kiểm tra")
        if not str(reason or "").strip():
            raise WorkflowError("reason_required", "Cần nêu lý do khi trả lại")
        reviewed = stage.reviews
        if reviewed not in enabled_keys:
            raise WorkflowError("stage_disabled", "Bước được kiểm tra chưa được bật")
        blocked = later_started(stage_key, statuses, enabled_keys)
        if blocked:
            raise WorkflowError(
                "downstream_started",
                "Các bước sau đã bắt đầu: " + ", ".join(blocked),
            )
        return {stage_key: PENDING, reviewed: REJECTED}

    # REOPEN (administrators only; the caller enforces that)
    if current != DONE:
        raise WorkflowError("invalid_transition", "Chỉ mở lại được bước đã hoàn tất")
    if not str(reason or "").strip():
        raise WorkflowError("reason_required", "Cần nêu lý do khi mở lại")
    blocked = later_started(stage_key, statuses, enabled_keys)
    if blocked:
        raise WorkflowError(
            "downstream_started",
            "Các bước sau đã bắt đầu: " + ", ".join(blocked),
        )
    return {stage_key: IN_PROGRESS}


def derive_entry_statuses(report_total, reports_entered, submissions_total,
                          submissions_under_review, submissions_completed):
    """Statuses of data_entry / entry_qc from submission counts of one case."""
    if report_total <= 0 or reports_entered <= 0:
        entry = PENDING
    elif reports_entered >= report_total:
        entry = DONE
    else:
        entry = IN_PROGRESS

    if entry != DONE or submissions_total <= 0:
        qc = PENDING
    elif submissions_completed >= submissions_total:
        qc = DONE
    elif submissions_under_review + submissions_completed > 0:
        qc = IN_PROGRESS
    else:
        qc = PENDING
    return {"data_entry": entry, "entry_qc": qc}
