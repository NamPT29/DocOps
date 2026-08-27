"""OpenAPI metadata that is kept separate from runtime route behavior."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


_ROUTE_SUMMARIES: dict[str, dict[str, str]] = {
    "/api/login": {"post": "Sign in and issue an access token"},
    "/api/me": {"get": "Get the current user's profile"},
    "/api/users": {"get": "List users", "post": "Create a user"},
    "/api/users/{user_id}": {"patch": "Update a user's profile", "delete": "Delete a user"},
    "/api/users/{user_id}/password": {"put": "Change a user's password"},
}


def _add_route_documentation(schema: dict[str, Any]) -> None:
    paths = schema.get("paths", {})
    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            summary = _ROUTE_SUMMARIES.get(path, {}).get(method)
            if summary:
                operation["summary"] = summary

            # Every API route except login is authenticated by the existing
            # dependency chain. Keep this documentation-only; runtime auth
            # behavior remains in server.routers.auth.
            if path.startswith("/api/") and path != "/api/login":
                operation.setdefault("security", [{"BearerAuth": []}])

        if path == "/api/login":
            request_body = operations.get("post", {}).get("requestBody", {})
            content = request_body.get("content", {}) if isinstance(request_body, dict) else {}
            json_content = content.get("application/json")
            if isinstance(json_content, dict):
                json_content["examples"] = {
                    "credentials": {
                        "summary": "Example credentials",
                        "value": {
                            "username": "operator",
                            "password": "replace-with-password",
                        },
                    }
                }


def configure_openapi(app: FastAPI) -> None:
    """Install the cached OpenAPI builder used by the application instance."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT returned by POST /api/login.",
        }
        _add_route_documentation(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
