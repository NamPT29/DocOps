from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from server.database import Base, get_utc_now

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False) # Scrypt hash; legacy values migrate on login
    role = Column(String(255), default="user") # 'admin' or 'user'
    created_at = Column(DateTime, default=get_utc_now)


class UserCapability(Base):
    __tablename__ = "user_capabilities"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    can_input = Column(Boolean, nullable=False, default=True)
    can_review = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now)


class ApiRateLimitBucket(Base):
    """Shared fixed-window counters used by all API worker processes."""

    __tablename__ = "api_rate_limit_buckets"

    bucket_key = Column(String(64), primary_key=True)
    request_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
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
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=get_utc_now)
    is_active = Column(Boolean, default=True)
    config_json = Column(Text, nullable=True) # Lưu cấu hình JSON của biểu mẫu

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True) # Which template this task is for
    title = Column(String(255), nullable=False)
    target_quantity = Column(Integer, nullable=False)
    current_quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=get_utc_now)
    status = Column(String(255), default="in_progress") # in_progress, completed

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=get_utc_now)
    
    # Store the dynamically filled JSON
    data_json = Column(Text, nullable=False)
    
    # Track which template this belongs to
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    
    # Track which user created this submission
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

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
    
    # Workflow status: draft, pending_review, rejected, approved
    status = Column(String(50), default="draft")


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
    last_seen_at = Column(DateTime, nullable=False, default=get_utc_now)

class AssignedDocument(Base):
    __tablename__ = "assigned_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    uuid_filename = Column(String(255), nullable=False, unique=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True) # null = unassigned
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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
from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint

class Dictionary(Base):
    __tablename__ = "dictionaries"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    name = Column(String(100), index=True, nullable=False) # e.g. "DM_DanToc"
    description = Column(String(255), nullable=True) # e.g. "Dân tộc"
    
    __table_args__ = (UniqueConstraint('template_id', 'name', name='uix_template_dict_name'),)
    
    items = relationship("DictionaryItem", back_populates="dictionary", cascade="all, delete-orphan")

class DictionaryItem(Base):
    __tablename__ = "dictionary_items"

    id = Column(Integer, primary_key=True, index=True)
    dictionary_id = Column(Integer, ForeignKey("dictionaries.id"))
    code = Column(String(50), nullable=True)  # e.g. "1" or "01"
    value = Column(String(255), nullable=False) # e.g. "Kinh"
    
    dictionary = relationship("Dictionary", back_populates="items")


class Project(Base):
    """A project pins one configured template and one folder hierarchy."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
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
    status = Column(String(32), nullable=False, default="configuring", index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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


class ProjectPdfDeletionAudit(Base):
    """Keeps a minimal audit trail after the managed PDF is hard-deleted."""

    __tablename__ = "project_pdf_deletion_audit"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("project_cases.id"), nullable=False, index=True)
    report_unit_id = Column(Integer, ForeignKey("project_report_units.id"), nullable=False, index=True)
    relative_path = Column(String(1024), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)
