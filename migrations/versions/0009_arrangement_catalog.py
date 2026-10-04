"""Add the arrangement catalogue (mục lục chỉnh lý) tables (FR-ARR-01, QC-16).

Revision ID: 0009_arrangement_catalog
Revises: 0008_project_policies

Purely additive: one row per dossier (hồ sơ) linked to its box (project case)
and a log of applied imports.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_arrangement_catalog"
down_revision = "0008_project_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arrangement_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("added", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("removed", sa.Integer(), nullable=False),
        sa.Column("kept", sa.Integer(), nullable=False),
        sa.Column("imported_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_arrangement_imports_project_id", "arrangement_imports", ["project_id"])
    op.create_index(
        "ix_arrangement_imports_imported_by_user_id",
        "arrangement_imports",
        ["imported_by_user_id"],
    )
    op.create_table(
        "arrangement_dossiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("box_number", sa.Integer(), nullable=False),
        sa.Column("dossier_number", sa.Integer(), nullable=False),
        sa.Column("dossier_suffix", sa.String(1), nullable=False),
        sa.Column("fonds_code", sa.String(50), nullable=False),
        sa.Column("fonds_name", sa.String(255), nullable=False),
        sa.Column("catalog_number", sa.String(50), nullable=False),
        sa.Column("file_notation", sa.String(20), nullable=True),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("start_date", sa.String(10), nullable=False),
        sa.Column("end_date", sa.String(10), nullable=False),
        sa.Column("start_year", sa.Integer(), nullable=False),
        sa.Column("maintenance_code", sa.String(2), nullable=False),
        sa.Column("sheet_count", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(100), nullable=True),
        sa.Column("bad_paper", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.Column("missing_from_import_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["project_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["import_id"], ["arrangement_imports.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["missing_from_import_id"], ["arrangement_imports.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "box_number", "dossier_number", "dossier_suffix",
            name="uq_arrangement_dossiers_key",
        ),
        sa.CheckConstraint(
            "box_number >= 1 AND dossier_number >= 1 AND sheet_count >= 1",
            name="ck_arrangement_dossiers_numbers",
        ),
    )
    op.create_index("ix_arrangement_dossiers_project_id", "arrangement_dossiers", ["project_id"])
    op.create_index("ix_arrangement_dossiers_case_id", "arrangement_dossiers", ["case_id"])
    op.create_index("ix_arrangement_dossiers_import_id", "arrangement_dossiers", ["import_id"])
    op.create_index(
        "ix_arrangement_dossiers_missing_from_import_id",
        "arrangement_dossiers",
        ["missing_from_import_id"],
    )


def downgrade() -> None:
    op.drop_table("arrangement_dossiers")
    op.drop_table("arrangement_imports")
