"""case paper handoffs

Revision ID: 0016_case_paper_handoffs
Revises: 0015_entry_qc_round2
Create Date: 2026-10-08 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016_case_paper_handoffs'
down_revision: Union[str, None] = '0015_entry_qc_round2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_paper_handoffs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('milestone', sa.String(length=32), nullable=False),
        sa.Column('happened_at', sa.DateTime(), nullable=False),
        sa.Column('handed_by', sa.String(length=255), nullable=False),
        sa.Column('received_by', sa.String(length=255), nullable=False),
        sa.Column('note', sa.String(length=1000), nullable=True),
        sa.Column('recorded_by_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['project_cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'milestone', name='uq_case_paper_handoffs_case_milestone')
    )
    with op.batch_alter_table('case_paper_handoffs') as batch_op:
        batch_op.create_index(batch_op.f('ix_case_paper_handoffs_case_id'), ['case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_case_paper_handoffs_project_id'), ['project_id'], unique=False)
        batch_op.create_check_constraint(
            'ck_case_paper_handoffs_milestone',
            "milestone IN ('received_from_client', 'to_arrangement', 'to_scan', 'returned_to_storage', 'returned_to_client')"
        )


def downgrade() -> None:
    with op.batch_alter_table('case_paper_handoffs') as batch_op:
        batch_op.drop_index(batch_op.f('ix_case_paper_handoffs_project_id'))
        batch_op.drop_index(batch_op.f('ix_case_paper_handoffs_case_id'))
    op.drop_table('case_paper_handoffs')
