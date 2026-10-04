"""Add per-project policy settings (FR-PRJ-01/03).

Revision ID: 0008_project_policies
Revises: 0007_user_lock

Purely additive. Every column is nullable: NULL means "follow the current
QC-01 default", so existing projects need no backfill (QC-01 v0.1.1).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_project_policies"
down_revision = "0007_user_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_policies",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("error_threshold_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("sample_rate_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("box_deadline_days", sa.Integer(), nullable=True),
        sa.Column("organ_code", sa.String(50), nullable=True),
        sa.Column("file_notation", sa.String(20), nullable=True),
        sa.Column("export_profile", sa.String(16), nullable=True),
        sa.Column("bad_paper_factor", sa.Numeric(4, 2), nullable=True),
        sa.Column("overtime_factor", sa.Numeric(4, 2), nullable=True),
        sa.Column("sunday_factor", sa.Numeric(4, 2), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("project_id"),
        sa.CheckConstraint(
            "error_threshold_percent >= 0 AND error_threshold_percent <= 100",
            name="ck_project_policies_error_threshold",
        ),
        sa.CheckConstraint(
            "sample_rate_percent >= 0 AND sample_rate_percent <= 100",
            name="ck_project_policies_sample_rate",
        ),
        sa.CheckConstraint(
            "box_deadline_days >= 1 AND box_deadline_days <= 365",
            name="ck_project_policies_box_deadline",
        ),
        sa.CheckConstraint(
            "export_profile IN ('NN-SIP', 'DANG-HD40')",
            name="ck_project_policies_export_profile",
        ),
        sa.CheckConstraint(
            "bad_paper_factor > 0 AND bad_paper_factor <= 10 "
            "AND overtime_factor > 0 AND overtime_factor <= 10 "
            "AND sunday_factor > 0 AND sunday_factor <= 10",
            name="ck_project_policies_factors",
        ),
    )
    op.create_index(
        "ix_project_policies_updated_by_user_id",
        "project_policies",
        ["updated_by_user_id"],
    )


def downgrade() -> None:
    op.drop_table("project_policies")
