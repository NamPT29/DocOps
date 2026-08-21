from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

_DEVELOPMENT_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/scan_data"
)
_PRODUCTION_ENVIRONMENTS = {"prod", "production"}


def _text(environment: Mapping[str, str], name: str) -> str:
    return str(environment.get(name, "") or "").strip()


def _positive_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = _text(environment, name)
    try:
        value = int(raw_value) if raw_value else default
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là số nguyên dương.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} phải là số nguyên dương.")
    return value


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    secret_key: str
    secret_key_is_ephemeral: bool
    pdf_storage_path: Path
    template_storage_path: Path
    document_source_root: Path
    cors_origins: tuple[str, ...]
    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int
    db_pool_recycle: int
    document_upload_max_bytes: int
    login_max_failures: int
    login_failure_window_seconds: int

    @property
    def is_production(self) -> bool:
        return self.app_env in _PRODUCTION_ENVIRONMENTS

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        generated_secret: str | None = None,
    ) -> "Settings":
        source = os.environ if environment is None else environment
        app_env = _text(source, "APP_ENV").lower() or "development"
        is_production = app_env in _PRODUCTION_ENVIRONMENTS

        database_url = _text(source, "DATABASE_URL")
        if not database_url:
            if is_production:
                raise RuntimeError("DATABASE_URL là bắt buộc trong môi trường production.")
            database_url = _DEVELOPMENT_DATABASE_URL

        secret_key = _text(source, "SECRET_KEY")
        secret_key_is_ephemeral = not secret_key
        if secret_key_is_ephemeral:
            if is_production:
                raise RuntimeError("SECRET_KEY là bắt buộc trong môi trường production.")
            secret_key = generated_secret or secrets.token_urlsafe(48)
        if len(secret_key.encode("utf-8")) < 32:
            raise RuntimeError("SECRET_KEY phải có ít nhất 32 byte.")

        storage_values = {
            "PDF_STORAGE_PATH": _text(source, "PDF_STORAGE_PATH"),
            "TEMPLATE_STORAGE_PATH": _text(source, "TEMPLATE_STORAGE_PATH"),
            "DOCUMENT_SOURCE_ROOT": _text(source, "DOCUMENT_SOURCE_ROOT"),
        }
        if is_production:
            missing = [name for name, value in storage_values.items() if not value]
            if missing:
                raise RuntimeError(
                    "Thiếu cấu hình thư mục production: " + ", ".join(missing)
                )

        cors_origins = tuple(
            origin.strip()
            for origin in _text(source, "CORS_ORIGINS").split(",")
            if origin.strip()
        )

        return cls(
            app_env=app_env,
            database_url=database_url,
            secret_key=secret_key,
            secret_key_is_ephemeral=secret_key_is_ephemeral,
            pdf_storage_path=Path(storage_values["PDF_STORAGE_PATH"] or "uploads"),
            template_storage_path=Path(storage_values["TEMPLATE_STORAGE_PATH"] or "templates"),
            document_source_root=Path(storage_values["DOCUMENT_SOURCE_ROOT"] or "source_documents"),
            cors_origins=cors_origins,
            db_pool_size=_positive_int(source, "DB_POOL_SIZE", 20),
            db_max_overflow=_positive_int(source, "DB_MAX_OVERFLOW", 10),
            db_pool_timeout=_positive_int(source, "DB_POOL_TIMEOUT", 30),
            db_pool_recycle=_positive_int(source, "DB_POOL_RECYCLE", 1800),
            document_upload_max_bytes=_positive_int(
                source,
                "DOCUMENT_UPLOAD_MAX_BYTES",
                100 * 1024 * 1024,
            ),
            login_max_failures=_positive_int(source, "LOGIN_MAX_FAILURES", 5),
            login_failure_window_seconds=_positive_int(
                source,
                "LOGIN_FAILURE_WINDOW_SECONDS",
                15 * 60,
            ),
        )


settings = Settings.from_env()
if settings.secret_key_is_ephemeral:
    logger.warning(
        "SECRET_KEY chưa được cấu hình; token sẽ hết hiệu lực khi server khởi động lại."
    )
