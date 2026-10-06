from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Boolean, Text, UniqueConstraint, Index, CheckConstraint, text
from sqlalchemy import Numeric
from sqlalchemy import false as sql_false
from sqlalchemy.orm import Mapped, mapped_column
from server.database import Base, get_utc_now

# Columns/constraints added after the frozen baseline carry this marker so the
# schema 0001 snapshot generator skips them.
USER_ACCOUNT_REVISION = {"revision": "0006_user_account_type"}
USER_LOCK_REVISION = {"revision": "0007_user_lock"}
CASE_INPUT_ASSIGNMENT_REVISION = {"revision": "0010_case_input_assignment"}


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('staff', 'ctv')",
            name="ck_users_account_type",
            info=USER_ACCOUNT_REVISION,
        ),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False) # Scrypt hash; legacy values migrate on login
    full_name = Column(String(255), nullable=False, default="")
    phone_number = Column(String(50), nullable=True)
    role = Column(String(255), default="user") # 'admin' or 'user'
    max_concurrent_sessions = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=get_utc_now)
    # FR-AUT-02/03: non-admin accounts are 'staff' (Hành chính) or 'ctv'.
    # Admins keep role='admin'; their account_type is not used.
    account_type = Column(
        String(16),
        nullable=False,
        default="staff",
        server_default="staff",
        info=USER_ACCOUNT_REVISION,
    )
    # Last day (Vietnam time) a CTV may sign in; NULL for other accounts.
    expires_on = Column(Date, nullable=True, info=USER_ACCOUNT_REVISION)
    # Locked by an admin: no sign-in, every session revoked (revision 0007).
    is_locked = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sql_false(),
        info=USER_LOCK_REVISION,
    )


class UserLockEvent(Base):
    """Append-only log of account locks and unlocks (who, when, why)."""

    __tablename__ = "user_lock_events"
    __table_args__ = (
        CheckConstraint("action IN ('lock', 'unlock')", name="ck_user_lock_events_action"),
        {"info": USER_LOCK_REVISION},
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(16), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)


class UserLoginSession(Base):
    __tablename__ = "user_login_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "browser_id", name="uq_user_login_sessions_browser"),
    )

    session_id = Column(String(64), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    browser_id = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    last_activity_at = Column(DateTime, nullable=False, default=get_utc_now)
    close_requested_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)


class UserCapability(Base):
    __tablename__ = "user_capabilities"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    can_input = Column(Boolean, nullable=False, default=True)
    can_review = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now)


class ApiRateLimitBucket(Base):
    """Shared fixed-window counters used by all API worker processes."""

    __tablename__ = "api_rate_limit_buckets"

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)


class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"

    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    read_at = Column(DateTime, nullable=True)

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=get_utc_now)
    is_active = Column(Boolean, default=True)
    config_json = Column(Text, nullable=True) # Lưu cấu hình JSON của biểu mẫu

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True) # Which template this task is for
    title = Column(String(255), nullable=False)
    target_quantity = Column(Integer, nullable=False)
    current_quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=get_utc_now)
    status = Column(String(255), default="in_progress") # in_progress, completed

class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index(
            "ix_submissions_status_template_created_at",
            "status",
            "template_id",
            "created_at",
        ),
        Index(
            "ix_submissions_status_template_folder_created_at",
            "status",
            "template_id",
            "folder_path_key",
            "created_at",
        ),
        Index(
            "ix_submissions_submitted_by_user_id",
            "submitted_by_user_id",
            info=CASE_INPUT_ASSIGNMENT_REVISION,
        ),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=get_utc_now)
    
    # Store the dynamically filled JSON
    data_json = Column(Text, nullable=False)
    
    # Track which template this belongs to
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True, index=True)
    
    # Track which user created this submission
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Author who submitted this report for review (FR-ENT-01, BR-04, revision 0010).
    submitted_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        info=CASE_INPUT_ASSIGNMENT_REVISION,
    )

    # Indexed metadata used for folder/document queries. `data_json` remains
    # untouched as the source of the dynamic form values and as a compatibility
    # fallback for records created before these columns existed.
    assigned_document_id = Column(
        Integer,
        ForeignKey("assigned_documents.id"),
        nullable=True,
        index=True,
    )
    folder_path = Column(String(1024), nullable=True)
    folder_path_key = Column(String(64), nullable=True, index=True)
    
    # Track admin check status
    is_checked = Column(Boolean, default=False)
    
    # Workflow status: draft, pending_review, pending_input_confirmation, completed
    status = Column(String(50), default="draft")


