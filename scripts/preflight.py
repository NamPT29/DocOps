"""Kiểm tra máy chủ trước khi chạy thật (R1).

    python scripts/preflight.py                  đọc .env ở thư mục dự án
    python scripts/preflight.py --env-file PATH  đọc file cấu hình khác

Chỉ ĐỌC: không sửa cấu hình, không áp migration, không ghi CSDL.
Không bao giờ in mật khẩu trong DATABASE_URL hay giá trị SECRET_KEY.
Cấu hình đọc như host_console.py: biến môi trường thắng, .env chỉ bổ sung
biến còn thiếu. Không import server.settings/server.database để tránh nối
nhầm CSDL dev mặc định khi chưa đặt DATABASE_URL.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import re
import shutil
import socket
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from server.migration_runner import HEAD_REVISION, current_database_revision  # noqa: E402


PASS = "ĐẠT"
WARN = "CẢNH BÁO"
FAIL = "LỖI"

MIN_PYTHON = (3, 11)
PACKAGED_PYTHON = (3, 12)
MIN_SECRET_BYTES = 32  # cùng luật với server/settings.py
MIN_FREE_BYTES = 5 * 1024 ** 3
DEFAULT_PORT = "80"  # mặc định của host_console.py
CONNECT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str


def load_config(environ: Mapping[str, str], env_file: Path | None) -> dict[str, str]:
    """Biến môi trường thắng; file .env chỉ bổ sung biến chưa có."""
    from dotenv import dotenv_values

    config: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        config.update(
            {key: value for key, value in dotenv_values(env_file).items() if value is not None}
        )
    config.update(environ)
    return config


def _value(config: Mapping[str, str], name: str) -> str:
    return str(config.get(name, "") or "").strip()


def _masked_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<DATABASE_URL không đọc được>"


def _scrub(message: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message.splitlines()[0] if message else message


def _pinned_version(package: str, lock_file: Path) -> str | None:
    if not lock_file.is_file():
        return None
    pattern = re.compile(rf"^{re.escape(package)}==([^\s;#]+)", re.IGNORECASE)
    for line in lock_file.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1)
    return None


def _known_revisions(root: Path) -> set[str]:
    pattern = re.compile(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
    revisions = set()
    for path in (root / "migrations" / "versions").glob("*.py"):
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match:
            revisions.add(match.group(1))
    return revisions


def check_python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] < MIN_PYTHON:
        return Check(FAIL, "Python", f"{version}; cần >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
    if sys.version_info[:2] != PACKAGED_PYTHON:
        return Check(
            WARN,
            "Python",
            f"{version}; bản đóng gói dùng {PACKAGED_PYTHON[0]}.{PACKAGED_PYTHON[1]}",
        )
    return Check(PASS, "Python", version)


def check_pypdf(root: Path) -> Check:
    try:
        module = importlib.import_module("pypdf")
    except ImportError:
        return Check(
            FAIL,
            "pypdf",
            "chưa cài; mọi gói Nộp S sẽ lỗi. Chạy: pip install -r requirements.txt",
        )
    installed = str(getattr(module, "__version__", "?"))
    pinned = _pinned_version("pypdf", root / "requirements-package.lock")
    if pinned and installed != pinned:
        return Check(WARN, "pypdf", f"bản {installed}, khác bản ghim {pinned}")
    return Check(PASS, "pypdf", f"bản {installed}")


def check_secret_key(config: Mapping[str, str]) -> Check:
    secret = _value(config, "SECRET_KEY")
    if not secret:
        return Check(FAIL, "SECRET_KEY", "chưa đặt; phiên đăng nhập mất mỗi lần khởi động lại")
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        return Check(FAIL, "SECRET_KEY", f"ngắn hơn {MIN_SECRET_BYTES} byte")
    return Check(PASS, "SECRET_KEY", "đã đặt, đủ dài")


def check_app_env(config: Mapping[str, str]) -> Check:
    app_env = _value(config, "APP_ENV").lower() or "development"
    if app_env not in {"prod", "production"}:
        return Check(WARN, "APP_ENV", f"'{app_env}'; chạy thật nên đặt APP_ENV=production")
    return Check(PASS, "APP_ENV", app_env)


def check_document_root(config: Mapping[str, str], root: Path) -> tuple[Check, Path | None]:
    raw = _value(config, "DOCUMENT_SOURCE_ROOT")
    if not raw:
        return Check(FAIL, "DOCUMENT_SOURCE_ROOT", "chưa đặt"), None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path  # host_console.py chạy với thư mục dự án làm thư mục hiện hành
    if not path.exists():
        return Check(FAIL, "DOCUMENT_SOURCE_ROOT", f"không tồn tại: {path}"), None
    if not path.is_dir():
        return Check(FAIL, "DOCUMENT_SOURCE_ROOT", f"không phải thư mục: {path}"), None
    if not os.access(path, os.R_OK | os.X_OK):
        return Check(FAIL, "DOCUMENT_SOURCE_ROOT", f"không đọc được: {path}"), None
    return Check(PASS, "DOCUMENT_SOURCE_ROOT", str(path)), path


def check_free_space(path: Path) -> Check:
    free = shutil.disk_usage(path).free
    free_gb = free / 1024 ** 3
    if free < MIN_FREE_BYTES:
        return Check(WARN, "Dung lượng trống", f"{free_gb:.1f} GB (< 5 GB) ở ổ chứa {path}")
    return Check(PASS, "Dung lượng trống", f"{free_gb:.1f} GB")


def check_database(url: str, secrets: list[str], root: Path) -> list[Check]:
    masked = _masked_url(url)
    connect_args = {}
    if url.startswith("postgresql"):
        connect_args["connect_timeout"] = CONNECT_TIMEOUT_SECONDS
    try:
        engine = create_engine(url, poolclass=NullPool, connect_args=connect_args)
    except Exception as exc:
        return [Check(FAIL, "Kết nối CSDL", _scrub(f"DATABASE_URL sai dạng: {exc}", secrets))]
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = current_database_revision(connection)
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
    except Exception as exc:
        return [Check(FAIL, "Kết nối CSDL", _scrub(f"{masked}: {exc}", secrets))]
    finally:
        engine.dispose()

    checks = [Check(PASS, "Kết nối CSDL", masked)]
    name = "Migration"
    if current == HEAD_REVISION:
        checks.append(Check(PASS, name, current))
    elif current is None and not tables:
        checks.append(Check(WARN, name, "CSDL trống; host_console.py sẽ tạo bảng khi khởi động"))
    elif current is None:
        checks.append(Check(
            WARN,
            name,
            "chưa có alembic_version; host_console.py sẽ thẩm định và nhận schema khi "
            "khởi động. SAO LƯU (pg_dump) TRƯỚC KHI KHỞI ĐỘNG",
        ))
    elif current in _known_revisions(root):
        checks.append(Check(
            WARN,
            name,
            f"đang ở {current}, bản mới cần {HEAD_REVISION}; host_console.py sẽ TỰ NÂNG khi "
            "khởi động. SAO LƯU (pg_dump) TRƯỚC KHI KHỞI ĐỘNG",
        ))
    else:
        checks.append(Check(
            FAIL,
            name,
            f"revision lạ {current!r} (không có trong migrations/versions); "
            "có thể CSDL thuộc bản mới hơn code này",
        ))
    return checks


def check_port(config: Mapping[str, str]) -> Check:
    raw = _value(config, "PORT") or DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return Check(FAIL, "Cổng", f"PORT không phải số: {raw!r}")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        return Check(PASS, "Cổng", f"{port} đang trống")
    return Check(
        WARN,
        "Cổng",
        f"{port} đang có chương trình khác (bản cũ đang chạy, hoặc Caddy nếu PORT=80)",
    )


def run_checks(
    environ: Mapping[str, str],
    env_file: Path | None,
    *,
    root: Path = ROOT,
) -> list[Check]:
    config = load_config(environ, env_file)
    checks = [check_python(), check_pypdf(root), check_app_env(config)]

    database_url = _value(config, "DATABASE_URL")
    secrets = [_value(config, "SECRET_KEY")]
    if database_url:
        try:
            secrets.append(make_url(database_url).password or "")
        except Exception:
            pass

    checks.append(check_secret_key(config))
    document_check, document_root = check_document_root(config, root)
    checks.append(document_check)
    if document_root is not None:
        checks.append(check_free_space(document_root))

    if not database_url:
        checks.append(Check(
            FAIL,
            "DATABASE_URL",
            "chưa đặt (biến môi trường hoặc .env); bỏ qua kiểm tra kết nối "
            "để không nối nhầm CSDL dev mặc định",
        ))
    else:
        checks.extend(check_database(database_url, secrets, root))
    checks.append(check_port(config))
    return checks


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra máy chủ trước khi chạy thật.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args(argv)

    checks = run_checks(os.environ if environ is None else environ, args.env_file)
    for check in checks:
        print(f"[{check.status}] {check.name}: {check.detail}")
    failures = sum(check.status == FAIL for check in checks)
    warnings = sum(check.status == WARN for check in checks)
    print()
    if failures:
        print(f"KẾT QUẢ PREFLIGHT: KHÔNG ĐẠT ({failures} lỗi, {warnings} cảnh báo)")
        return 1
    print(f"KẾT QUẢ PREFLIGHT: ĐẠT ({warnings} cảnh báo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
