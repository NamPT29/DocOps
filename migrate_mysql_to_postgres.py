"""Copy the legacy MariaDB data into the PostgreSQL database configured in .env.

The source is read through a separate connection. The target is truncated and
reloaded inside one PostgreSQL transaction; a failure rolls the target back.
"""

from __future__ import annotations

import argparse
from typing import Iterable

import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv
import os


TABLE_ORDER = (
    "users",
    "user_capabilities",
    "templates",
    "dictionaries",
    "dictionary_items",
    "assigned_documents",
    "assigned_document_paths",
    "assigned_document_folders",
    "assigned_document_review_assignments",
    "server_folder_import_jobs",
    "server_folder_import_reviewers",
    "submissions",
    "submission_review_assignments",
    "notifications",
    "notification_recipients",
    "tasks",
    "submission_view_presence",
)

BOOLEAN_COLUMNS = {"is_active", "is_checked", "can_input", "can_review"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-host", default="127.0.0.1")
    parser.add_argument("--source-port", type=int, default=3307)
    parser.add_argument("--source-user", default="root")
    parser.add_argument("--source-password", default="")
    parser.add_argument("--source-database", default="scan_data")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def source_tables(connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        return {next(iter(row.values())) for row in cursor.fetchall()}


def source_rows(connection, table_name: str, columns: list[str], batch_size: int = 1000) -> Iterable[list[dict]]:
    quoted = ", ".join(f"`{column}`" for column in columns)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {quoted} FROM `{table_name}`")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                return
            yield rows


def normalize_row(table_name: str, row: dict) -> dict:
    normalized = dict(row)
    for column in BOOLEAN_COLUMNS:
        if column in normalized and normalized[column] is not None:
            normalized[column] = bool(normalized[column])
    return normalized


def reset_sequences(connection, metadata: MetaData) -> None:
    inspector = inspect(connection)
    for table_name in TABLE_ORDER:
        if table_name not in metadata.tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "id" not in columns:
            continue
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table_name},
        ).scalar()
        if not sequence:
            continue
        connection.execute(
            text(
                "SELECT setval(:sequence_name, "
                "COALESCE((SELECT MAX(id) FROM \"" + table_name + "\"), 1), "
                "COALESCE((SELECT MAX(id) FROM \"" + table_name + "\"), 0) > 0)"
            ),
            {"sequence_name": sequence},
        )


def migrate(args: argparse.Namespace) -> None:
    load_dotenv()
    target_url = os.environ["DATABASE_URL"]
    source = pymysql.connect(
        host=args.source_host,
        port=args.source_port,
        user=args.source_user,
        password=args.source_password,
        database=args.source_database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    target_engine: Engine = create_engine(target_url, pool_pre_ping=True)
    try:
        available = source_tables(source)
        missing = [table for table in TABLE_ORDER if table not in available]
        if missing:
            raise RuntimeError(f"Nguồn thiếu bảng: {', '.join(missing)}")

        metadata = MetaData()
        metadata.reflect(bind=target_engine, only=list(TABLE_ORDER))
        target_columns = {
            table: [column.name for column in metadata.tables[table].columns]
            for table in TABLE_ORDER
        }
        counts = {}
        for table in TABLE_ORDER:
            with source.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = next(iter(cursor.fetchone().values()))
        with source.cursor() as cursor:
            cursor.execute("SELECT id FROM submissions")
            valid_submission_ids = {row["id"] for row in cursor.fetchall()}
            cursor.execute("SELECT id FROM users")
            valid_user_ids = {row["id"] for row in cursor.fetchall()}
        print("SOURCE_COUNTS", counts)
        if args.dry_run:
            return

        with target_engine.begin() as connection:
            quoted_tables = ", ".join(f'"{table}"' for table in TABLE_ORDER)
            connection.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))
            for table_name in TABLE_ORDER:
                target_table: Table = metadata.tables[table_name]
                columns = target_columns[table_name]
                inserted = 0
                skipped = 0
                for batch in source_rows(source, table_name, columns):
                    rows = [normalize_row(table_name, row) for row in batch]
                    if table_name == "submission_view_presence":
                        before_filter = len(rows)
                        rows = [
                            row
                            for row in rows
                            if row["submission_id"] in valid_submission_ids
                            and row["viewer_user_id"] in valid_user_ids
                        ]
                        skipped += before_filter - len(rows)
                    if not rows:
                        continue
                    connection.execute(target_table.insert(), rows)
                    inserted += len(rows)
                print("MIGRATED", table_name, inserted)
                if skipped:
                    print("SKIPPED_ORPHANS", table_name, skipped)
            reset_sequences(connection, metadata)
    finally:
        source.close()
        target_engine.dispose()


if __name__ == "__main__":
    migrate(parse_args())
