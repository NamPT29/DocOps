from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, text, CheckConstraint, UniqueConstraint
from sqlalchemy.sql import func
from server.database import Base

class CasePaperHandoff(Base):
    __tablename__ = 'case_paper_handoffs'
    __table_args__ = (
        CheckConstraint(
            "milestone IN ('received_from_client', 'to_arrangement', 'to_scan', 'returned_to_storage', 'returned_to_client')",
            name='ck_case_paper_handoffs_milestone'
        ),
        UniqueConstraint('case_id', 'milestone', name='uq_case_paper_handoffs_case_milestone'),
        {"info": {"revision": "0016_case_paper_handoffs"}}
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), index=True, nullable=False)
    case_id = Column(Integer, ForeignKey('project_cases.id', ondelete='CASCADE'), index=True, nullable=False)
    milestone = Column(String(32), nullable=False)
    happened_at = Column(DateTime, nullable=False)
    handed_by = Column(String(255), nullable=False)
    received_by = Column(String(255), nullable=False)
    note = Column(String(1000), nullable=True)
    recorded_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
