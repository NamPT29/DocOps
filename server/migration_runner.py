"""Alembic execution and safe adoption of pre-Alembic databases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    inspect,
    text,
)
from sqlalchemy.engine import Connection, Engine

from migrations.schema_0001 import SCHEMA


BASELINE_REVISION = "0001_current_schema"
HEAD_REVISION = "0004_normalize_legacy_workflow"
_POSTGRES_MIGRATION_LOCK_ID = 761_004_001


@dataclass(frozen=True)
class MigrationState:
    current: str | None
    expected: str
    ready: bool


@dataclass(frozen=True)
class MigrationResult:
    previous: str | None
    current: str
    adopted_existing: bool


def current_database_revision(connection: Connection) -> str | None:
    if "alembic_version" not in set(inspect(connection).get_table_names()):
        return None
    row = connection.execute(text(
        "SELECT version_num FROM alembic_version LIMIT 1"
    )).first()
    return str(row[0]) if row and row[0] else None


def migration_state(engine: Engine) -> MigrationState:
    with engine.connect() as connection:
        current = current_database_revision(connection)
    return MigrationState(
        current=current,
        expected=HEAD_REVISION,
        ready=current == HEAD_REVISION,
    )


def _column_type_matches(actual_type, expected: dict) -> bool:
    name = expected["name"]
    if name == "big_integer":
        return isinstance(actual_type, BigInteger)
    if name == "integer":
        return isinstance(actual_type, Integer) and not isinstance(
            actual_type,
            BigInteger,
        )
    if name == "text":
        return isinstance(actual_type, (Text, String)) and getattr(
            actual_type,
            "length",
            None,
        ) is None
    if name == "string":
        if not isinstance(actual_type, String) or isinstance(actual_type, Text):
            return False
        expected_length = expected.get("length")
        actual_length = getattr(actual_type, "length", None)
        return expected_length is None or actual_length == expected_length
    if name == "datetime":
        return isinstance(actual_type, DateTime)
    if name == "boolean":
        return isinstance(actual_type, Boolean)
    return False


def validate_existing_database(connection: Connection) -> list[str]:
    """Return structural differences that make baseline stamping unsafe."""
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names())
    errors: list[str] = []

    for table_spec in SCHEMA["tables"]:
        table_name = table_spec["name"]
        if table_name not in actual_tables:
            errors.append(f"missing table: {table_name}")
            continue

        actual_columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        for column_spec in table_spec["columns"]:
            column_name = column_spec["name"]
            if column_name not in actual_columns:
                errors.append(f"missing column: {table_name}.{column_name}")
                continue
            if not _column_type_matches(
                actual_columns[column_name]["type"],
                column_spec["type"],
            ):
                errors.append(f"type mismatch: {table_name}.{column_name}")
            if (
                not column_spec["nullable"]
                and actual_columns[column_name].get("nullable", True)
                and not column_spec["primary_key"]
            ):
                errors.append(f"nullable column: {table_name}.{column_name}")

        expected_primary_key = {
            column["name"]
            for column in table_spec["columns"]
            if column["primary_key"]
        }
        actual_primary_key = set(
            inspector.get_pk_constraint(table_name).get(
                "constrained_columns",
                [],
            )
        )
        if actual_primary_key != expected_primary_key:
            errors.append(f"primary key mismatch: {table_name}")

        actual_indexes = {
            index.get("name"): index
            for index in inspector.get_indexes(table_name)
            if index.get("name")
        }
        for index_spec in table_spec["indexes"]:
            actual_index = actual_indexes.get(index_spec["name"])
            if actual_index is None:
                errors.append(
                    f"missing index: {table_name}.{index_spec['name']}"
                )
                continue
            if list(actual_index.get("column_names") or []) != list(
                index_spec["columns"]
            ) or bool(actual_index.get("unique")) != bool(
                index_spec["unique"]
            ):
                errors.append(
                    f"index mismatch: {table_name}.{index_spec['name']}"
                )

        expected_unique_constraints = {
            tuple(constraint["columns"])
            for constraint in table_spec["constraints"]
            if constraint["kind"] == "unique"
        }
        actual_unique_constraints = {
            tuple(constraint.get("column_names") or [])
            for constraint in inspector.get_unique_constraints(table_name)
        }
        for columns in sorted(
            expected_unique_constraints - actual_unique_constraints
        ):
            errors.append(
                f"missing unique constraint: {table_name}({', '.join(columns)})"
            )

        expected_checks = {
            constraint["name"]
            for constraint in table_spec["constraints"]
            if constraint["kind"] == "check" and constraint.get("name")
        }
        actual_checks = {
            constraint.get("name")
            for constraint in inspector.get_check_constraints(table_name)
            if constraint.get("name")
        }
        for constraint_name in sorted(expected_checks - actual_checks):
            errors.append(
                f"missing check constraint: {table_name}.{constraint_name}"
            )

        expected_foreign_keys = {
            (
                column_spec["name"],
                foreign_key["target"],
                (foreign_key.get("ondelete") or "").upper(),
            )
            for column_spec in table_spec["columns"]
            for foreign_key in column_spec["foreign_keys"]
        }
        actual_foreign_keys = set()
        for foreign_key in inspector.get_foreign_keys(table_name):
            constrained_columns = foreign_key.get("constrained_columns") or []
            referred_columns = foreign_key.get("referred_columns") or []
            if len(constrained_columns) != 1 or len(referred_columns) != 1:
                continue
            target = (
                f"{foreign_key['referred_table']}.{referred_columns[0]}"
            )
            actual_foreign_keys.add((
                constrained_columns[0],
                target,
                (
                    (foreign_key.get("options") or {}).get("ondelete") or ""
                ).upper(),
            ))
        for column_name, target, ondelete in sorted(
            expected_foreign_keys - actual_foreign_keys
        ):
            suffix = f" on delete {ondelete}" if ondelete else ""
            errors.append(
                f"missing foreign key: {table_name}.{column_name} -> "
                f"{target}{suffix}"
            )
    return errors


def _alembic_config(base_dir: Path):
    from alembic.config import Config

    config_path = base_dir / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("script_location", str(base_dir / "migrations"))
    return config


def _lock_migrations(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _POSTGRES_MIGRATION_LOCK_ID},
        )


def upgrade_database(
    engine: Engine,
    *,
    base_dir: Path,
    adopt_existing: bool = False,
) -> MigrationResult:
    """Upgrade to head using one connection and one PostgreSQL advisory lock."""
    from alembic import command

    config = _alembic_config(base_dir)
    with engine.begin() as connection:
        _lock_migrations(connection)
        config.attributes["connection"] = connection
        previous = current_database_revision(connection)
        application_tables = set(inspect(connection).get_table_names()) - {
            "alembic_version"
        }
        adopted = False
        if previous is None and application_tables:
            if not adopt_existing:
                raise RuntimeError(
                    "Database đã có dữ liệu nhưng chưa có alembic_version. "
                    "Chạy scripts/migrate_database.py --adopt-existing sau khi backup."
                )
            differences = validate_existing_database(connection)
            if differences:
                preview = "; ".join(differences[:10])
                suffix = "" if len(differences) <= 10 else " ..."
                raise RuntimeError(
                    "Không thể stamp baseline vì schema chưa khớp: "
                    f"{preview}{suffix}"
                )
            command.stamp(config, BASELINE_REVISION)
            adopted = True

        command.upgrade(config, "head")
        current = current_database_revision(connection)
        if current != HEAD_REVISION:
            raise RuntimeError(
                f"Migration kết thúc ở {current!r}, cần {HEAD_REVISION!r}."
            )
        return MigrationResult(
            previous=previous,
            current=current,
            adopted_existing=adopted,
        )
