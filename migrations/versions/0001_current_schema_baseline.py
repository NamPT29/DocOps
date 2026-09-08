"""Current PostgreSQL schema baseline.

Revision ID: 0001_current_schema
Revises: None
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from migrations.schema_0001 import build_metadata


revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names()) - {"alembic_version"}
    if existing:
        raise RuntimeError(
            "Revision 0001 only creates a new database. "
            "Validate and stamp an existing database with "
            "scripts/migrate_database.py --adopt-existing."
        )
    build_metadata().create_all(bind=bind)


def downgrade() -> None:
    build_metadata().drop_all(bind=op.get_bind())
