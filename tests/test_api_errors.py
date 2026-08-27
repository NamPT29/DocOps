from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from server.api_errors import API_ERROR_RESPONSES, register_exception_handlers


class SecretPayload(BaseModel):
    password: str


def _test_app() -> FastAPI:
    app = FastAPI(responses=API_ERROR_RESPONSES)
    register_exception_handlers(app)

    @app.get("/missing")
    def missing():
        raise HTTPException(status_code=404, detail="Không tìm thấy")

    @app.get("/duplicate")
    def duplicate():
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_submission", "message": "Bị trùng"},
        )

    @app.get("/limited")
    def limited():
        raise HTTPException(
            status_code=429,
            detail="Thử lại sau",
            headers={"Retry-After": "30"},
        )

    @app.post("/validate")
    def validate(payload: SecretPayload):
        return payload

    @app.get("/broken")
    def broken():
        raise RuntimeError("database password must not leak")

    return app


def test_http_exception_uses_consistent_error_contract():
    response = TestClient(_test_app()).get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "status": "error",
        "message": "Không tìm thấy",
        "detail": "Không tìm thấy",
    }


def test_structured_http_detail_is_preserved_for_existing_clients():
    response = TestClient(_test_app()).get("/duplicate")

    assert response.status_code == 409
    assert response.json()["message"] == "Bị trùng"
    assert response.json()["detail"] == {
        "code": "duplicate_submission",
        "message": "Bị trùng",
    }


def test_http_exception_headers_are_preserved():
    response = TestClient(_test_app()).get("/limited")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"


def test_validation_error_omits_submitted_values():
    response = TestClient(_test_app()).post(
        "/validate",
        json={"password": ["plain-text-secret"]},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Dữ liệu yêu cầu không hợp lệ"
    assert body["detail"][0]["loc"] == ["body", "password"]
    assert "input" not in body["detail"][0]
    assert "plain-text-secret" not in response.text


def test_unhandled_error_is_logged_without_leaking_detail(caplog):
    with caplog.at_level("ERROR", logger="server"):
        response = TestClient(
            _test_app(),
            raise_server_exceptions=False,
        ).get("/broken")

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "Lỗi máy chủ nội bộ",
        "detail": None,
    }
    assert "database password must not leak" not in response.text
    assert "Unhandled request exception" in caplog.text
    error_record = next(record for record in caplog.records if record.name == "server")
    assert error_record.error_type == "RuntimeError"
    assert "/broken" not in caplog.text
    assert "database password must not leak" not in caplog.text


def test_openapi_documents_the_shared_error_schema():
    responses = _test_app().openapi()["paths"]["/missing"]["get"]["responses"]

    for status_code in API_ERROR_RESPONSES:
        assert str(status_code) in responses
