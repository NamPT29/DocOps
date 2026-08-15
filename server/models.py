from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from datetime import datetime
from server.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False) # Scrypt hash; legacy values migrate on login
    role = Column(String(255), default="user") # 'admin' or 'user'
    created_at = Column(DateTime, default=datetime.utcnow)


class UserCapability(Base):
    __tablename__ = "user_capabilities"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    can_input = Column(Boolean, nullable=False, default=True)
    can_review = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(255), default="in_progress") # in_progress, completed

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
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
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class SubmissionViewPresence(Base):
    __tablename__ = 'submission_view_presence'

    submission_id = Column(Integer, ForeignKey('submissions.id'), primary_key=True)
    viewer_user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class AssignedDocument(Base):
    __tablename__ = "assigned_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    uuid_filename = Column(String(255), nullable=False, unique=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True) # null = unassigned
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    status = Column(String(255), default="pending") # pending, assigned, completed
    created_at = Column(DateTime, default=datetime.utcnow)


class AssignedDocumentReviewAssignment(Base):
    __tablename__ = "assigned_document_review_assignments"

    document_id = Column(
        Integer,
        ForeignKey("assigned_documents.id"),
        primary_key=True,
    )
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    current_path = Column(String(1024), nullable=True)
    error_message = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
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
from sqlalchemy import UniqueConstraint

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
