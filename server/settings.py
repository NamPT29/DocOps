from __future__ import annotations

import logging
import os
import secrets
import tempfile
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
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


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


def _log_level(environment: Mapping[str, str]) -> str:
    value = _text(environment, "LOG_LEVEL").upper() or "INFO"
    if value not in _LOG_LEVELS:
        raise RuntimeError(
            "LOG_LEVEL phải là DEBUG, INFO, WARNING, ERROR hoặc CRITICAL."
        )
    return value


def _boolean(
    environment: Mapping[str, str],
    name: str,
    default: bool = False,
) -> bool:
    value = _text(environment, name).lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} phải là true hoặc false.")


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    redis_url: str | None
    secret_key: str
    secret_key_is_ephemeral: bool
    pdf_storage_path: Path
    template_storage_path: Path
    document_source_root: Path
    export_work_dir: Path
    cors_origins: tuple[str, ...]
    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int
    db_pool_recycle: int
    document_upload_max_bytes: int
    login_max_failures: int
    login_failure_window_seconds: int
    access_token_expire_minutes: int
    session_idle_timeout_minutes: int
    session_activity_touch_interval_seconds: int
    session_close_grace_seconds: int
    heavy_api_rate_limit: int
    heavy_api_rate_window_seconds: int
    project_upload_chunk_rate_limit: int
    dictionary_cache_ttl_seconds: int
    log_level: str
    log_dir: Path
    log_max_bytes: int
    log_backup_count: int
    api_docs_enabled: bool

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

        redis_url = _text(source, "REDIS_URL") or None
        if redis_url and is_production and not redis_url.startswith("rediss://"):
            raise RuntimeError(
                "REDIS_URL production phải dùng rediss:// để mã hóa kết nối Redis."
            )

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
            "EXPORT_WORK_DIR": _text(source, "EXPORT_WORK_DIR"),
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
            redis_url=redis_url,
            secret_key=secret_key,
            secret_key_is_ephemeral=secret_key_is_ephemeral,
            pdf_storage_path=Path(storage_values["PDF_STORAGE_PATH"] or "uploads"),
            template_storage_path=Path(storage_values["TEMPLATE_STORAGE_PATH"] or "templates"),
            document_source_root=Path(storage_values["DOCUMENT_SOURCE_ROOT"] or "source_documents"),
            export_work_dir=Path(
                storage_values["EXPORT_WORK_DIR"]
                or Path(tempfile.gettempdir()) / "scan_to_excel" / "export_jobs"
            ),
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
            access_token_expire_minutes=_positive_int(
                source,
                "ACCESS_TOKEN_EXPIRE_MINUTES",
                24 * 60,
            ),
            session_idle_timeout_minutes=_positive_int(
                source,
                "SESSION_IDLE_TIMEOUT_MINUTES",
                30,
            ),
            session_activity_touch_interval_seconds=_positive_int(
                source,
                "SESSION_ACTIVITY_TOUCH_INTERVAL_SECONDS",
                60,
            ),
            session_close_grace_seconds=_positive_int(
                source,
                "SESSION_CLOSE_GRACE_SECONDS",
                30,
            ),
            heavy_api_rate_limit=_positive_int(source, "HEAVY_API_RATE_LIMIT", 240),
            heavy_api_rate_window_seconds=_positive_int(
                source,
                "HEAVY_API_RATE_WINDOW_SECONDS",
                60,
            ),
            project_upload_chunk_rate_limit=_positive_int(
                source,
                "PROJECT_UPLOAD_CHUNK_RATE_LIMIT",
                2400,
            ),
            dictionary_cache_ttl_seconds=_positive_int(
                source,
                "DICTIONARY_CACHE_TTL_SECONDS",
                30,
            ),
            log_level=_log_level(source),
            log_dir=Path(_text(source, "LOG_DIR") or "logs"),
            log_max_bytes=_positive_int(source, "LOG_MAX_BYTES", 10 * 1024 * 1024),
            log_backup_count=_positive_int(source, "LOG_BACKUP_COUNT", 5),
            api_docs_enabled=_boolean(source, "API_DOCS_ENABLED"),
        )


settings = Settings.from_env()
if settings.secret_key_is_ephemeral:
    logger.warning(
        "SECRET_KEY chưa được cấu hình; token sẽ hết hiệu lực khi server khởi động lại."
    )
