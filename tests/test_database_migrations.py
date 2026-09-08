from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

from migrations.schema_0001 import SCHEMA, SCHEMA_SHA256, build_metadata
from scripts.generate_migration_schema_snapshot import build_snapshot
from server.migration_runner import (
    HEAD_REVISION,
    current_database_revision,
    migration_state,
    upgrade_database,
    validate_existing_database,
)


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_baseline_snapshot_is_reproducible():
    current = build_snapshot()
    canonical = json.dumps(current, ensure_ascii=False, sort_keys=True)

    assert current == SCHEMA
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == SCHEMA_SHA256


def test_server_import_path_contains_no_schema_mutation():
    source = (ROOT / "server" / "main.py").read_text(encoding="utf-8")

    forbidden = (
        "metadata.create_all",
        "ensure_submission_view_schema(",
        "ensure_user_profile_schema(",
        "ensure_auth_session_schema(",
        "ensure_submission_metadata_schema(",
        "ensure_project_status_schema(",
        "ensure_submission_status_schema(",
        "ensure_performance_indexes(",
        "backfill_submission_metadata(",
    )
    assert all(item not in source for item in forbidden)


def test_existing_schema_requires_explicit_adoption():
    pytest.importorskip("alembic")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    build_metadata().create_all(engine)

    with pytest.raises(RuntimeError, match="--adopt-existing"):
        upgrade_database(engine, base_dir=ROOT)

    result = upgrade_database(engine, base_dir=ROOT, adopt_existing=True)

    assert result.adopted_existing is True
    assert result.current == HEAD_REVISION
    assert migration_state(engine).ready is True
    with engine.connect() as connection:
        assert current_database_revision(connection) == HEAD_REVISION


def test_fresh_database_upgrades_to_versioned_baseline():
    pytest.importorskip("alembic")
    engine = create_engine("sqlite+pysqlite:///:memory:")

    result = upgrade_database(engine, base_dir=ROOT)

    assert result.previous is None
    assert result.adopted_existing is False
    assert result.current == HEAD_REVISION
    with engine.connect() as connection:
        assert validate_existing_database(connection) == []
    assert "submissions" in inspect(engine).get_table_names()


def test_validation_rejects_incomplete_existing_schema():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    with engine.connect() as connection:
        differences = validate_existing_database(connection)

    assert "missing column: users.username" in differences
    assert "missing table: submissions" in differences


def test_validation_rejects_missing_constraints_and_wrong_index_shape():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    build_metadata().create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_submissions_template_id")
        connection.exec_driver_sql(
            "CREATE INDEX ix_submissions_template_id "
            "ON submissions (created_at)"
        )
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql(
            "ALTER TABLE user_login_sessions "
            "RENAME TO original_user_login_sessions"
        )
        connection.exec_driver_sql(
            "CREATE TABLE user_login_sessions AS "
            "SELECT * FROM original_user_login_sessions WHERE 0"
        )

    with engine.connect() as connection:
        differences = validate_existing_database(connection)

    assert "index mismatch: submissions.ix_submissions_template_id" in differences
    assert any(
        item.startswith("missing unique constraint: user_login_sessions(")
        for item in differences
    )
    assert any(
        item.startswith("missing foreign key: user_login_sessions.user_id")
        for item in differences
    )


