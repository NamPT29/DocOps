"""scan catalog match

Revision ID: 0012_scan_catalog_match
Revises: 0011_scan_packages
Create Date: 2026-10-06 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0012_scan_catalog_match'
down_revision = '0011_scan_packages'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('case_scan_packages', sa.Column('match_status', sa.String(length=20), nullable=True))
    op.add_column('case_scan_packages', sa.Column('match_summary', sa.Text(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('case_scan_packages', schema=None) as batch_op:
        batch_op.drop_column('match_summary')
        batch_op.drop_column('match_status')
