from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.logging_config import request_log_context


logger = logging.getLogger("server")


class ApiErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    message: str
    detail: Any | None = None


_ERROR_DESCRIPTIONS = {
    400: "Yêu cầu không hợp lệ",
    401: "Chưa xác thực",
    403: "Không có quyền truy cập",
    404: "Không tìm thấy tài nguyên",
    409: "Xung đột trạng thái",
    413: "Tệp tải lên quá lớn",
    422: "Dữ liệu yêu cầu không hợp lệ",
    429: "Quá nhiều yêu cầu",
    500: "Lỗi máy chủ nội bộ",
}

API_ERROR_RESPONSES = {
    status_code: {
        "model": ApiErrorResponse,
        "description": description,
    }
    for status_code, description in _ERROR_DESCRIPTIONS.items()
}


def _message_from_detail(detail: Any, default: str) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message
    return default


def _error_content(message: str, detail: Any = None) -> dict[str, Any]:
    return {
        "status": "error",
        "message": message,
        "detail": jsonable_encoder(detail),
    }


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    del request
    message = _message_from_detail(exc.detail, "Yêu cầu không thể thực hiện")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_content(message, exc.detail),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    safe_errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "Giá trị không hợp lệ"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_content("Dữ liệu yêu cầu không hợp lệ", safe_errors),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    log_context = request_log_context(request.scope, status_code=500)
    log_context["error_type"] = type(exc).__name__
    logger.error(
        "Unhandled request exception",
        extra=log_context,
    )
    response_headers = {}
    if log_context["request_id"] != "-":
        response_headers["X-Request-ID"] = str(log_context["request_id"])
    return JSONResponse(
        status_code=500,
        content=_error_content("Lỗi máy chủ nội bộ"),
        headers=response_headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
