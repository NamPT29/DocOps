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

    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in policy
    assert "style-src 'self'" in policy
    assert "'unsafe-inline'" not in policy
    assert "cdn.jsdelivr.net" not in policy
    assert "cdnjs.cloudflare.com" not in policy
    assert "Content-Security-Policy-Report-Only" not in response.headers
    assert "Strict-Transport-Security" not in response.headers


def test_security_headers_do_not_overwrite_endpoint_policy():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/embedded")
    def embedded(response: Response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return {"status": "ok"}

    response = TestClient(app).get("/embedded")

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_report_only_rollout_preserves_an_endpoint_enforcing_policy():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/strict")
    def strict(response: Response):
        response.headers["Content-Security-Policy-Report-Only"] = "default-src 'none'"
        return {"status": "ok"}

    response = TestClient(app).get("/strict")

    assert response.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"]
    assert response.headers["Content-Security-Policy-Report-Only"] == "default-src 'none'"
