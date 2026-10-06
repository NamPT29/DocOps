from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, text, CheckConstraint, UniqueConstraint, String, Text, BigInteger
from sqlalchemy.orm import relationship

from server.database import Base


class CaseEntryQcResult(Base):
    __tablename__ = "case_entry_qc_results"
    __table_args__ = (
        UniqueConstraint('case_id', 'round', name='uq_case_entry_qc_round'),
        CheckConstraint('round > 0', name='chk_round_positive'),
        CheckConstraint('reports_total >= 0', name='chk_reports_total_non_neg'),
        CheckConstraint('reports_assessed >= 0', name='chk_reports_assessed_non_neg'),
        CheckConstraint('error_reports >= 0', name='chk_error_reports_non_neg'),
        CheckConstraint('total_fields >= 0', name='chk_total_fields_non_neg'),
        CheckConstraint('error_fields >= 0', name='chk_error_fields_non_neg'),
        CheckConstraint('rate_percent >= 0 AND rate_percent <= 100', name='chk_rate_percent_range'),
        CheckConstraint("resolution = 'approved'", name='ck_entry_qc_resolution'),
        {"info": {"revision": "0014_entry_qc_resolution"}},
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("project_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    round = Column(Integer, nullable=False, default=1)
    
    reports_total = Column(Integer, nullable=False, default=0)
    reports_assessed = Column(Integer, nullable=False, default=0)
    error_reports = Column(Integer, nullable=False, default=0)
    
    total_fields = Column(Integer, nullable=False, default=0)
    error_fields = Column(Integer, nullable=False, default=0)
    
    rate_percent = Column(Numeric(6, 2), nullable=False, default=Decimal('0.00'))
    threshold_percent = Column(Numeric(5, 2), nullable=False)
    passed = Column(Boolean, nullable=False)
    
    resolution = Column(String(20), nullable=True, info={"revision": "0014_entry_qc_resolution"})
    resolution_reason = Column(Text, nullable=True, info={"revision": "0014_entry_qc_resolution"})
    resolved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, info={"revision": "0014_entry_qc_resolution"})
    resolved_at = Column(DateTime, nullable=True, info={"revision": "0014_entry_qc_resolution"})
    
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    
    case = relationship("ProjectCase")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_user_id])


class CaseEntryQcSampling(Base):
    __tablename__ = "case_entry_qc_samplings"
    __table_args__ = (
        UniqueConstraint('case_id', 'round', name='uq_case_entry_qc_samplings_round'),
        CheckConstraint('round = 2', name='chk_sampling_round_2'),
        CheckConstraint('sample_size >= 1', name='chk_sampling_sample_size_pos'),
        {"info": {"revision": "0015_entry_qc_round2"}},
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("project_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    round = Column(Integer, nullable=False)
    population_count = Column(Integer, nullable=False)
    sample_size = Column(Integer, nullable=False)
    sample_rate_percent = Column(Numeric(5, 2), nullable=False)
    seed = Column(BigInteger, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class CaseEntryQcSampleItem(Base):
    __tablename__ = "case_entry_qc_sample_items"
    __table_args__ = (
        UniqueConstraint('sampling_id', 'submission_id', name='uq_case_entry_qc_sample_item'),
        {"info": {"revision": "0015_entry_qc_round2"}},
    )

    id = Column(Integer, primary_key=True, index=True)
    sampling_id = Column(Integer, ForeignKey("case_entry_qc_samplings.id", ondelete="CASCADE"), nullable=False, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    baseline_data_json = Column(Text, nullable=False)
    final_data_json = Column(Text, nullable=True)
    visible_field_count = Column(Integer, nullable=True)
    changed_field_count = Column(Integer, nullable=True)
    checked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    checked_at = Column(DateTime, nullable=True)
    
    checked_by = relationship("User", foreign_keys=[checked_by_user_id])
