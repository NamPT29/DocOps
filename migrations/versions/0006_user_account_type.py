"""Add account type (Hành chính/CTV) and CTV expiry date to users.

Revision ID: 0006_user_account_type
Revises: 0005_workflow_stages

FR-AUT-02/03. Every existing account becomes 'staff' (Hành chính) through the
server default; administrators keep role='admin' and ignore account_type.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_user_account_type"
down_revision = "0005_workflow_stages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode emits plain ALTER TABLE on PostgreSQL and rebuilds the table
    # on SQLite, which cannot add a CHECK constraint to an existing table.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "account_type",
            sa.String(16),
            nullable=False,
            server_default="staff",
        ))
        batch.add_column(sa.Column("expires_on", sa.Date(), nullable=True))
        batch.create_check_constraint(
            "ck_users_account_type",
            "account_type IN ('staff', 'ctv')",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_account_type", type_="check")
        batch.drop_column("expires_on")
        batch.drop_column("account_type")
