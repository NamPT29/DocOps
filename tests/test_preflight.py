"""R1: scripts/preflight.py chỉ đọc, báo đúng lỗi và không lộ mật khẩu."""

from pathlib import Path
import socket
import sys

import pytest
from sqlalchemy import create_engine, text

from scripts import preflight
from server.migration_runner import HEAD_REVISION, upgrade_database


ROOT = Path(__file__).resolve().parents[1]
SECRET = "k" * 48


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def environment(tmp_path):
    pytest.importorskip("alembic")
    database = tmp_path / "preflight.db"
    url = f"sqlite+pysqlite:///{database}"
    engine = create_engine(url)
    upgrade_database(engine, base_dir=ROOT)
    engine.dispose()
    documents = tmp_path / "source_documents"
    documents.mkdir()
    return {
        "DATABASE_URL": url,
        "SECRET_KEY": SECRET,
        "DOCUMENT_SOURCE_ROOT": str(documents),
        "PORT": str(_free_port()),
    }


def _run(environ, env_file=None):
    return {check.name: check for check in preflight.run_checks(environ, env_file)}


def _failures(checks):
    return [check for check in checks.values() if check.status == preflight.FAIL]


def test_ready_machine_passes(environment, tmp_path, capsys):
    checks = _run(environment)

    assert _failures(checks) == []
    assert checks["Migration"].status == preflight.PASS
    assert checks["Migration"].detail == HEAD_REVISION
    assert preflight.main(["--env-file", str(tmp_path / "none.env")], environment) == 0
    assert "KẾT QUẢ PREFLIGHT: ĐẠT" in capsys.readouterr().out


def test_missing_pypdf_fails(environment, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)

    checks = _run(environment)

    assert checks["pypdf"].status == preflight.FAIL


def test_missing_database_url_never_connects(environment, monkeypatch, tmp_path, capsys):
    environment.pop("DATABASE_URL")

    def refuse(*_args, **_kwargs):
        raise AssertionError("preflight must not connect without DATABASE_URL")

    monkeypatch.setattr(preflight, "create_engine", refuse)
    checks = _run(environment, tmp_path / "none.env")

    assert checks["DATABASE_URL"].status == preflight.FAIL
    assert "Kết nối CSDL" not in checks
    assert preflight.main(["--env-file", str(tmp_path / "none.env")], environment) == 1
    assert "KẾT QUẢ PREFLIGHT: KHÔNG ĐẠT" in capsys.readouterr().out


def test_env_file_fills_missing_values_but_environment_wins(environment, tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text(
        f"DATABASE_URL={environment['DATABASE_URL']}\nSECRET_KEY=short\n",
        encoding="utf-8",
    )
    environment.pop("DATABASE_URL")

    checks = _run(environment, env_file)

    assert checks["Kết nối CSDL"].status == preflight.PASS
    assert checks["SECRET_KEY"].status == preflight.PASS


def test_short_secret_key_fails(environment):
    environment["SECRET_KEY"] = "short"

    assert _run(environment)["SECRET_KEY"].status == preflight.FAIL


def test_missing_document_root_fails(environment, tmp_path):
    environment["DOCUMENT_SOURCE_ROOT"] = str(tmp_path / "missing")

    checks = _run(environment)

    assert checks["DOCUMENT_SOURCE_ROOT"].status == preflight.FAIL
    assert "Dung lượng trống" not in checks


def test_older_migration_warns_to_back_up(environment):
    engine = create_engine(environment["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0012_scan_catalog_match'"))
    engine.dispose()

    check = _run(environment)["Migration"]

    assert check.status == preflight.WARN
    assert "0012_scan_catalog_match" in check.detail
    assert "pg_dump" in check.detail


def test_unknown_migration_fails(environment):
    engine = create_engine(environment["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999_from_the_future'"))
    engine.dispose()

    assert _run(environment)["Migration"].status == preflight.FAIL


def test_database_password_is_never_printed(environment, tmp_path, capsys):
    environment["DATABASE_URL"] = "postgresql+psycopg://docops:SieuBiMat123@127.0.0.1:1/docops"

    code = preflight.main(["--env-file", str(tmp_path / "none.env")], environment)

    output = capsys.readouterr().out
    assert code == 1
    assert "[LỖI] Kết nối CSDL" in output
    assert "SieuBiMat123" not in output
    assert SECRET not in output


def test_masked_url_hides_password():
    masked = preflight._masked_url("postgresql+psycopg://docops:SieuBiMat123@db.local:5432/docops")

    assert "SieuBiMat123" not in masked
    assert "docops:***@db.local" in masked


def test_error_text_is_scrubbed_of_secrets():
    message = "password authentication failed: SieuBiMat123\nDETAIL: SieuBiMat123"

    assert preflight._scrub(message, ["SieuBiMat123"]) == "password authentication failed: ***"


def test_port_in_use_warns(environment):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        environment["PORT"] = str(server.getsockname()[1])

        assert _run(environment)["Cổng"].status == preflight.WARN
