"""project work rates

Revision ID: 0018_project_work_rates
Revises: 0017_project_handover_lock
Create Date: 2026-10-08 19:00:00.000000

Chi trả theo sản lượng (P1): đơn giá loại 1 của từng mã công việc trong dự án.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0018_project_work_rates'
down_revision: Union[str, None] = '0017_project_handover_lock'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project_work_rates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('work_code', sa.String(length=16), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'work_code', name='uq_project_work_rates_code'),
        sa.CheckConstraint("work_code IN ('NL-1', 'CN-1', 'SC-A4-1')", name='ck_project_work_rates_code'),
        sa.CheckConstraint('unit_price >= 0', name='ck_project_work_rates_price'),
    )
    op.create_index('ix_project_work_rates_project_id', 'project_work_rates', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_project_work_rates_project_id', table_name='project_work_rates')
    op.drop_table('project_work_rates')
