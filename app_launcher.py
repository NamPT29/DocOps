"""Windows launcher for source checkouts and packaged ScanToExcel hosts."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn
from dotenv import load_dotenv

from server.host_runtime_paths import HostRuntimePaths, resolve_host_data_root
from server.host_setup import HOST_CONFIG_PATH_ENV
from server.packaged_services import (
    ensure_cloudflared_service,
    start_packaged_caddy,
    stop_managed_caddy,
)
from server.release_info import (
    APP_VERSION,
    DEFAULT_PUBLIC_HOSTNAME,
    SUPPORTED_POSTGRESQL_MAJOR,
)
from server.runtime_config import configure_server_runtime
from wizard import run_setup_wizard


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def configure_console_output() -> None:
    """Prevent localized errors from crashing legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def get_base_dir() -> str:
    """Return the immutable application directory."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_root() -> Path:
    """Return the directory containing bundled frontend resources."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    return Path(bundled_root) if is_frozen() and bundled_root else Path(get_base_dir())


def bind_runtime_paths(
    paths: HostRuntimePaths,
    environment: dict[str, str] | os._Environ[str] | None = None,
) -> None:
    """Force mutable packaged-host files into the persistent data root."""
    target = os.environ if environment is None else environment
    path_values = {
        "PDF_STORAGE_PATH": paths.uploads_dir,
        "TEMPLATE_STORAGE_PATH": paths.templates_dir,
        "DOCUMENT_SOURCE_ROOT": paths.source_documents_dir,
        "EXPORT_WORK_DIR": paths.exports_dir,
        "LOG_DIR": paths.logs_dir,
    }
    for key, value in path_values.items():
        target[key] = str(value.resolve())


def prepare_runtime_environment() -> HostRuntimePaths | None:
    """Load configuration before importing modules that construct DB settings."""
    if not is_frozen():
        load_dotenv(Path(get_base_dir()) / ".env", override=False)
        return None

    paths = HostRuntimePaths(resolve_host_data_root())
    paths.ensure_directories()
    if not paths.config_path.exists():
        configured = run_setup_wizard(paths.config_path, paths)
        if not configured:
            raise RuntimeError(
                "Chua co cau hinh host.env. Qua trinh thiet lap da bi huy."
            )

    # host.env is the authoritative packaged-host configuration. Do not let a
    # stale system-wide DATABASE_URL silently redirect this installation.
    load_dotenv(paths.config_path, override=True)
    bind_runtime_paths(paths)
    return paths


def run_host_configuration() -> bool:
    """Open the packaged-host wizard without starting the HTTP server."""
    if not is_frozen():
        raise RuntimeError("Chế độ --configure chỉ dùng cho ứng dụng đã đóng gói.")
    paths = HostRuntimePaths(resolve_host_data_root())
    paths.ensure_directories()
    return run_setup_wizard(paths.config_path, paths)


def verify_database_connection() -> None:
    """Fail before starting workers when PostgreSQL is unavailable."""
    from sqlalchemy import text

    from server.database import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def run_host_console() -> int:
    """Run the same monitored console dashboard used by host_server.bat."""
    from host_console import main as run_dashboard

    return run_dashboard()


def public_url(host: str, port: int, path: str = "") -> str:
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    authority = url_host if port == 80 else f"{url_host}:{port}"
    suffix = path if path.startswith("/") or not path else f"/{path}"
    return f"http://{authority}{suffix}"


def browser_enabled() -> bool:
    return os.environ.get("OPEN_BROWSER", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def open_browser_when_ready(
    health_url: str,
    browser_url: str,
    *,
    attempts: int = 60,
    delay_seconds: float = 0.5,
) -> bool:
    """Open the browser only after the HTTP server is accepting requests."""
    for _attempt in range(attempts):
        try:
            with urlopen(health_url, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if (
                    response.status == 200
                    and payload.get("status") == "ready"
                    and payload.get("version") == APP_VERSION
                ):
                    webbrowser.open(browser_url)
                    return True
        except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        time.sleep(delay_seconds)
    print(f"Khong nhan duoc trang thai san sang tu {health_url}.")
    return False


def report_public_domain_when_ready(
    health_url: str,
    *,
    attempts: int = 60,
    delay_seconds: float = 1.0,
) -> bool:
    """Report whether the configured Cloudflare route reaches this release."""
    for _attempt in range(attempts):
        try:
            with urlopen(health_url, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if (
                    response.status == 200
                    and payload.get("status") == "ready"
                    and payload.get("version") == APP_VERSION
                ):
                    print(f"Domain cong khai: SAN SANG - {health_url}")
                    return True
        except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        time.sleep(delay_seconds)
    print(f"CANH BAO: Domain cong khai chua san sang - {health_url}")
    print("Kiem tra dich vu Cloudflared va Public Hostname -> http://127.0.0.1:80.")
    return False


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ScanToExcelApp")
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Mở lại trình cấu hình host.env rồi thoát.",
    )
    return parser.parse_args([] if argv is None else argv)


def main(argv: list[str] | None = None) -> int:
    configure_console_output()
    if argv and argv[0] == "--export-worker":
        os.chdir(get_resource_root())
        prepare_runtime_environment()
        from server.export_worker import parse_args, run_export_job

        return run_export_job(parse_args(argv[1:]))
    args = _parse_args(argv)
    resource_root = get_resource_root()
    os.chdir(resource_root)

    if args.configure:
        try:
            configured = run_host_configuration()
        except Exception as exc:
            print(f"Khong the mo cau hinh: {exc}")
            return 1
        return 0 if configured else 1

    managed_caddy = None
    public_hostname = ""
    try:
        paths = prepare_runtime_environment()
        if paths is not None:
            os.environ[HOST_CONFIG_PATH_ENV] = str(paths.config_path.resolve())
        verify_database_connection()
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8000"))
        public_hostname = os.environ.get("PUBLIC_HOSTNAME", "").strip()
        if paths is not None:
            managed_caddy, caddy_status = start_packaged_caddy(
                Path(get_base_dir()),
                resource_root,
            )
            cloudflared_status = ensure_cloudflared_service()
            print(f"Caddy: {caddy_status}")
            print(f"Cloudflared: {cloudflared_status}")
    except Exception as exc:
        stop_managed_caddy(managed_caddy)
        print("=" * 60)
        print("KHONG THE KHOI DONG SCAN TO EXCEL")
        print(f"Ly do: {exc}")
        print("Kiem tra host.env va dich vu PostgreSQL, sau do chay lai.")
        print("=" * 60)
        return 1

    browser_url = public_url(host, port, "/login.html")
    health_url = public_url(host, port, "/health/ready")
    if browser_enabled():
        threading.Thread(
            target=open_browser_when_ready,
            args=(health_url, browser_url),
            daemon=True,
        ).start()
    if paths is not None and public_hostname:
        threading.Thread(
            target=report_public_domain_when_ready,
            args=(f"https://{public_hostname}/health/ready",),
            daemon=True,
        ).start()

    try:
        return run_host_console()
    finally:
        stop_managed_caddy(managed_caddy)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv[1:]))
