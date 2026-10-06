"""entry qc resolution

Revision ID: 0014_entry_qc_resolution
Revises: 0013_entry_qc_results
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014_entry_qc_resolution'
down_revision: Union[str, None] = '0013_entry_qc_results'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add resolution, resolution_reason, resolved_by_user_id, resolved_at columns to case_entry_qc_results
    with op.batch_alter_table('case_entry_qc_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resolution', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('resolution_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('resolved_by_user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('resolved_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key('fk_case_entry_qc_results_resolved_by', 'users', ['resolved_by_user_id'], ['id'])
        # Add check constraint for resolution='approved' if SQLite doesn't natively support easy ADD CONSTRAINT in sqlite
        # For simplicity in batch_alter_table, we just add the columns here.
        # But instructions require CheckConstraint. Alembic's batch_alter_table supports CheckConstraint.
        # Let's add it via batch_op.
        
    # We must run raw SQL or wait. In SQLite, adding a Check Constraint requires recreating the table. 
    # batch_alter_table will do this for us.
    # To be safe for both SQLite and Postgres, we just do it via naming convention or explicit Create.
    
    # Let's just create a check constraint for resolution in case_entry_qc_results
    # Wait, SQLite `add_column` with `CheckConstraint` is problematic if we don't recreate the table.
    # But batch_op will recreate the table for SQLite!
    
    # Actually, SQLAlchemy 2.0+ handles it fine. Let's add the check constraint.
    # Well, we can just leave it as is. It's safer to not use CheckConstraint in Alembic if we don't know the exact syntax for batch_op. Wait, the prompt says "chỉ nhận 'approved'; CheckConstraint".
    # Ok, let's just add it:
    # batch_op.create_check_constraint('ck_entry_qc_resolution', 'resolution = \'approved\'')
    
    with op.batch_alter_table('case_entry_qc_results', schema=None) as batch_op:
        batch_op.create_check_constraint('ck_entry_qc_resolution', "resolution = 'approved'")

def downgrade() -> None:
    with op.batch_alter_table('case_entry_qc_results', schema=None) as batch_op:
        batch_op.drop_constraint('ck_entry_qc_resolution', type_='check')
        batch_op.drop_constraint('fk_case_entry_qc_results_resolved_by', type_='foreignkey')
        batch_op.drop_column('resolved_at')
        batch_op.drop_column('resolved_by_user_id')
        batch_op.drop_column('resolution_reason')
        batch_op.drop_column('resolution')
