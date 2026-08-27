import os
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Environment-backed settings must be available before database/auth modules import.
load_dotenv()
from server.settings import settings
from server.api_errors import API_ERROR_RESPONSES, register_exception_handlers
from server.logging_config import RequestLoggingMiddleware, configure_logging
from server.frontend_static import PublicFrontendStaticFiles, resolve_public_frontend_file
from server.security_headers import SecurityHeadersMiddleware
from server.openapi import configure_openapi

configure_logging(
    settings.log_dir,
    level=settings.log_level,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)
logger = logging.getLogger("server")

# Initialize database
from server.database import Base, engine
from server.models import Template, Dictionary, DictionaryItem
from server.routers.auth import init_admin
from server.database import SessionLocal
from server.services.submission_metadata_service import (
    backfill_submission_metadata,
    ensure_submission_metadata_schema,
)
from server.services.project_status_service import ensure_project_status_schema
from server.services.submission_status_service import ensure_submission_status_schema
from server.services.user_profile_service import ensure_user_profile_schema

Base.metadata.create_all(bind=engine)
ensure_user_profile_schema(engine)
ensure_submission_metadata_schema(engine)
ensure_project_status_schema(engine)
ensure_submission_status_schema(engine)
with SessionLocal() as metadata_db:
    backfill_submission_metadata(metadata_db)
init_admin()

# Seed the default template
def seed_default_template():
    db = SessionLocal()
    try:
        if not db.query(Template).first():
            # If templates dir has our default file
            if os.path.exists(os.path.join("templates", "Excel_FormMau_v5_04082026.xlsx")):
                t = Template(name="Giấy chứng nhận QSDĐ (Mẫu 1)", filename="Excel_FormMau_v5_04082026.xlsx")
                db.add(t)
                db.commit()
    finally:
        db.close()

seed_default_template()

OPENAPI_TAGS = [
    {"name": "auth", "description": "Sign-in and account administration."},
    {"name": "templates", "description": "Template management and configuration."},
    {"name": "tasks", "description": "Background processing tasks."},
    {"name": "submissions", "description": "Submission intake, review, and export."},
    {"name": "documents", "description": "Document and folder operations."},
    {"name": "processing", "description": "Template field processing."},
    {"name": "dictionaries", "description": "Dictionary and lookup data."},
    {"name": "notifications", "description": "User notifications."},
    {"name": "projects", "description": "Project and membership management."},
    {"name": "project-uploads", "description": "Chunked project asset uploads."},
]

app = FastAPI(
    title="Số hóa All in One API",
    summary="Document digitization and review API.",
    description=(
        "API for digitizing documents, completing structured submissions, and managing review workflows. "
        "Protected endpoints require a JWT access token in the Authorization bearer header."
    ),
    version="1.0.0",
    openapi_tags=OPENAPI_TAGS,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    responses=API_ERROR_RESPONSES,
)
register_exception_handlers(app)

cors_origins = list(settings.cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# Include routers
from server.routers import auth, templates, tasks, submissions, documents, processing, dictionaries, notifications, projects, project_uploads
app.include_router(auth.router)
app.include_router(templates.router)
app.include_router(tasks.router)
app.include_router(submissions.router)
app.include_router(documents.router)
app.include_router(processing.router)
app.include_router(dictionaries.template_dict_router)
app.include_router(dictionaries.router)
app.include_router(notifications.router)
app.include_router(projects.router)
app.include_router(project_uploads.router)
configure_openapi(app)

PDF_STORAGE_PATH = str(settings.pdf_storage_path)
os.makedirs(PDF_STORAGE_PATH, exist_ok=True)

# Ensure internal upload dirs exist
os.makedirs("scratch", exist_ok=True)
os.makedirs(settings.template_storage_path, exist_ok=True)

# Mount static directories
app.mount("/frontend", PublicFrontendStaticFiles(directory="frontend"), name="frontend")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

@app.get("/")
def serve_index():
    return FileResponse("frontend/index.html")

@app.get("/{filename:path}")
def serve_root_files(filename: str):
    file_path = resolve_public_frontend_file(Path("frontend"), filename)
    if file_path is not None:
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

logger.info("Server initialized successfully")

