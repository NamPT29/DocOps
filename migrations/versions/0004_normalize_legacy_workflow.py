"""Normalize legacy profile and workflow values once.

Revision ID: 0004_normalize_legacy_workflow
Revises: 0003_submission_metadata

The SQL is frozen here so request handling and server imports never mutate
the database schema or perform compatibility backfills.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0004_normalize_legacy_workflow"
down_revision = "0003_submission_metadata"
branch_labels = None
depends_on = None


def _normalize_legacy_values(bind) -> None:
    bind.execute(text(
        "UPDATE users SET full_name = username "
        "WHERE full_name IS NULL OR TRIM(full_name) = ''"
    ))
    bind.execute(text(
        "UPDATE users SET max_concurrent_sessions = 1 "
        "WHERE max_concurrent_sessions IS NULL OR max_concurrent_sessions < 1"
    ))

    bind.execute(text(
        "UPDATE projects SET status = CASE status "
        "WHEN 'configuring' THEN 'new' "
        "WHEN 'importing' THEN 'in_progress' "
        "WHEN 'ready' THEN 'in_progress' "
        "WHEN 'new' THEN 'new' "
        "WHEN 'in_progress' THEN 'in_progress' "
        "WHEN 'completed' THEN 'completed' "
        "WHEN 'overdue' THEN 'overdue' "
        "ELSE 'new' END "
        "WHERE status IS NULL OR status NOT IN "
        "('new', 'in_progress', 'completed', 'overdue')"
    ))

    bind.execute(text(
        "UPDATE submissions SET status = 'pending_review' "
        "WHERE status = 'rejected'"
    ))
    bind.execute(text(
        "UPDATE submissions SET status = CASE "
        "WHEN EXISTS ("
        "SELECT 1 FROM submission_review_histories history "
        "WHERE history.submission_id = submissions.id "
        "AND history.event_type IN "
        "('input_confirmed', 'input_corrected', 'input_correction')"
        ") THEN 'completed' "
        "ELSE 'pending_input_confirmation' END "
        "WHERE status = 'approved'"
    ))

    if bind.dialect.name == "postgresql":
        bind.execute(text(
            "ALTER TABLE users ALTER COLUMN full_name SET NOT NULL"
        ))


def upgrade() -> None:
    _normalize_legacy_values(op.get_bind())


def downgrade() -> None:
    # Normalized values cannot be distinguished from values written normally.
    pass
