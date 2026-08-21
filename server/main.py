import os
import logging
import logging.handlers
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Environment-backed settings must be available before database/auth modules import.
load_dotenv()
from server.settings import settings
from server.security_headers import SecurityHeadersMiddleware

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Root logger — captures all loggers (uvicorn, sqlalchemy, app routers, etc.)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Formatter with timestamp, level, module, and message
_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# File handler — ERROR+ only, rotates at 5 MB, keeps 5 backups
_error_file = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "error.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_error_file.setLevel(logging.ERROR)
_error_file.setFormatter(_fmt)
root_logger.addHandler(_error_file)

# File handler — ALL levels, for full audit trail
_all_file = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"),
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_all_file.setLevel(logging.INFO)
_all_file.setFormatter(_fmt)
root_logger.addHandler(_all_file)

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

Base.metadata.create_all(bind=engine)
ensure_submission_metadata_schema(engine)
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

app = FastAPI(title="Số hóa All in One")

# ---------------------------------------------------------------------------
# Global exception handler — catches any unhandled error in API endpoints
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logger.error(
        "Unhandled exception: %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Lỗi máy chủ nội bộ"},
    )

cors_origins = list(settings.cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

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

PDF_STORAGE_PATH = str(settings.pdf_storage_path)
os.makedirs(PDF_STORAGE_PATH, exist_ok=True)

# Ensure internal upload dirs exist
os.makedirs("scratch", exist_ok=True)
os.makedirs(settings.template_storage_path, exist_ok=True)

# Mount static directories
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

@app.get("/")
def serve_index():
    return FileResponse("frontend/index.html")

@app.get("/{filename:path}")
def serve_root_files(filename: str):
    frontend_dir = Path("frontend").resolve()
    file_path = (frontend_dir / filename).resolve()
    try:
        file_path.relative_to(frontend_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.is_file():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

logger.info("Server initialized successfully")

