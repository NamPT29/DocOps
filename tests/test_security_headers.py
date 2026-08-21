from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from server.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware


def test_security_headers_are_added_to_http_responses():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_security_headers_do_not_overwrite_endpoint_policy():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/embedded")
    def embedded(response: Response):
        response.headers["X-Frame-Options"] = "DENY"
        return {"status": "ok"}

    response = TestClient(app).get("/embedded")

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
