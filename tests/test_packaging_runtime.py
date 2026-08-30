from pathlib import Path

import pytest

from dotenv import dotenv_values

import app_launcher
from server.host_runtime_paths import HostRuntimePaths
from wizard import build_host_environment


def test_frozen_resource_root_uses_pyinstaller_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(app_launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_launcher.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert app_launcher.get_resource_root() == tmp_path


def test_bind_runtime_paths_uses_absolute_persistent_directories(tmp_path):
    paths = HostRuntimePaths(tmp_path / "host-data")
    environment = {"PDF_STORAGE_PATH": "unsafe-relative-path"}

    app_launcher.bind_runtime_paths(paths, environment)

    assert environment["PDF_STORAGE_PATH"] == str(paths.uploads_dir.resolve())
    assert environment["TEMPLATE_STORAGE_PATH"] == str(paths.templates_dir.resolve())
    assert environment["DOCUMENT_SOURCE_ROOT"] == str(
        paths.source_documents_dir.resolve()
    )
    assert environment["EXPORT_WORK_DIR"] == str(paths.exports_dir.resolve())
    assert environment["LOG_DIR"] == str(paths.logs_dir.resolve())


def test_first_packaged_run_creates_and_loads_host_environment(monkeypatch, tmp_path):
    data_root = tmp_path / "persistent-host"
    monkeypatch.setattr(app_launcher.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SCAN_TO_EXCEL_DATA_DIR", str(data_root))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def fake_wizard(env_path, paths):
        Path(env_path).write_text(
            "DATABASE_URL='postgresql+psycopg://user:pass@127.0.0.1/db'\n",
            encoding="utf-8",
        )
        return paths.config_path.exists()

    monkeypatch.setattr(app_launcher, "run_setup_wizard", fake_wizard)

    paths = app_launcher.prepare_runtime_environment()

    assert paths == HostRuntimePaths(data_root)
    assert paths.config_path.exists()
    assert app_launcher.os.environ["DATABASE_URL"].endswith("@127.0.0.1/db")
    assert app_launcher.os.environ["PDF_STORAGE_PATH"] == str(
        paths.uploads_dir.resolve()
    )


def test_host_environment_uses_external_postgres_and_escapes_credentials(tmp_path):
    paths = HostRuntimePaths(tmp_path / "host-data")

    content = build_host_environment(
        paths=paths,
        database_host="127.0.0.1",
        database_port=5432,
        database_name="scan_data",
        database_user="scan user",
        database_password="p@ss:/# word",
        admin_password="Admin password #1",
        web_port=8000,
    )
    env_path = tmp_path / "host.env"
    env_path.write_text(content, encoding="utf-8")
    values = dotenv_values(env_path)

    assert values["DATABASE_URL"] == (
        "postgresql+psycopg://scan%20user:p%40ss%3A%2F%23%20word"
        "@127.0.0.1:5432/scan_data"
    )
    assert values["INITIAL_ADMIN_PASSWORD"] == "Admin password #1"
    assert values["PUBLIC_HOSTNAME"] == "nhaplieu1.aivn.net.vn"
    assert Path(values["PDF_STORAGE_PATH"]).is_absolute()
    assert "database_engine" not in content
    assert "UVICORN_WORKERS" not in content


def test_launcher_stops_before_uvicorn_when_database_is_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(app_launcher, "get_resource_root", lambda: tmp_path)
    monkeypatch.setattr(app_launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(app_launcher, "prepare_runtime_environment", lambda: None)
    monkeypatch.setattr(
        app_launcher,
        "verify_database_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("database offline")),
    )
    monkeypatch.setattr(
        app_launcher.uvicorn,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("uvicorn must not start")
        ),
    )

    assert app_launcher.main() == 1


def test_browser_can_be_disabled_for_unattended_host(monkeypatch):
    monkeypatch.setenv("OPEN_BROWSER", "false")

    assert app_launcher.browser_enabled() is False


def test_launcher_configures_console_before_parsing_help(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_launcher,
        "configure_console_output",
        lambda: calls.append("console"),
    )

    def stop_after_recording(_argv):
        calls.append("parse")
        raise RuntimeError("stop after argument parsing")

    monkeypatch.setattr(app_launcher, "_parse_args", stop_after_recording)

    with pytest.raises(RuntimeError, match="stop after argument parsing"):
        app_launcher.main(["--help"])

    assert calls == ["console", "parse"]


def test_package_manifest_excludes_embedded_services_and_secrets():
    project_root = Path(__file__).parents[1]
    spec = (project_root / "scan_to_excel.spec").read_text(encoding="utf-8")
    installer = (project_root / "setup.iss").read_text(encoding="utf-8")

    assert "database_engine" not in spec
    assert "auto_updater" not in spec
    assert "cloudflared" not in spec
    assert "host.env" not in spec
    assert "'server.main'" in spec
    assert "'torch'" in spec
    assert "OutputDir=installer-output" in installer
    assert "D:\\version" not in installer


def test_caddyfile_uses_the_configured_public_hostname():
    project_root = Path(__file__).parents[1]
    caddyfile = (project_root / "Caddyfile").read_text(encoding="utf-8")

    assert "{$PUBLIC_HOSTNAME:nhaplieu1.aivn.net.vn}" in caddyfile


def test_release_contract_is_version_0_1_for_postgresql_18():
    from server.release_info import (
        APP_VERSION,
        DEFAULT_PUBLIC_HOSTNAME,
        SUPPORTED_POSTGRESQL_MAJOR,
    )

    assert APP_VERSION == "0.1"
    assert SUPPORTED_POSTGRESQL_MAJOR == 18
    assert DEFAULT_PUBLIC_HOSTNAME == "nhaplieu1.aivn.net.vn"


def test_failed_candidate_validation_preserves_existing_host_environment(
    monkeypatch, tmp_path
):
    from server import host_setup

    config_path = tmp_path / "config" / "host.env"
    config_path.parent.mkdir(parents=True)
    original = "DATABASE_URL='postgresql+psycopg://old:secret@127.0.0.1/old'\n"
    config_path.write_text(original, encoding="utf-8")

    monkeypatch.setattr(
        host_setup,
        "verify_database_url",
        lambda _url: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        host_setup.validate_and_write_host_environment(
            config_path,
            "DATABASE_URL='postgresql+psycopg://new:secret@127.0.0.1/new'\n",
        )

    assert config_path.read_text(encoding="utf-8") == original


def test_initial_admin_password_is_consumed_without_changing_other_settings(tmp_path):
    from server.host_setup import consume_initial_admin_password

    config_path = tmp_path / "host.env"
    config_path.write_text(
        "SECRET_KEY='keep-me'\n"
        "INITIAL_ADMIN_PASSWORD='remove-me'\n"
        "DATABASE_URL='postgresql+psycopg://user:pass@127.0.0.1/db'\n",
        encoding="utf-8",
    )

    assert consume_initial_admin_password(config_path) is True
    content = config_path.read_text(encoding="utf-8")
    assert "INITIAL_ADMIN_PASSWORD" not in content
    assert "SECRET_KEY='keep-me'" in content
    assert "DATABASE_URL='postgresql+psycopg://user:pass@127.0.0.1/db'" in content
    assert consume_initial_admin_password(config_path) is False


def test_browser_opens_only_for_exact_ready_payload(monkeypatch):
    opened = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"ready","version":"0.1"}'

    monkeypatch.setattr(app_launcher, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(app_launcher.webbrowser, "open", opened.append)

    assert app_launcher.open_browser_when_ready(
        "http://127.0.0.1:8000/health/ready",
        "http://127.0.0.1:8000/login.html",
        attempts=1,
        delay_seconds=0,
    ) is True
    assert opened == ["http://127.0.0.1:8000/login.html"]


def test_browser_rejects_non_ready_success_response(monkeypatch):
    opened = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"starting","version":"0.1"}'

    monkeypatch.setattr(app_launcher, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(app_launcher.webbrowser, "open", opened.append)

    assert app_launcher.open_browser_when_ready(
        "http://127.0.0.1:8000/health/ready",
        "http://127.0.0.1:8000/login.html",
        attempts=1,
        delay_seconds=0,
    ) is False
    assert opened == []


def test_launcher_configure_mode_exits_before_database_and_uvicorn(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(app_launcher, "get_resource_root", lambda: tmp_path)
    monkeypatch.setattr(app_launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(app_launcher, "run_host_configuration", lambda: calls.append("configure") or True)
    monkeypatch.setattr(
        app_launcher,
        "verify_database_connection",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be checked")),
    )
    monkeypatch.setattr(
        app_launcher.uvicorn,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("uvicorn must not start")
        ),
    )

    assert app_launcher.main(["--configure"]) == 0
    assert calls == ["configure"]


def test_release_files_share_version_and_reconfiguration_contract():
    project_root = Path(__file__).parents[1]
    setup = (project_root / "setup.iss").read_text(encoding="utf-8")
    build = (project_root / "scripts/build_windows_package.ps1").read_text(
        encoding="utf-8"
    )
    main = (project_root / "server/main.py").read_text(encoding="utf-8")
    spec = (project_root / "scan_to_excel.spec").read_text(encoding="utf-8")
    launcher = (project_root / "packaging/Start-ScanToExcelHost.cmd").read_text(
        encoding="utf-8"
    )

    assert '#define MyAppVersion "0.1"' in setup
    assert 'Parameters: "--configure"' in setup
    assert 'Start-ScanToExcelHost.cmd' in setup
    assert "shellexec nowait postinstall" not in setup
    assert "function InitializeSetup(): Boolean;" in setup
    assert "DisplayVersion" in setup
    assert "Co (Yes): Sua/cai lai ung dung" in setup
    assert "Co (Yes): Cap nhat tai cho" in setup
    assert "RemoveExistingInstall" in setup
    assert 'ScanToExcelApp.exe' in launcher
    assert 'pause >nul' not in launcher.split('ScanToExcelApp.exe', 1)[0]
    assert "start " not in launcher.lower()
    assert "console=True" in spec
    assert "D:\\ScanToExcel-Releases" in build
    assert '"caddy.exe"' in build
    assert "Caddyfile" in spec
    assert '@app.get("/health/ready"' in main
    assert main.index('@app.get("/health/ready"') < main.index(
        '@app.get("/{filename:path}"'
    )
