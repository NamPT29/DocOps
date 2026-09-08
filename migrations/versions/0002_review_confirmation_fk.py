"""Add the reviewer-confirmation user foreign key.

Revision ID: 0002_review_confirmation_fk
Revises: 0001_current_schema
"""

from __future__ import annotations

from alembic import op


revision = "0002_review_confirmation_fk"
down_revision = "0001_current_schema"
branch_labels = None
depends_on = None

TABLE_NAME = "submission_review_histories"
CONSTRAINT_NAME = (
    "submission_review_histories_confirmed_by_user_id_fkey"
)


def upgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.create_foreign_key(
            CONSTRAINT_NAME,
            "users",
            ["confirmed_by_user_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="foreignkey")
