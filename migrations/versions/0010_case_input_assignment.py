"""Add case input assignments tracking and submission author attribution (FR-ENT-01, BR-06, revision 0010).

Revision ID: 0010_case_input_assignment
Revises: 0009_arrangement_catalog

Nhiệm vụ 4a:
- Giao / thu hồi hộp nhập liệu với thời hạn cố định (due_at, deadline_days).
- Chặn ở DB: mỗi hộp tối đa 1 dòng phân công nhập liệu đang hiệu lực (WHERE ended_at IS NULL).
- Ghi nhận người nộp duyệt (submitted_by_user_id) trên submissions khi chuyển sang pending_review.
- Backfill dòng hiệu lực cho hộp đã giao trước migration với due_at = NULL.
- Backfill submitted_by_user_id = created_by_user_id cho các văn bản khác draft.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_case_input_assignment"
down_revision = "0009_arrangement_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. submissions.submitted_by_user_id
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("submitted_by_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_submissions_submitted_by_user_id",
            "users",
            ["submitted_by_user_id"],
            ["id"],
        )
        batch.create_index(
            "ix_submissions_submitted_by_user_id",
            ["submitted_by_user_id"],
        )

    # 2. case_input_assignments
    op.create_table(
        "case_input_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("deadline_days", sa.Integer(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("ended_by_user_id", sa.Integer(), nullable=True),
        sa.Column("end_reason", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["project_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ended_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_case_input_assignments_project_id",
        "case_input_assignments",
        ["project_id"],
    )
    op.create_index(
        "ix_case_input_assignments_case_id",
        "case_input_assignments",
        ["case_id"],
    )
    op.create_index(
        "ix_case_input_assignments_user_id",
        "case_input_assignments",
        ["user_id"],
    )
    op.create_index(
        "uq_case_input_assignments_active_case",
        "case_input_assignments",
        ["case_id"],
        unique=True,
        sqlite_where=sa.text("ended_at IS NULL"),
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    # 3. Data backfill: submissions.submitted_by_user_id for non-draft submissions
    op.execute(
        sa.text(
            "UPDATE submissions "
            "SET submitted_by_user_id = created_by_user_id "
            "WHERE status != 'draft' AND created_by_user_id IS NOT NULL"
        )
    )

    # 4. Data backfill: active case_input_assignments for existing assigned cases
    op.execute(
        sa.text(
            "INSERT INTO case_input_assignments "
            "(project_id, case_id, user_id, assigned_by_user_id, assigned_at, due_at, deadline_days, ended_at, ended_by_user_id, end_reason) "
            "SELECT project_id, id, assigned_input_user_id, NULL, created_at, NULL, NULL, NULL, NULL, NULL "
            "FROM project_cases "
            "WHERE assigned_input_user_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "uq_case_input_assignments_active_case",
        table_name="case_input_assignments",
        sqlite_where=sa.text("ended_at IS NULL"),
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_index("ix_case_input_assignments_user_id", table_name="case_input_assignments")
    op.drop_index("ix_case_input_assignments_case_id", table_name="case_input_assignments")
    op.drop_index("ix_case_input_assignments_project_id", table_name="case_input_assignments")
    op.drop_table("case_input_assignments")

    with op.batch_alter_table("submissions") as batch:
        batch.drop_index("ix_submissions_submitted_by_user_id")
        batch.drop_constraint("fk_submissions_submitted_by_user_id", type_="foreignkey")
        batch.drop_column("submitted_by_user_id")
