from pathlib import Path

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
