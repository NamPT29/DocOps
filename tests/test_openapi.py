from fastapi import FastAPI
from pydantic import BaseModel

from server.openapi import configure_openapi


class LoginPayload(BaseModel):
    username: str
    password: str


def test_openapi_documents_metadata_bearer_auth_and_safe_login_example():
    app = FastAPI(
        title="Số hóa All in One API",
        summary="Document digitization and review API.",
        description="Protected endpoints require a JWT access token.",
        version="1.0.0",
        openapi_tags=[{"name": "auth", "description": "Sign-in."}],
    )
    @app.post("/api/login", tags=["auth"])
    def login(payload: LoginPayload):
        return payload
    app.get("/api/me", tags=["auth"])(lambda: {"status": "ok"})
    configure_openapi(app)

    schema = app.openapi()

    assert schema["info"]["title"] == "Số hóa All in One API"
    assert schema["info"]["summary"] == "Document digitization and review API."
    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT returned by POST /api/login.",
    }
    assert "security" not in schema["paths"]["/api/login"]["post"]
    assert schema["paths"]["/api/me"]["get"]["security"] == [{"BearerAuth": []}]
    example = schema["paths"]["/api/login"]["post"]["requestBody"]["content"]["application/json"]["examples"]
    assert example["credentials"]["value"]["password"] == "replace-with-password"
