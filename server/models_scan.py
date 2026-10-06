"""Tables for the scan packages ingestion (revision 0011_scan_packages).

These tables are additive. They carry info={"revision": "0011_scan_packages"}
so the baseline snapshot generator skips them.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from server.database import Base, get_utc_now


SCAN_REVISION = "0011_scan_packages"
_TABLE_INFO = {"info": {"revision": SCAN_REVISION}}


class CaseScanPackage(Base):
    """A scan package submitted for a project case (FR-SCN-01)."""

    __tablename__ = "case_scan_packages"

    id = Column(Integer, primary_key=True)
    case_id = Column(
        Integer,
        ForeignKey("project_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)
    
    scanned_by_name = Column(String(255), nullable=True)
    scanned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    submitted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    scan_user_name_level = Column(Integer, nullable=False, default=1)
    source_path = Column(String(1024), nullable=False)
    
    total_pages = Column(Integer, nullable=False, default=0)
    total_a4_equivalent = Column(Integer, nullable=False, default=0)
    conversion_parameters = Column(Text, nullable=True)
    
    total_files = Column(Integer, nullable=False, default=0)
    processed_files = Column(Integer, nullable=False, default=0)
    failed_files = Column(Integer, nullable=False, default=0)
    
    warning_flags = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="processing", index=True)
    match_status = Column(String(20), nullable=True, info={"revision": "0012_scan_catalog_match"})
    match_summary = Column(Text, nullable=True, info={"revision": "0012_scan_catalog_match"})
    
    started_at = Column(DateTime, nullable=False, default=get_utc_now)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_case_scan_packages_case_version"),
        Index(
            "uq_case_scan_packages_active_case",
            "case_id",
            unique=True,
            sqlite_where=text("status = 'processing'"),
            postgresql_where=text("status = 'processing'"),
        ),
        CheckConstraint(
            "status IN ('processing', 'done', 'failed')",
            name="ck_case_scan_packages_status"
        ),
        CheckConstraint("total_pages >= 0", name="ck_case_scan_packages_total_pages"),
        CheckConstraint("total_a4_equivalent >= 0", name="ck_case_scan_packages_total_a4"),
        CheckConstraint("total_files >= 0", name="ck_case_scan_packages_total_files"),
        CheckConstraint("processed_files >= 0", name="ck_case_scan_packages_processed_files"),
        CheckConstraint("failed_files >= 0", name="ck_case_scan_packages_failed_files"),
        _TABLE_INFO,
    )


class CaseScanFile(Base):
    """Individual PDF file records inside a scan package (QC-06)."""

    __tablename__ = "case_scan_files"

    id = Column(Integer, primary_key=True)
    package_id = Column(
        Integer,
        ForeignKey("case_scan_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    relative_path = Column(String(1024), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    page_count = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=True)
    
    a0_pages = Column(Integer, nullable=False, default=0)
    a1_pages = Column(Integer, nullable=False, default=0)
    a2_pages = Column(Integer, nullable=False, default=0)
    a3_pages = Column(Integer, nullable=False, default=0)
    a4_pages = Column(Integer, nullable=False, default=0)
    a5_pages = Column(Integer, nullable=False, default=0)
    a4_equivalent = Column(Integer, nullable=False, default=0)
    
    is_pdf = Column(Boolean, nullable=False, default=True)
    
    status = Column(String(32), nullable=False, default="ok")
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        Index("ix_case_scan_files_package_path", "package_id", "relative_path", unique=True),
        CheckConstraint(
            "status IN ('ok', 'error', 'incomplete', 'not_pdf')",
            name="ck_case_scan_files_status"
        ),
        CheckConstraint("page_count >= -1", name="ck_case_scan_files_page_count"),
        CheckConstraint("a0_pages >= 0", name="ck_case_scan_files_a0"),
        CheckConstraint("a1_pages >= 0", name="ck_case_scan_files_a1"),
        CheckConstraint("a2_pages >= 0", name="ck_case_scan_files_a2"),
        CheckConstraint("a3_pages >= 0", name="ck_case_scan_files_a3"),
        CheckConstraint("a4_pages >= 0", name="ck_case_scan_files_a4"),
        CheckConstraint("a5_pages >= 0", name="ck_case_scan_files_a5"),
        CheckConstraint("a4_equivalent >= 0", name="ck_case_scan_files_a4_eq"),
        CheckConstraint("file_size >= 0", name="ck_case_scan_files_size"),
        _TABLE_INFO,
    )
