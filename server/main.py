import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from dotenv import load_dotenv
from sqlalchemy import text

# Environment-backed settings must be available before database/auth modules import.
load_dotenv()
from server.settings import settings
from server.api_errors import API_ERROR_RESPONSES, register_exception_handlers
from server.logging_config import configure_logging
from server.frontend_static import PublicFrontendStaticFiles, resolve_public_frontend_file
from server.http_middleware import configure_http_middleware
from server.openapi import configure_openapi
from server.release_info import APP_VERSION
from server.migration_runner import migration_state
from server.services.export_job_service import cleanup_stale_export_jobs
from server.services.project_upload_service import cleanup_stale_project_uploads

configure_logging(
    settings.log_dir,
    level=settings.log_level,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)
logger = logging.getLogger("server")


def run_startup_maintenance() -> None:
    try:
        result = cleanup_stale_export_jobs()
    except Exception:
        logger.warning("Không thể dọn tác vụ xuất cũ khi khởi động", exc_info=True)
    else:
        logger.info(
            "Dọn tác vụ xuất khi khởi động: cleaned=%d skipped=%d errors=%d",
            result["cleaned"],
            result["skipped"],
            result["errors"],
        )

    try:
        state = migration_state(engine)
        if not state.ready:
            logger.warning("Bỏ qua dọn phiên upload vì database chưa migrate")
            return
        with SessionLocal() as db:
            upload_result = cleanup_stale_project_uploads(db)
    except Exception:
        logger.warning("Không thể dọn phiên upload cũ khi khởi động", exc_info=True)
        return
    logger.info(
        "Dọn phiên upload khi khởi động: cleaned=%d skipped=%d errors=%d",
        upload_result["cleaned"],
        upload_result["skipped"],
        upload_result["errors"],
    )


from server.database import SessionLocal, engine
from server.models import Template
from server.routers.auth import init_admin
from server.host_setup import HOST_CONFIG_PATH_ENV, consume_initial_admin_password

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


def run_database_bootstrap() -> None:
    state = migration_state(engine)
    if not state.ready:
        logger.warning(
            "Bỏ qua bootstrap dữ liệu vì database chưa migrate: current=%s expected=%s",
            state.current or "<none>",
            state.expected,
        )
        return
    init_admin()
    host_config_path = os.environ.get(HOST_CONFIG_PATH_ENV)
    if host_config_path:
        consume_initial_admin_password(host_config_path)
    seed_default_template()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_startup_maintenance()
    run_database_bootstrap()
    yield

OPENAPI_TAGS = [
    {"name": "auth", "description": "Sign-in and account administration."},
    {"name": "templates", "description": "Template management and configuration."},
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
    version=APP_VERSION,
    openapi_tags=OPENAPI_TAGS,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    responses=API_ERROR_RESPONSES,
    lifespan=lifespan,
)
register_exception_handlers(app)

configure_http_middleware(app, settings.cors_origins)

# Include routers
from server.routers import auth, templates, submissions, documents, processing, dictionaries, notifications, projects, project_uploads
app.include_router(auth.router)
app.include_router(templates.router)
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


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "live", "version": APP_VERSION}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not-ready", "version": APP_VERSION},
        )
    state = migration_state(engine)
    if not state.ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not-ready",
                "version": APP_VERSION,
                "database_revision": state.current,
                "expected_database_revision": state.expected,
            },
        )
    return {
        "status": "ready",
        "version": APP_VERSION,
        "database_revision": state.current,
    }

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

