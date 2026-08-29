"""Non-UI helpers for validating and persisting packaged-host settings."""

from __future__ import annotations

from io import StringIO
import os
from pathlib import Path
import re
import socket

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


HOST_CONFIG_PATH_ENV = "SCAN_TO_EXCEL_CONFIG_PATH"
INITIAL_ADMIN_PASSWORD_KEY = "INITIAL_ADMIN_PASSWORD"
_ENV_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def verify_database_url(database_url: str, *, timeout_seconds: int = 5) -> None:
    """Verify candidate PostgreSQL settings without importing global app settings."""
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL phải dùng PostgreSQL với psycopg.")

    engine = None
    try:
        engine = create_engine(
            database_url,
            poolclass=NullPool,
            connect_args={"connect_timeout": timeout_seconds},
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            "Không kết nối được PostgreSQL 18. Hãy kiểm tra dịch vụ, database, "
            "tài khoản và mật khẩu."
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()


def verify_web_port_available(port: int) -> None:
    """Fail before saving configuration when the selected local port is occupied."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError(
            f"Cổng Web {port} đang được sử dụng. Hãy chọn cổng khác."
        ) from exc
    finally:
        probe.close()


def _write_text_atomically(target_path: Path, content: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        temporary_path.write_text(content, encoding="utf-8")
        os.replace(temporary_path, target_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def validate_and_write_host_environment(
    env_path: str | Path,
    content: str,
    *,
    web_port: int | None = None,
) -> None:
    """Validate a candidate completely before replacing the last known config."""
    values = dotenv_values(stream=StringIO(content))
    database_url = str(values.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("Thiếu DATABASE_URL trong cấu hình host.")

    verify_database_url(database_url)
    if web_port is not None:
        verify_web_port_available(web_port)
    _write_text_atomically(Path(env_path), content)


def consume_initial_admin_password(env_path: str | Path) -> bool:
    """Remove the one-time admin secret while preserving every other setting."""
    target_path = Path(env_path)
    if not target_path.exists():
        return False

    original_lines = target_path.read_text(encoding="utf-8").splitlines(keepends=True)
    filtered_lines: list[str] = []
    removed = False
    for line in original_lines:
        match = _ENV_ASSIGNMENT.match(line)
        if match and match.group(1) == INITIAL_ADMIN_PASSWORD_KEY:
            removed = True
            continue
        filtered_lines.append(line)

    if removed:
        _write_text_atomically(target_path, "".join(filtered_lines))
    return removed
