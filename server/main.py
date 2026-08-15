import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

# Environment-backed settings must be available before database/auth modules import.
load_dotenv()

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

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from server.routers import auth, templates, tasks, submissions, documents, processing, dictionaries
app.include_router(auth.router)
app.include_router(templates.router)
app.include_router(tasks.router)
app.include_router(submissions.router)
app.include_router(documents.router)
app.include_router(processing.router)
app.include_router(dictionaries.template_dict_router)
app.include_router(dictionaries.router)

PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH", "uploads")
os.makedirs(PDF_STORAGE_PATH, exist_ok=True)

# Ensure internal upload dirs exist
os.makedirs("scratch", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Mount static directories
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

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
