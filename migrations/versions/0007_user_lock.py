"""Add account locking and its append-only log.

Revision ID: 0007_user_lock
Revises: 0006_user_account_type

Nhiệm vụ 1c: an admin may lock an account (no sign-in, every session revoked)
and unlock it again; each change is logged with actor, time and reason.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_user_lock"
down_revision = "0006_user_account_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A plain ADD COLUMN with a default works on PostgreSQL and SQLite and
    # leaves the rest of the users table (and its constraints) untouched.
    op.add_column(
        "users",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "user_lock_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "action IN ('lock', 'unlock')",
            name="ck_user_lock_events_action",
        ),
    )
    op.create_index("ix_user_lock_events_user_id", "user_lock_events", ["user_id"])
    op.create_index(
        "ix_user_lock_events_actor_user_id", "user_lock_events", ["actor_user_id"]
    )


def downgrade() -> None:
    op.drop_table("user_lock_events")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_locked")
