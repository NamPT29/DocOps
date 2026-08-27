import tempfile
from pathlib import Path

import pytest

from server.settings import Settings


def production_environment() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://scan_app:secret@db:5432/scan_data",
        "SECRET_KEY": "s" * 32,
        "PDF_STORAGE_PATH": "/data/uploads",
        "TEMPLATE_STORAGE_PATH": "/data/templates",
        "DOCUMENT_SOURCE_ROOT": "/data/source_documents",
        "EXPORT_WORK_DIR": "/data/export_jobs",
    }


def test_development_settings_keep_compatible_defaults():
    configured = Settings.from_env({}, generated_secret="d" * 32)

    assert configured.app_env == "development"
    assert configured.database_url.endswith("127.0.0.1:5432/scan_data")
    assert configured.secret_key == "d" * 32
    assert configured.secret_key_is_ephemeral is True
    assert str(configured.pdf_storage_path) == "uploads"
    assert configured.export_work_dir == (
        Path(tempfile.gettempdir()) / "scan_to_excel" / "export_jobs"
    )
    assert configured.document_upload_max_bytes == 100 * 1024 * 1024
    assert configured.heavy_api_rate_limit == 240
    assert configured.heavy_api_rate_window_seconds == 60
    assert configured.project_upload_chunk_rate_limit == 2400
    assert configured.dictionary_cache_ttl_seconds == 30
    assert configured.redis_url is None
    assert configured.api_docs_enabled is False


def test_production_redis_requires_tls_url():
    environment = production_environment()
    environment["REDIS_URL"] = "redis://redis:6379/0"

    with pytest.raises(RuntimeError, match="rediss"):
        Settings.from_env(environment)


@pytest.mark.parametrize(
    ("missing_name", "message"),
    [
        ("DATABASE_URL", "DATABASE_URL"),
        ("SECRET_KEY", "SECRET_KEY"),
        ("PDF_STORAGE_PATH", "PDF_STORAGE_PATH"),
        ("TEMPLATE_STORAGE_PATH", "TEMPLATE_STORAGE_PATH"),
        ("DOCUMENT_SOURCE_ROOT", "DOCUMENT_SOURCE_ROOT"),
        ("EXPORT_WORK_DIR", "EXPORT_WORK_DIR"),
    ],
)
def test_production_rejects_missing_security_configuration(missing_name, message):
    environment = production_environment()
    environment.pop(missing_name)

    with pytest.raises(RuntimeError, match=message):
        Settings.from_env(environment)


def test_secret_key_must_have_at_least_32_bytes():
    environment = production_environment()
    environment["SECRET_KEY"] = "too-short"

    with pytest.raises(RuntimeError, match="32 byte"):
        Settings.from_env(environment)


def test_numeric_security_limits_must_be_positive():
    environment = production_environment()
    environment["DOCUMENT_UPLOAD_MAX_BYTES"] = "0"

    with pytest.raises(RuntimeError, match="DOCUMENT_UPLOAD_MAX_BYTES"):
        Settings.from_env(environment)


def test_dictionary_cache_ttl_must_be_positive():
    environment = production_environment()
    environment["DICTIONARY_CACHE_TTL_SECONDS"] = "0"

    with pytest.raises(RuntimeError, match="DICTIONARY_CACHE_TTL_SECONDS"):
        Settings.from_env(environment)


def test_logging_settings_are_environment_driven():
    configured = Settings.from_env(
        {
            "LOG_LEVEL": "warning",
            "LOG_DIR": "runtime-logs",
            "LOG_MAX_BYTES": "4096",
            "LOG_BACKUP_COUNT": "2",
        },
        generated_secret="d" * 32,
    )

    assert configured.log_level == "WARNING"
    assert configured.log_dir == Path("runtime-logs")
    assert configured.log_max_bytes == 4096
    assert configured.log_backup_count == 2


def test_logging_level_rejects_unsupported_values():
    with pytest.raises(RuntimeError, match="LOG_LEVEL"):
        Settings.from_env({"LOG_LEVEL": "verbose"}, generated_secret="d" * 32)


def test_api_docs_require_explicit_boolean_configuration():
    configured = Settings.from_env(
        {"API_DOCS_ENABLED": "true"},
        generated_secret="d" * 32,
    )

    assert configured.api_docs_enabled is True

    with pytest.raises(RuntimeError, match="API_DOCS_ENABLED"):
        Settings.from_env({"API_DOCS_ENABLED": "sometimes"}, generated_secret="d" * 32)
