"""Chi trả theo sản lượng (P1: đơn giá, revision 0018_project_work_rates)."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, text

from server.database import Base

WORK_RATES_REVISION = "0018_project_work_rates"


class ProjectWorkRate(Base):
    """Đơn giá loại 1 (giấy thường) của một mã công việc trong dự án; loại 2 = loại 1 × hệ số giấy xấu (QC-07)."""

    __tablename__ = "project_work_rates"
    __table_args__ = (
        CheckConstraint("work_code IN ('NL-1', 'CN-1', 'SC-A4-1')", name="ck_project_work_rates_code"),
        CheckConstraint("unit_price >= 0", name="ck_project_work_rates_price"),
        UniqueConstraint("project_id", "work_code", name="uq_project_work_rates_code"),
        {"info": {"revision": WORK_RATES_REVISION}},
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    work_code = Column(String(16), nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
