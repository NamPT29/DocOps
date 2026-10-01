"""Add the end-to-end pipeline (workflow stage) tables.

Revision ID: 0005_workflow_stages
Revises: 0004_normalize_legacy_workflow

Purely additive: no existing table is altered.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_workflow_stages"
down_revision = "0004_normalize_legacy_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_stages",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("stage_key", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "stage_key"),
    )
    op.create_table(
        "project_stage_members",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stage_key", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id", "stage_key"),
    )
    op.create_index(
        "ix_project_stage_members_user_id", "project_stage_members", ["user_id"]
    )
    op.create_table(
        "case_stage_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("stage_key", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("rework_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["project_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "stage_key", name="uq_case_stage_states_case_stage"),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'done', 'rejected')",
            name="ck_case_stage_states_status",
        ),
        sa.CheckConstraint("rework_count >= 0", name="ck_case_stage_states_rework"),
    )
    op.create_index("ix_case_stage_states_project_id", "case_stage_states", ["project_id"])
    op.create_index("ix_case_stage_states_case_id", "case_stage_states", ["case_id"])
    op.create_index(
        "ix_case_stage_states_assigned_user_id", "case_stage_states", ["assigned_user_id"]
    )
    op.create_index(
        "ix_case_stage_states_project_stage_status",
        "case_stage_states",
        ["project_id", "stage_key", "status"],
    )
    op.create_table(
        "case_stage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("stage_key", sa.String(32), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["project_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_stage_events_project_id", "case_stage_events", ["project_id"])
    op.create_index("ix_case_stage_events_case_id", "case_stage_events", ["case_id"])
    op.create_index("ix_case_stage_events_actor_user_id", "case_stage_events", ["actor_user_id"])
    op.create_index("ix_case_stage_events_created_at", "case_stage_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("case_stage_events")
    op.drop_table("case_stage_states")
    op.drop_table("project_stage_members")
    op.drop_table("project_stages")
