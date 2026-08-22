import logging

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api_errors import register_exception_handlers
from server.logging_config import (
    RequestLoggingMiddleware,
    close_managed_logging_handlers,
    configure_logging,
)


def _flush_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_logging_separates_app_error_and_audit_files_and_redacts_secrets(tmp_path):
    paths = configure_logging(tmp_path, force=True)
    try:
        logging.getLogger("server.service").info(
            "login password=plain-secret authorization=Bearer signed-token"
        )
        logging.getLogger("server.service").error("failure token=private-token")
        logging.getLogger("server.audit").info(
            "HTTP mutation completed",
            extra={
                "request_id": "request-12345678",
                "user_id": "17",
                "method": "DELETE",
                "path": "/api/projects/{project_id}",
                "status_code": 200,
                "duration_ms": "12.50",
                "client_ip": "127.0.0.1",
                "response_bytes": 42,
            },
        )
        _flush_handlers()

        app_text = paths.app.read_text(encoding="utf-8")
        error_text = paths.error.read_text(encoding="utf-8")
        audit_text = paths.audit.read_text(encoding="utf-8")

        assert "plain-secret" not in app_text
        assert "signed-token" not in app_text
        assert "private-token" not in error_text
        assert "[REDACTED]" in app_text
        assert "HTTP mutation completed" not in app_text
        assert "HTTP mutation completed" in audit_text
        assert "request_id=request-12345678" in audit_text
        assert "user_id=17" in audit_text
    finally:
        close_managed_logging_handlers()


def test_request_middleware_adds_request_id_and_audits_verified_actor(caplog):
    secret_key = "observability-secret-key-at-least-32-bytes"
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, secret_key=secret_key)

    @app.post("/api/projects/{project_id}")
    def update_project(project_id: int):
        return {"project_id": project_id}

    token = jwt.encode({"sub": "17"}, secret_key, algorithm="HS256")
    with caplog.at_level(logging.INFO):
        response = TestClient(app).post(
            "/api/projects/9",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": "request-12345678",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-12345678"
    request_record = next(
        record for record in caplog.records if record.name == "server.http"
    )
    audit_record = next(
        record for record in caplog.records if record.name == "server.audit"
    )
    assert request_record.request_id == "request-12345678"
    assert request_record.user_id == "17"
    assert request_record.path == "/api/projects/{project_id}"
    assert request_record.status_code == 200
    assert float(request_record.duration_ms) >= 0
    assert audit_record.user_id == "17"


def test_request_middleware_replaces_unsafe_request_id():
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, secret_key="s" * 32)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    response = TestClient(app).get(
        "/health",
        headers={"X-Request-ID": "bad"},
    )

    generated_request_id = response.headers["x-request-id"]
    assert generated_request_id != "bad"
    assert len(generated_request_id) == 32


def test_unhandled_error_log_is_correlated_once_and_redacted(tmp_path):
    paths = configure_logging(tmp_path, force=True)
    try:
        app = FastAPI()
        register_exception_handlers(app)
        app.add_middleware(RequestLoggingMiddleware, secret_key="s" * 32)

        @app.get("/broken")
        def broken():
            raise RuntimeError("password=raw-database-secret")

        response = TestClient(app, raise_server_exceptions=False).get(
            "/broken",
            headers={"X-Request-ID": "request-error-1234"},
        )
        _flush_handlers()
        error_text = paths.error.read_text(encoding="utf-8")

        assert response.status_code == 500
        assert response.headers["x-request-id"] == "request-error-1234"
        assert error_text.count("Unhandled exception: GET /broken") == 1
        assert "request_id=request-error-1234" in error_text
        assert "raw-database-secret" not in error_text
        assert "[REDACTED]" in error_text
    finally:
        close_managed_logging_handlers()
