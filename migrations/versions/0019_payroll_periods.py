"""payroll periods

Revision ID: 0019_payroll_periods
Revises: 0018_project_work_rates
Create Date: 2026-10-08 20:00:00.000000

Chi trả (P2): kỳ đã chốt và các dòng, lưu kèm tham số đã dùng (QC-01).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0019_payroll_periods'
down_revision: Union[str, None] = '0018_project_work_rates'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payroll_periods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('params_json', sa.Text(), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=16, scale=0), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('date_from <= date_to', name='ck_payroll_periods_dates'),
    )
    op.create_index('ix_payroll_periods_project_id', 'payroll_periods', ['project_id'], unique=False)
    op.create_table(
        'payroll_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('period_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('person_name', sa.String(length=255), nullable=False),
        sa.Column('work_code', sa.String(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('factor', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('amount', sa.Numeric(precision=16, scale=0), nullable=False),
        sa.ForeignKeyConstraint(['period_id'], ['payroll_periods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payroll_lines_period_id', 'payroll_lines', ['period_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_payroll_lines_period_id', table_name='payroll_lines')
    op.drop_table('payroll_lines')
    op.drop_index('ix_payroll_periods_project_id', table_name='payroll_periods')
    op.drop_table('payroll_periods')
