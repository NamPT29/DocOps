from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.logging_config import RequestLoggingMiddleware
from server.security_headers import SecurityHeadersMiddleware


def configure_http_middleware(app: FastAPI, cors_origins: Sequence[str]) -> None:
    """Register the production HTTP middleware stack.
    
    In FastAPI/Starlette, middleware executes in reverse registration order (LIFO).
    CORSMiddleware is added last so it forms the outermost layer and handles
    cross-origin requests and preflight OPTIONS before other middlewares.
    """
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
