from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from server.http_middleware import configure_http_middleware
from server.security_headers import SECURITY_HEADERS


ALLOWED_ORIGIN = "https://allowed.example"
REQUEST_ID = "cors-request-1234"


def _configured_cors_app() -> FastAPI:
    app = FastAPI()
    configure_http_middleware(app, [ALLOWED_ORIGIN])

    @app.get("/error")
    def error_response():
        return JSONResponse({"detail": "expected error"}, status_code=500)

    return app


def _assert_security_and_request_id_headers(response) -> None:
    assert response.headers["X-Request-ID"] == REQUEST_ID
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_allowed_origin_preflight_returns_cors_headers():
    response = TestClient(_configured_cors_app()).options(
        "/error",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "X-Request-ID": REQUEST_ID,
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert "GET" in response.headers["Access-Control-Allow-Methods"]


def test_error_response_preserves_cors_security_and_request_id_headers():
    response = TestClient(_configured_cors_app()).get(
        "/error",
        headers={"Origin": ALLOWED_ORIGIN, "X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    _assert_security_and_request_id_headers(response)
