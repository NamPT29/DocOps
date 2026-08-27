# API documentation

The FastAPI Swagger UI, ReDoc, and `/openapi.json` routes are disabled by
default. Enable them only when they are intentionally placed behind a private
network or an authenticated gateway:

```env
API_DOCS_ENABLED=true
```

The generated schema documents `BearerAuth` (JWT) for API routes that require
the existing application authentication dependency. The login route remains
public and accepts credentials in the request body.
