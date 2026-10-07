"""R2: chuỗi migration mới sinh được SQL PostgreSQL mà không cần máy chủ PostgreSQL.

Alembic offline mode (sql=True) không có kết nối nên migration nào đọc dữ liệu
qua op.get_bind() không chạy được: 0001, 0003, 0004, 0010. Vì vậy chỉ kiểm từ
0010_case_input_assignment lên head, phần cần cho đợt triển khai 0011 trở đi.
"""

import dataclasses
import io
from pathlib import Path
import re

import pytest

import server.settings
from server.migration_runner import HEAD_REVISION


ROOT = Path(__file__).resolve().parents[1]
OFFLINE_BASE = "0010_case_input_assignment"
POSTGRES_URL = "postgresql+psycopg://offline@localhost/offline"


@pytest.fixture()
def offline_sql(monkeypatch):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    # migrations/env.py lấy URL từ server.settings.settings: trỏ sang dialect PostgreSQL.
    monkeypatch.setattr(
        server.settings,
        "settings",
        dataclasses.replace(server.settings.settings, database_url=POSTGRES_URL),
    )

    def generate(action, revision_range):
        buffer = io.StringIO()
        config = Config(str(ROOT / "alembic.ini"), output_buffer=buffer)
        config.set_main_option("script_location", str(ROOT / "migrations"))
        getattr(command, action)(config, revision_range, sql=True)
        return buffer.getvalue()

    return generate


def test_upgrade_to_head_generates_postgres_sql(offline_sql):
    sql = offline_sql("upgrade", f"{OFFLINE_BASE}:head")

    assert "CREATE TABLE case_scan_packages" in sql
    assert "CREATE TABLE case_scan_files" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX uq_case_scan_packages_active_case ON case_scan_packages "
        r"\(case_id\) WHERE status = 'processing'",
        sql,
    )
    assert "ALTER TABLE case_scan_packages ADD COLUMN match_status VARCHAR(20)" in sql
    assert "ALTER TABLE case_scan_packages ADD COLUMN match_summary TEXT" in sql
    assert "CREATE TABLE case_entry_qc_results" in sql
    assert "ALTER TABLE case_entry_qc_results ADD COLUMN resolution VARCHAR(20)" in sql
    assert "ADD CONSTRAINT ck_entry_qc_resolution CHECK (resolution = 'approved')" in sql
    assert "CREATE TABLE case_entry_qc_samplings" in sql
    assert "CREATE TABLE case_entry_qc_sample_items" in sql
    assert "ALTER TABLE project_policies ADD COLUMN entry_qc_round2_enabled BOOLEAN" in sql
    assert "CONSTRAINT chk_sampling_round_2 CHECK (round = 2)" in sql
    # Dialect PostgreSQL thật, không phải SQLite.
    assert "TIMESTAMP WITHOUT TIME ZONE" in sql
    assert f"version_num='{HEAD_REVISION}'" in sql


def test_upgrade_sql_has_no_sqlite_only_syntax(offline_sql):
    sql = offline_sql("upgrade", f"{OFFLINE_BASE}:head")

    for sqlite_only in ("PRAGMA", "AUTOINCREMENT", "_alembic_tmp_", "sqlite_"):
        assert sqlite_only not in sql


def test_downgrade_from_head_generates_postgres_sql(offline_sql):
    sql = offline_sql("downgrade", f"head:{OFFLINE_BASE}")

    assert "DROP TABLE case_scan_files" in sql
    assert "DROP TABLE case_scan_packages" in sql
    assert "DROP TABLE case_entry_qc_results" in sql
    assert "DROP CONSTRAINT ck_entry_qc_resolution" in sql
    assert "DROP TABLE case_entry_qc_sample_items" in sql
    assert "DROP TABLE case_entry_qc_samplings" in sql
    assert "ALTER TABLE project_policies DROP COLUMN entry_qc_round2_enabled" in sql
    assert f"version_num='{OFFLINE_BASE}'" in sql
