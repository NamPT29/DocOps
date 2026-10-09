"""Chi trả theo sản lượng (P1: đơn giá, revision 0018_project_work_rates)."""

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text

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


PERIODS_REVISION = "0019_payroll_periods"


class PayrollPeriod(Base):
    """Kỳ chi trả đã chốt (P2): lưu kèm tham số đã dùng (đơn giá, hệ số giấy xấu, phiên bản QC) – QC-01."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        CheckConstraint("date_from <= date_to", name="ck_payroll_periods_dates"),
        {"info": {"revision": PERIODS_REVISION}},
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    params_json = Column(Text, nullable=False)
    total_amount = Column(Numeric(16, 0), nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class PayrollLine(Base):
    """Một dòng (người × mã công việc) của kỳ đã chốt; giữ nguyên số đã tính, kể cả tên người lúc chốt."""

    __tablename__ = "payroll_lines"
    __table_args__ = ({"info": {"revision": PERIODS_REVISION}},)

    id = Column(Integer, primary_key=True)
    period_id = Column(Integer, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    person_name = Column(String(255), nullable=False)
    work_code = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    factor = Column(Numeric(4, 2), nullable=False)
    amount = Column(Numeric(16, 0), nullable=False)
