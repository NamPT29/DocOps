"""Tables for the end-to-end digitization pipeline (revision 0005).

These tables are additive: they never alter the frozen baseline tables. Each
carries ``info={"revision": ...}`` so the baseline snapshot generator skips it.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from server.database import Base, get_utc_now


WORKFLOW_REVISION = "0005_workflow_stages"
_TABLE_INFO = {"info": {"revision": WORKFLOW_REVISION}}


class ProjectStage(Base):
    """Which pipeline stages a project runs; absent rows mean legacy mode."""

    __tablename__ = "project_stages"

    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stage_key = Column(String(32), primary_key=True)
    position = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (_TABLE_INFO,)


class ProjectStageMember(Base):
    """Workers for the stages that have no input/reviewer pool of their own."""

    __tablename__ = "project_stage_members"

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
    stage_key = Column(String(32), primary_key=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (_TABLE_INFO,)


class CaseStageState(Base):
    """Progress of one case (hồ sơ) in one stage; a missing row is ``pending``."""

    __tablename__ = "case_stage_states"

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
    stage_key = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    rework_count = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now)
    updated_at = Column(DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        UniqueConstraint("case_id", "stage_key", name="uq_case_stage_states_case_stage"),
        Index("ix_case_stage_states_project_stage_status", "project_id", "stage_key", "status"),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'done', 'rejected')",
            name="ck_case_stage_states_status",
        ),
        CheckConstraint("rework_count >= 0", name="ck_case_stage_states_rework"),
        _TABLE_INFO,
    )


class CaseStageEvent(Base):
    """Append-only audit trail of every stage transition."""

    __tablename__ = "case_stage_events"

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
    stage_key = Column(String(32), nullable=False)
    action = Column(String(24), nullable=False)
    from_status = Column(String(16), nullable=True)
    to_status = Column(String(16), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=get_utc_now, index=True)

    __table_args__ = (_TABLE_INFO,)