def test_baseline_revision_upgrade_and_downgrade_without_importing_models(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    connection = engine.connect()
    fake_op = SimpleNamespace(get_bind=lambda: connection)
    monkeypatch.setitem(sys.modules, "alembic", SimpleNamespace(op=fake_op))
    revision_path = (
        ROOT
        / "migrations"
        / "versions"
        / "0001_current_schema_baseline.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0001_test",
        revision_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    module.upgrade()
    assert "submissions" in inspect(connection).get_table_names()
    module.downgrade()
    assert inspect(connection).get_table_names() == []
    connection.close()


def test_second_revision_adds_and_removes_confirmation_foreign_key(monkeypatch):
    calls = []

    class FakeBatchOperation:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def create_foreign_key(self, *args):
            calls.append(("create", args))

        def drop_constraint(self, *args, **kwargs):
            calls.append(("drop", args, kwargs))

    fake_op = SimpleNamespace(
        batch_alter_table=lambda table_name: (
            calls.append(("table", table_name)) or FakeBatchOperation()
        )
    )
    monkeypatch.setitem(sys.modules, "alembic", SimpleNamespace(op=fake_op))
    revision_path = (
        ROOT
        / "migrations"
        / "versions"
        / "0002_review_confirmation_fk.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0002_test",
        revision_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.down_revision == "0001_current_schema"
    module.upgrade()
    module.downgrade()

    assert calls == [
        ("table", "submission_review_histories"),
        (
            "create",
            (
                module.CONSTRAINT_NAME,
                "users",
                ["confirmed_by_user_id"],
                ["id"],
            ),
        ),
        ("table", "submission_review_histories"),
        (
            "drop",
            (module.CONSTRAINT_NAME,),
            {"type_": "foreignkey"},
        ),
    ]


def _load_metadata_backfill_revision(monkeypatch, connection):
    fake_op = SimpleNamespace(get_bind=lambda: connection)
    monkeypatch.setitem(sys.modules, "alembic", SimpleNamespace(op=fake_op))
    revision_path = (
        ROOT
        / "migrations"
        / "versions"
        / "0003_backfill_submission_metadata.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0003_test",
        revision_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_metadata_backfill_revision_is_frozen_and_versioned():
    source = (
        ROOT
        / "migrations"
        / "versions"
        / "0003_backfill_submission_metadata.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0003_submission_metadata"' in source
    assert 'down_revision = "0002_review_confirmation_fk"' in source
    assert "from server" not in source
    assert "import server" not in source


def test_metadata_backfill_revision_preserves_values_and_is_idempotent(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE assigned_documents (
                id INTEGER PRIMARY KEY,
                original_filename VARCHAR(255),
                uuid_filename VARCHAR(255),
                assigned_to_user_id INTEGER,
                created_at DATETIME
            )
        """))
        connection.execute(text("""
            CREATE TABLE assigned_document_folders (
                id INTEGER PRIMARY KEY,
                document_id INTEGER,
                folder_group VARCHAR(1024)
            )
        """))
        connection.execute(text("""
            CREATE TABLE submissions (
                id INTEGER PRIMARY KEY,
                data_json TEXT NOT NULL,
                created_by_user_id INTEGER,
                status VARCHAR(50),
                assigned_document_id INTEGER,
                folder_path VARCHAR(1024),
                folder_path_key VARCHAR(64)
            )
        """))
        connection.execute(text("""
            INSERT INTO assigned_documents VALUES
              (10, 'same.pdf', 'old-uuid.pdf', 7, '2026-08-13 01:00:00'),
              (11, 'same.pdf', 'new-uuid.pdf', 7, '2026-08-14 01:00:00')
        """))
        connection.execute(text("""
            INSERT INTO assigned_document_folders VALUES
              (20, 10, 'old\\folder'),
              (21, 11, '/new/folder/')
        """))
        original_json = {
            1: '{  "col_8": "uuid", "_pdf_uuid": "dir/new-uuid.pdf"  }',
            2: '{"col_8":"filename","_pdf_filename":"same.pdf"}',
            3: json.dumps({
                "col_8": "fallback",
                "_folder_path": "\\fallback\\path\\",
            }),
            4: '{"col_8":"already indexed"}',
        }
        for submission_id, data_json in original_json.items():
            connection.execute(text("""
                INSERT INTO submissions VALUES (
                    :id, :data_json, 7, :status, :document_id,
                    :folder_path, :folder_path_key
                )
            """), {
                "id": submission_id,
                "data_json": data_json,
                "status": "completed" if submission_id == 4 else "draft",
                "document_id": 99 if submission_id == 4 else None,
                "folder_path": "kept" if submission_id == 4 else None,
                "folder_path_key": "already-set" if submission_id == 4 else None,
            })

        module = _load_metadata_backfill_revision(monkeypatch, connection)
        assert module.down_revision == "0002_review_confirmation_fk"
        assert module._backfill(connection, batch_size=1) == 3
        assert module._backfill(connection, batch_size=1) == 0

        rows = connection.execute(text("""
            SELECT id, data_json, status, assigned_document_id,
                   folder_path, folder_path_key
            FROM submissions ORDER BY id
        """)).mappings().all()

    assert {row["id"]: row["data_json"] for row in rows} == original_json
    assert rows[0]["assigned_document_id"] == 11
    assert rows[0]["folder_path"] == "new/folder"
    assert rows[0]["folder_path_key"] == module._folder_path_key("new/folder")
    assert rows[1]["assigned_document_id"] == 11
    assert rows[2]["assigned_document_id"] is None
    assert rows[2]["folder_path"] == "fallback/path"
    assert rows[2]["folder_path_key"] == module._folder_path_key("fallback/path")
    assert rows[3]["status"] == "completed"
    assert rows[3]["assigned_document_id"] == 99
    assert rows[3]["folder_path_key"] == "already-set"


def _load_legacy_workflow_revision(monkeypatch, connection):
    fake_op = SimpleNamespace(get_bind=lambda: connection)
    monkeypatch.setitem(sys.modules, "alembic", SimpleNamespace(op=fake_op))
    revision_path = (
        ROOT
        / "migrations"
        / "versions"
        / "0004_normalize_legacy_workflow.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0004_test",
        revision_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_legacy_workflow_revision_is_frozen_and_versioned(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        module = _load_legacy_workflow_revision(monkeypatch, connection)

    assert HEAD_REVISION == "0004_normalize_legacy_workflow"
    assert module.revision == HEAD_REVISION
    assert module.down_revision == "0003_submission_metadata"
    source = (
        ROOT
        / "migrations"
        / "versions"
        / "0004_normalize_legacy_workflow.py"
    ).read_text(encoding="utf-8")
    assert "from server" not in source
    assert "import server" not in source


def test_legacy_workflow_revision_normalizes_values_idempotently(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                full_name VARCHAR(255),
                max_concurrent_sessions INTEGER
            )
        """))
        connection.execute(text("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                status VARCHAR(32)
            )
        """))
        connection.execute(text("""
            CREATE TABLE submissions (
                id INTEGER PRIMARY KEY,
                status VARCHAR(50)
            )
        """))
        connection.execute(text("""
            CREATE TABLE submission_review_histories (
                id INTEGER PRIMARY KEY,
                submission_id INTEGER NOT NULL,
                event_type VARCHAR(32) NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO users VALUES
              (1, 'legacy-user', NULL, 0),
              (2, 'valid-user', 'Valid User', 3)
        """))
        connection.execute(text("""
            INSERT INTO projects VALUES
              (1, 'configuring'),
              (2, 'importing'),
              (3, 'ready'),
              (4, 'unknown'),
              (5, 'completed')
        """))
        connection.execute(text("""
            INSERT INTO submissions VALUES
              (1, 'rejected'),
              (2, 'approved'),
              (3, 'approved'),
              (4, 'draft')
        """))
        connection.execute(text("""
            INSERT INTO submission_review_histories VALUES
              (1, 3, 'input_corrected')
        """))

        module = _load_legacy_workflow_revision(monkeypatch, connection)
        module._normalize_legacy_values(connection)
        module._normalize_legacy_values(connection)

        users = connection.execute(text(
            "SELECT id, full_name, max_concurrent_sessions FROM users ORDER BY id"
        )).all()
        projects = connection.execute(text(
            "SELECT id, status FROM projects ORDER BY id"
        )).all()
        submissions = connection.execute(text(
            "SELECT id, status FROM submissions ORDER BY id"
        )).all()

    assert users == [(1, "legacy-user", 1), (2, "Valid User", 3)]
    assert projects == [
        (1, "new"),
        (2, "in_progress"),
        (3, "in_progress"),
        (4, "new"),
        (5, "completed"),
    ]
    assert submissions == [
        (1, "pending_review"),
        (2, "pending_input_confirmation"),
        (3, "completed"),
        (4, "draft"),
    ]


def test_request_paths_do_not_call_submission_metadata_backfill():
    request_paths = [
        ROOT / "server" / "routers",
        ROOT / "server" / "services",
    ]
    offenders = []
    for directory in request_paths:
        for path in directory.glob("*.py"):
            if "backfill_submission_metadata" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
