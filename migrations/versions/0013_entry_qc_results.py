"""entry qc results

Revision ID: 0013_entry_qc_results
Revises: 0012_scan_catalog_match
Create Date: 2026-10-06 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013_entry_qc_results'
down_revision: Union[str, None] = '0012_scan_catalog_match'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_entry_qc_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('reports_total', sa.Integer(), nullable=False),
        sa.Column('reports_assessed', sa.Integer(), nullable=False),
        sa.Column('error_reports', sa.Integer(), nullable=False),
        sa.Column('total_fields', sa.Integer(), nullable=False),
        sa.Column('error_fields', sa.Integer(), nullable=False),
        sa.Column('rate_percent', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('threshold_percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        
        sa.ForeignKeyConstraint(['case_id'], ['project_cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'round', name='uq_case_entry_qc_round'),
        
        sa.CheckConstraint('round > 0', name='chk_round_positive'),
        sa.CheckConstraint('reports_total >= 0', name='chk_reports_total_non_neg'),
        sa.CheckConstraint('reports_assessed >= 0', name='chk_reports_assessed_non_neg'),
        sa.CheckConstraint('error_reports >= 0', name='chk_error_reports_non_neg'),
        sa.CheckConstraint('total_fields >= 0', name='chk_total_fields_non_neg'),
        sa.CheckConstraint('error_fields >= 0', name='chk_error_fields_non_neg'),
        sa.CheckConstraint('rate_percent >= 0 AND rate_percent <= 100', name='chk_rate_percent_range')
    )
    op.create_index(op.f('ix_case_entry_qc_results_id'), 'case_entry_qc_results', ['id'], unique=False)
    op.create_index(op.f('ix_case_entry_qc_results_project_id'), 'case_entry_qc_results', ['project_id'], unique=False)
    op.create_index(op.f('ix_case_entry_qc_results_case_id'), 'case_entry_qc_results', ['case_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_case_entry_qc_results_case_id'), table_name='case_entry_qc_results')
    op.drop_index(op.f('ix_case_entry_qc_results_project_id'), table_name='case_entry_qc_results')
    op.drop_index(op.f('ix_case_entry_qc_results_id'), table_name='case_entry_qc_results')
    op.drop_table('case_entry_qc_results')
