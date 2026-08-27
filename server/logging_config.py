from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_MANAGED_HANDLER_ATTRIBUTE = "_scan_to_excel_managed_handler"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)([\"']?(?:password|passwd|secret|token|authorization|cookie|api[_-]?key)"
    r"[\"']?\s*[:=]\s*)(?:bearer\s+)?[\"']?([^,\s;&}\]\"']+)[\"']?"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_CONTEXT = {
    "request_id": "-",
    "method": "-",
    "path": "-",
    "status_code": "-",
    "duration_ms": "-",
    "response_bytes": "-",
    "error_type": "-",
}
_request_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "request_log_context",
    default=None,
)


@dataclass(frozen=True)
class LogPaths:
    app: Path
    error: Path
    audit: Path


class RedactingFormatter(logging.Formatter):
    """Render one redacted JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        message = _SENSITIVE_ASSIGNMENT_PATTERN.sub(
            lambda match: f"{match.group(1)}[REDACTED]",
            record.getMessage(),
        )
        message = _BEARER_PATTERN.sub("Bearer [REDACTED]", message)
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            **{
                name: getattr(record, name, default)
                for name, default in _DEFAULT_CONTEXT.items()
            },
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload["event"] = {
                str(name): (
                    _BEARER_PATTERN.sub(
                        "Bearer [REDACTED]",
                        _SENSITIVE_ASSIGNMENT_PATTERN.sub(
                            lambda match: f"{match.group(1)}[REDACTED]",
                            value,
                        ),
                    )
                    if isinstance(value, str)
                    else value
                )
                for name, value in event_data.items()
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _request_context.get() or {}
        for name, default in _DEFAULT_CONTEXT.items():
            if not hasattr(record, name):
                setattr(record, name, context.get(name, default))
        return True


class _AuditOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "server.audit" or record.name.startswith("server.audit.")


class _ExcludeAuditFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _AuditOnlyFilter().filter(record)


def _log_paths(log_dir: str | Path | None) -> LogPaths:
    directory = (
        Path(log_dir)
        if log_dir is not None
        else Path(__file__).resolve().parent.parent / "logs"
    ).resolve()
    suffix = f".{os.getpid()}" if os.environ.get("MULTIPROCESS_LOGGING") == "1" else ""
    return LogPaths(
        app=directory / f"app{suffix}.log",
        error=directory / f"error{suffix}.log",
        audit=directory / f"audit{suffix}.log",
    )


def close_managed_logging_handlers() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if not getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False):
            continue
        root_logger.removeHandler(handler)
        handler.flush()
        handler.close()


def configure_logging(
    log_dir: str | Path | None = None,
    *,
    force: bool = False,
    level: int | str = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> LogPaths:
    """Configure idempotent rotating app, error, and audit log files."""

    paths = _log_paths(log_dir)
    root_logger = logging.getLogger()
    managed_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False)
    ]
    if managed_handlers and not force:
        return paths
    if managed_handlers:
        close_managed_logging_handlers()

    paths.app.parent.mkdir(parents=True, exist_ok=True)
    resolved_level = logging.getLevelNamesMapping().get(str(level).upper(), level)
    if not isinstance(resolved_level, int):
        raise ValueError(f"Unsupported logging level: {level}")
    formatter = RedactingFormatter()
    context_filter = RequestContextFilter()

    app_handler = logging.handlers.RotatingFileHandler(
        paths.app,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    app_handler.setLevel(resolved_level)
    app_handler.setFormatter(formatter)
    app_handler.addFilter(context_filter)
    app_handler.addFilter(_ExcludeAuditFilter())

    error_handler = logging.handlers.RotatingFileHandler(
        paths.error,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(context_filter)

    audit_handler = logging.handlers.RotatingFileHandler(
        paths.audit,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(formatter)
    audit_handler.addFilter(context_filter)
    audit_handler.addFilter(_AuditOnlyFilter())

    for handler in (app_handler, error_handler, audit_handler):
        setattr(handler, _MANAGED_HANDLER_ATTRIBUTE, True)
        root_logger.addHandler(handler)
    root_logger.setLevel(resolved_level)
    return paths


def _header_value(scope: dict[str, Any], name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode("latin-1", errors="replace").strip()
    return ""


def _request_id(scope: dict[str, Any]) -> str:
    supplied = _header_value(scope, b"x-request-id")
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


def _route_path(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    return str(route_path or "<unmatched>")[:1024]


def request_log_context(
    scope: dict[str, Any],
    *,
    status_code: int | None = None,
) -> dict[str, Any]:
    state = scope.get("state") or {}
    stored_context = (
        state.get("request_log_context", {}) if isinstance(state, dict) else {}
    )
    context = {**_DEFAULT_CONTEXT, **stored_context}
    if status_code is not None:
        context["status_code"] = status_code
    return context


class RequestLoggingMiddleware:
    """Correlate HTTP requests and emit a separate mutation audit trail."""

    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app
        self.request_logger = logging.getLogger("server.http")
        self.audit_logger = logging.getLogger("server.audit")

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        request_id = _request_id(scope)
        method = str(scope.get("method") or "HTTP").upper()
        context: dict[str, Any] = {
            "request_id": request_id,
            "method": method,
            "path": _route_path(scope),
            "status_code": 500,
            "duration_ms": "0.00",
            "response_bytes": 0,
            "error_type": "-",
        }
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
            state["request_log_context"] = context
            state["request_started_at"] = started
        context_token = _request_context.set(context)

        async def logged_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                context["status_code"] = int(message.get("status", 500))
                headers = [
                    (key, value)
                    for key, value in message.get("headers", ())
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            elif message.get("type") == "http.response.body":
                context["response_bytes"] += len(message.get("body", b"") or b"")
            await send(message)

        try:
            await self.app(scope, receive, logged_send)
        finally:
            context["path"] = _route_path(scope)
            context["duration_ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
            self.request_logger.info("HTTP request completed", extra=context)
            if method in _STATE_CHANGING_METHODS and context["path"].startswith("/api"):
                self.audit_logger.info("HTTP mutation completed", extra=context)
            _request_context.reset(context_token)