class SubmissionQualityAssessment(Base):
    """Immutable review baseline and the latest quality result for one report."""

    __tablename__ = "submission_quality_assessments"

    submission_id = Column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    input_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    baseline_data_json = Column(Text, nullable=False)
    visible_field_count = Column(Integer, nullable=False, default=0)
    changed_field_count = Column(Integer, nullable=False, default=0)
    is_error_report = Column(Boolean, nullable=False, default=False, index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assessed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)


class SubmissionReviewHistory(Base):
    """Append-only snapshots for confirmed reviews and input confirmations."""

    __tablename__ = "submission_review_histories"

    id = Column(Integer, primary_key=True)
    submission_id = Column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_event_id = Column(
        Integer,
        ForeignKey("submission_review_histories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(32), nullable=False, index=True)
    input_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    confirmed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    baseline_data_json = Column(Text, nullable=False)
    reviewer_data_json = Column(Text, nullable=False)
    final_data_json = Column(Text, nullable=True)
    visible_field_count = Column(Integer, nullable=False, default=0)
    changed_field_count = Column(Integer, nullable=False, default=0)
    reviewer_error_count = Column(Integer, nullable=False, default=0)
    # NULL for review events. Input confirmations use a deterministic value so
    # the database, not only the API process, enforces the one-time rule.
    correction_token = Column(String(64), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)


class SubmissionReviewFieldHistory(Base):
    """Immutable A/B/C values for one visible field in a history event."""

    __tablename__ = "submission_review_field_histories"

    id = Column(Integer, primary_key=True)
    event_id = Column(
        Integer,
        ForeignKey("submission_review_histories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_id = Column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name = Column(String(255), nullable=False, index=True)
    baseline_value_json = Column(Text, nullable=False)
    reviewer_value_json = Column(Text, nullable=False)
    final_value_json = Column(Text, nullable=True)
    reviewer_error = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)


class SubmissionReviewSeen(Base):
    """Latest immutable review event viewed by one input user."""

    __tablename__ = "submission_review_seen"

    submission_id = Column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    review_event_id = Column(
        Integer,
        ForeignKey("submission_review_histories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seen_at = Column(DateTime, nullable=False, default=get_utc_now)


class SubmissionReviewAssignment(Base):
    __tablename__ = "submission_review_assignments"

    submission_id = Column(
        Integer,
        ForeignKey("submissions.id"),
        primary_key=True,
    )
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=False, default=get_utc_now)

class SubmissionViewPresence(Base):
    __tablename__ = 'submission_view_presence'

    submission_id = Column(Integer, ForeignKey('submissions.id'), primary_key=True)
    viewer_user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    lease_token = Column(String(64), nullable=True)
    last_seen_at = Column(DateTime, nullable=False, default=get_utc_now)

class AssignedDocument(Base):
    __tablename__ = "assigned_documents"
    
    id = Column(Integer, primary_key=True)
    original_filename = Column(String(255), nullable=False)
    uuid_filename = Column(String(255), nullable=False, unique=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True) # null = unassigned
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True, index=True)
    status = Column(String(255), default="pending") # pending, assigned, completed
    created_at = Column(DateTime, default=get_utc_now)


class AssignedDocumentReviewAssignment(Base):
    __tablename__ = "assigned_document_review_assignments"

    document_id = Column(
        Integer,
        ForeignKey("assigned_documents.id"),
        primary_key=True,
    )
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_at = Column(DateTime, nullable=False, default=get_utc_now)

class AssignedDocumentPath(Base):
    """Logical folder metadata for independently assigned documents."""

    __tablename__ = "assigned_document_paths"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("assigned_documents.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    relative_path = Column(String(1024), nullable=False)
    upload_id = Column(String(100), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=get_utc_now)

class AssignedDocumentFolder(Base):
    __tablename__ = "assigned_document_folders"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("assigned_documents.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    folder_group = Column(String(1024), nullable=False)
    created_at = Column(DateTime, default=get_utc_now)

class ServerFolderImportJob(Base):
    __tablename__ = "server_folder_import_jobs"

    id = Column(Integer, primary_key=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    source_relative_path = Column(String(1024), nullable=False, default="")
    grouping_level = Column(Integer, nullable=False)
    user_ids_json = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="queued")
    total_files = Column(Integer, nullable=False, default=0)
    processed_files = Column(Integer, nullable=False, default=0)
    imported_files = Column(Integer, nullable=False, default=0)
    skipped_files = Column(Integer, nullable=False, default=0)
    failed_files = Column(Integer, nullable=False, default=0)
    current_path = Column("current_path", String(1024), nullable=True, quote=True)
    error_message = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=get_utc_now)
    completed_at = Column(DateTime, nullable=True)


class ServerFolderImportReviewer(Base):
    __tablename__ = "server_folder_import_reviewers"

    job_id = Column(
        Integer,
        ForeignKey("server_folder_import_jobs.id"),
        primary_key=True,
    )
    reviewer_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        primary_key=True,
    )

from sqlalchemy.orm import relationship
from sqlalchemy import BigInteger, CheckConstraint

class Dictionary(Base):
    __tablename__ = "dictionaries"

    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    name = Column(String(100), index=True, nullable=False) # e.g. "DM_DanToc"
    description = Column(String(255), nullable=True) # e.g. "Dân tộc"
    
    __table_args__ = (UniqueConstraint('template_id', 'name', name='uix_template_dict_name'),)
    
    items = relationship("DictionaryItem", back_populates="dictionary", cascade="all, delete-orphan")

class DictionaryItem(Base):
    __tablename__ = "dictionary_items"

    id = Column(Integer, primary_key=True)
    dictionary_id = Column(Integer, ForeignKey("dictionaries.id"), index=True)
    code = Column(String(50), nullable=True)  # e.g. "1" or "01"
    value = Column(String(255), nullable=False) # e.g. "Kinh"
    
    dictionary = relationship("Dictionary", back_populates="items")


class Project(Base):
    """A project pins one configured template and one folder hierarchy."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    root_folder_name = Column(String(255), nullable=False)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False, index=True)
    template_name_snapshot = Column(String(255), nullable=False)
    template_filename_snapshot = Column(String(255), nullable=False)
    template_config_json_snapshot = Column(Text, nullable=True)
    form_schema_json_snapshot = Column(Text, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    case_level = Column(Integer, nullable=False)
    report_mode = Column(String(32), nullable=False)
    report_level = Column(Integer, nullable=True)
    # Public lifecycle values. Migration 0004 normalizes legacy rows once;
    # keeping this as a string preserves compatibility with stored values.
    status = Column(String(32), nullable=False, default="new", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        CheckConstraint("case_level >= 1", name="ck_projects_case_level"),
        CheckConstraint(
            "report_mode IN ('folder_level', 'pdf')",
            name="ck_projects_report_mode",
        ),
        CheckConstraint(
            "(report_mode = 'pdf' AND report_level IS NULL) OR "
            "(report_mode = 'folder_level' AND report_level > case_level)",
            name="ck_projects_report_level",
        ),
    )


ARRANGEMENT_REVISION = {"revision": "0009_arrangement_catalog"}


class ArrangementImport(Base):
    """One applied import of an arrangement catalogue (FR-ARR-01)."""

    __tablename__ = "arrangement_imports"
    __table_args__ = ({"info": ARRANGEMENT_REVISION},)

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name = Column(String(255), nullable=False)
    file_sha256 = Column(String(64), nullable=False)
    row_count = Column(Integer, nullable=False, default=0)
    added = Column(Integer, nullable=False, default=0)
    updated = Column(Integer, nullable=False, default=0)
    unchanged = Column(Integer, nullable=False, default=0)
    removed = Column(Integer, nullable=False, default=0)
    kept = Column(Integer, nullable=False, default=0)
    imported_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)


class ArrangementDossier(Base):
    """One catalogue row: a hồ sơ inside a box (hộp = ProjectCase), QC-16."""

    __tablename__ = "arrangement_dossiers"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "box_number", "dossier_number", "dossier_suffix",
            name="uq_arrangement_dossiers_key",
        ),
        CheckConstraint(
            "box_number >= 1 AND dossier_number >= 1 AND sheet_count >= 1",
            name="ck_arrangement_dossiers_numbers",
        ),
        {"info": ARRANGEMENT_REVISION},
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = Column(
        Integer,
        ForeignKey("project_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    box_number = Column(Integer, nullable=False)
    dossier_number = Column(Integer, nullable=False)
    # Optional letter after the number ("12a"), stored lower case; "" if none.
    dossier_suffix = Column(String(1), nullable=False, default="")
    fonds_code = Column(String(50), nullable=False)
    fonds_name = Column(String(255), nullable=False)
    catalog_number = Column(String(50), nullable=False)
    file_notation = Column(String(20), nullable=True)
    title = Column(String(1000), nullable=False)
    # QC-05 text dates: dd/mm/yyyy, 00 for an unknown day or month.
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    start_year = Column(Integer, nullable=False)
    maintenance_code = Column(String(2), nullable=False)
    sheet_count = Column(Integer, nullable=False)
    term = Column(String(100), nullable=True)
    bad_paper = Column(Boolean, nullable=False, default=False)
    note = Column(String(1000), nullable=True)
    source_row = Column(Integer, nullable=False)
    import_id = Column(
        Integer,
        ForeignKey("arrangement_imports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Set when a later import of this box no longer lists the row but the box
    # had already started scanning, so the row was kept (QC-16 re-import).
    missing_from_import_id = Column(
        Integer,
        ForeignKey("arrangement_imports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)


PROJECT_POLICY_REVISION = {"revision": "0008_project_policies"}


class ProjectPolicy(Base):
    """Per-project policy (FR-PRJ-03). NULL = follow the current QC-01 default."""

    __tablename__ = "project_policies"
    __table_args__ = (
        CheckConstraint(
            "error_threshold_percent >= 0 AND error_threshold_percent <= 100",
            name="ck_project_policies_error_threshold",
        ),
        CheckConstraint(
            "sample_rate_percent >= 0 AND sample_rate_percent <= 100",
            name="ck_project_policies_sample_rate",
        ),
        CheckConstraint(
            "box_deadline_days >= 1 AND box_deadline_days <= 365",
            name="ck_project_policies_box_deadline",
        ),
        CheckConstraint(
            "export_profile IN ('NN-SIP', 'DANG-HD40')",
            name="ck_project_policies_export_profile",
        ),
        CheckConstraint(
            "bad_paper_factor > 0 AND bad_paper_factor <= 10 "
            "AND overtime_factor > 0 AND overtime_factor <= 10 "
            "AND sunday_factor > 0 AND sunday_factor <= 10",
            name="ck_project_policies_factors",
        ),
        {"info": PROJECT_POLICY_REVISION},
    )

    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # QC-08
    error_threshold_percent = Column(Numeric(5, 2), nullable=True)
    sample_rate_percent = Column(Numeric(5, 2), nullable=True)
    box_deadline_days = Column(Integer, nullable=True)
    # QC-02/03
    organ_code = Column(String(50), nullable=True)
    file_notation = Column(String(20), nullable=True)
    # QC-01
    export_profile = Column(String(16), nullable=True)
    # QC-07/09
    bad_paper_factor = Column(Numeric(4, 2), nullable=True)
    overtime_factor = Column(Numeric(4, 2), nullable=True)
    sunday_factor = Column(Numeric(4, 2), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)


class ProjectMember(Base):
    """Input and reviewer pools; a user may hold both roles."""

    __tablename__ = "project_members"

    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    member_role = Column(String(16), primary_key=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        CheckConstraint(
            "member_role IN ('input', 'reviewer')",
            name="ck_project_members_role",
        ),
    )


class ProjectCase(Base):
    """The indivisible assignment unit used when work is transferred."""

    __tablename__ = "project_cases"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_key = Column(String(1024), nullable=False)
    display_name = Column(String(255), nullable=False)
    assigned_input_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        UniqueConstraint("project_id", "case_key", name="uq_project_cases_key"),
    )


class ProjectReportUnit(Base):
    """One logical report that may own one or many PDF assets."""

    __tablename__ = "project_report_units"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = Column(
        Integer,
        ForeignKey("project_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_key = Column(String(1024), nullable=False)
    display_name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="not_entered", index=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        UniqueConstraint("case_id", "report_key", name="uq_project_report_units_key"),
    )


class ProjectDocumentAsset(Base):
    """A managed PDF attached to a logical report."""

    __tablename__ = "project_document_assets"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = Column(
        Integer,
        ForeignKey("project_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_unit_id = Column(
        Integer,
        ForeignKey("project_report_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_document_id = Column(
        Integer,
        ForeignKey("assigned_documents.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    relative_path = Column(String(1024), nullable=False)
    normalized_relative_path = Column(String(1024), nullable=False)
    original_filename = Column(String(255), nullable=False)
    storage_filename = Column(String(255), nullable=False, unique=True)
    content_sha256 = Column(String(64), nullable=False, index=True)
    byte_size = Column(BigInteger, nullable=False)
    client_last_modified = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    error_message = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "normalized_relative_path",
            "content_sha256",
            name="uq_project_document_assets_identity",
        ),
        CheckConstraint("byte_size >= 0", name="ck_project_document_assets_size"),
    )


class ProjectUploadSession(Base):
    """Idempotent manifest session for resumable browser uploads."""

    __tablename__ = "project_upload_sessions"

    id = Column(String(64), primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    client_session_key = Column(String(100), nullable=False)
    manifest_digest = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="created", index=True)
    total_files = Column(Integer, nullable=False, default=0)
    requested_files = Column(Integer, nullable=False, default=0)
    completed_files = Column(Integer, nullable=False, default=0)
    failed_files = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)
    expires_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "client_session_key",
            name="uq_project_upload_sessions_client_key",
        ),
    )


class ProjectUploadFile(Base):
    """Per-file resume cursor; chunks are accepted sequentially and retried safely."""

    __tablename__ = "project_upload_files"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        String(64),
        ForeignKey("project_upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relative_path = Column(String(1024), nullable=False)
    normalized_relative_path = Column(String(1024), nullable=False)
    expected_sha256 = Column(String(64), nullable=False)
    expected_size = Column(BigInteger, nullable=False)
    client_last_modified = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    next_offset = Column(BigInteger, nullable=False, default=0)
    staging_filename = Column(String(255), nullable=True, unique=True)
    error_message = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "normalized_relative_path",
            name="uq_project_upload_files_path",
        ),
        CheckConstraint("expected_size >= 0", name="ck_project_upload_files_size"),
        CheckConstraint("next_offset >= 0", name="ck_project_upload_files_offset"),
    )


class ProjectAssignmentHistory(Base):
    __tablename__ = "project_assignment_history"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("project_cases.id"), nullable=False, index=True)
    assignment_role = Column(String(16), nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)

    __table_args__ = (
        CheckConstraint(
            "assignment_role IN ('input', 'reviewer')",
            name="ck_project_assignment_history_role",
        ),
    )


class CaseInputAssignment(Base):
    """Tracks active and historical input assignments for a project case (FR-ENT-01, BR-06)."""

    __tablename__ = "case_input_assignments"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = Column(
        Integer,
        ForeignKey("project_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime, nullable=False, default=get_utc_now)
    due_at = Column(DateTime, nullable=True)
    deadline_days = Column(Integer, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    ended_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    end_reason = Column(String(255), nullable=True)

    __table_args__ = (
        Index(
            "uq_case_input_assignments_active_case",
            "case_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL"),
            postgresql_where=text("ended_at IS NULL"),
        ),
        {"info": CASE_INPUT_ASSIGNMENT_REVISION},
    )


class ProjectPdfDeletionAudit(Base):
    """Keeps a minimal audit trail after the managed PDF is hard-deleted."""

    __tablename__ = "project_pdf_deletion_audit"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("project_cases.id"), nullable=False, index=True)
    report_unit_id = Column(Integer, ForeignKey("project_report_units.id"), nullable=False, index=True)
    relative_path = Column(String(1024), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)


# Post-baseline pipeline tables (revision 0005); registers them on Base.metadata.
from server.models_workflow import (  # noqa: E402,F401
    CaseStageEvent,
    CaseStageState,
    ProjectStage,
    ProjectStageMember,
)

from server.models_scan import (  # noqa: E402,F401
    CaseScanPackage,
    CaseScanFile,
)

from server.models_entry_qc import (  # noqa: E402,F401
    CaseEntryQcResult,
)
