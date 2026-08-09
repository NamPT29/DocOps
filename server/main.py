import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Initialize database
from server.database import Base, engine
from server.models import Template
from server.routers.auth import init_admin
from server.database import SessionLocal
import shutil

Base.metadata.create_all(bind=engine)
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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from server.routers import auth, templates, tasks, submissions, documents
app.include_router(auth.router)
app.include_router(templates.router)
app.include_router(tasks.router)
app.include_router(submissions.router)
app.include_router(documents.router)

# Ensure upload dirs exist
os.makedirs("uploads", exist_ok=True)
os.makedirs("scratch", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Mount static directories
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def serve_index():
    return FileResponse("frontend/index.html")

@app.get("/{filename:path}")
def serve_root_files(filename: str):
    file_path = os.path.join("frontend", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"status": "error", "message": "File not found"}
