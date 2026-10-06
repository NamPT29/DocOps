"""entry qc round2

Revision ID: 0015_entry_qc_round2
Revises: 0014_entry_qc_resolution
Create Date: 2026-10-06 20:39:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0015_entry_qc_round2'
down_revision: Union[str, None] = '0014_entry_qc_resolution'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_entry_qc_samplings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('population_count', sa.Integer(), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False),
        sa.Column('sample_rate_percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('seed', sa.BigInteger(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['project_cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'round', name='uq_case_entry_qc_samplings_round')
    )
    with op.batch_alter_table('case_entry_qc_samplings') as batch_op:
        batch_op.create_index(batch_op.f('ix_case_entry_qc_samplings_case_id'), ['case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_case_entry_qc_samplings_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_case_entry_qc_samplings_project_id'), ['project_id'], unique=False)
        batch_op.create_check_constraint('chk_sampling_round_2', 'round = 2')
        batch_op.create_check_constraint('chk_sampling_sample_size_pos', 'sample_size >= 1')

    op.create_table(
        'case_entry_qc_sample_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sampling_id', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('baseline_data_json', sa.Text(), nullable=False),
        sa.Column('final_data_json', sa.Text(), nullable=True),
        sa.Column('visible_field_count', sa.Integer(), nullable=True),
        sa.Column('changed_field_count', sa.Integer(), nullable=True),
        sa.Column('checked_by_user_id', sa.Integer(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['checked_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['sampling_id'], ['case_entry_qc_samplings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sampling_id', 'submission_id', name='uq_case_entry_qc_sample_item')
    )
    with op.batch_alter_table('case_entry_qc_sample_items') as batch_op:
        batch_op.create_index(batch_op.f('ix_case_entry_qc_sample_items_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_case_entry_qc_sample_items_sampling_id'), ['sampling_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_case_entry_qc_sample_items_submission_id'), ['submission_id'], unique=False)

    with op.batch_alter_table('project_policies') as batch_op:
        batch_op.add_column(sa.Column('entry_qc_round2_enabled', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('project_policies') as batch_op:
        batch_op.drop_column('entry_qc_round2_enabled')

    with op.batch_alter_table('case_entry_qc_sample_items') as batch_op:
        batch_op.drop_index(batch_op.f('ix_case_entry_qc_sample_items_submission_id'))
        batch_op.drop_index(batch_op.f('ix_case_entry_qc_sample_items_sampling_id'))
        batch_op.drop_index(batch_op.f('ix_case_entry_qc_sample_items_id'))
    op.drop_table('case_entry_qc_sample_items')

    with op.batch_alter_table('case_entry_qc_samplings') as batch_op:
        batch_op.drop_index(batch_op.f('ix_case_entry_qc_samplings_project_id'))
        batch_op.drop_index(batch_op.f('ix_case_entry_qc_samplings_id'))
        batch_op.drop_index(batch_op.f('ix_case_entry_qc_samplings_case_id'))
    op.drop_table('case_entry_qc_samplings')
