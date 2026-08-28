from fastapi import FastAPI
from pydantic import BaseModel

from server.openapi import configure_openapi
from server.routers import submissions


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


def test_openapi_exposes_submission_and_export_response_contracts():
    app = FastAPI()
    app.include_router(submissions.router)
    configure_openapi(app)

    schema = app.openapi()

    update_operation = schema["paths"]["/api/submissions/{sub_id}"]["put"]
    claim_operation = schema["paths"]["/api/submissions/{sub_id}/view"]["put"]
    export_operation = schema["paths"]["/api/export-jobs"]["post"]
    status_operation = schema["paths"]["/api/export-jobs/{job_id}"]["get"]
    assert update_operation["summary"] == "Update a submission"
    assert claim_operation["summary"] == "Claim the submission view lease"
    assert export_operation["summary"] == "Start a background export job"
    assert status_operation["summary"] == "Get background export status"
    assert update_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/StatusResponse")
    assert claim_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/SubmissionViewResponse")
    assert export_operation["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("/ExportJobResponse")
