import os
import shutil
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from server.database import get_db
from server.models import Template
from server.routers.auth import get_admin_user
from server.services.excel_service import get_form_schema, get_ma_xa_mapping, get_don_vi_do_mapping

router = APIRouter(prefix="/api/templates", tags=["templates"])

TEMPLATES_DIR = "templates"
os.makedirs(TEMPLATES_DIR, exist_ok=True)

@router.post("")
def upload_template(file: UploadFile = File(...), current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    file_path = os.path.join(TEMPLATES_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    template = db.query(Template).filter(Template.filename == file.filename).first()
    if not template:
        template = Template(name=file.filename, filename=file.filename)
        db.add(template)
    else:
        template.is_active = True
        
    db.commit()
    db.refresh(template)
    return {"status": "ok", "data": {"id": template.id, "name": template.name}}

@router.get("")
def get_templates(db: Session = Depends(get_db)):
    templates = db.query(Template).filter(Template.is_active == True).all()
    return {"status": "ok", "data": [{"id": t.id, "name": t.name, "filename": t.filename} for t in templates]}

@router.get("/{template_id}/schema")
async def get_template_schema(template_id: int, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        return {"status": "error", "message": "Template not found"}
    
    file_path = os.path.join(TEMPLATES_DIR, template.filename)
    try:
        schema = await run_in_threadpool(get_form_schema, file_path)
        return {"status": "ok", "data": schema}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/{template_id}/maxa_mapping")
async def get_template_maxa_mapping(template_id: int, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        return {"status": "error", "message": "Template not found"}
    file_path = os.path.join(TEMPLATES_DIR, template.filename)
    try:
        mapping = await run_in_threadpool(get_ma_xa_mapping, file_path)
        return {"status": "ok", "data": mapping}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/{template_id}/don_vi_do_mapping")
async def get_template_don_vi_do_mapping(template_id: int, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        return {"status": "error", "message": "Template not found"}
    file_path = os.path.join(TEMPLATES_DIR, template.filename)
    try:
        mapping = await run_in_threadpool(get_don_vi_do_mapping, file_path)
        return {"status": "ok", "data": mapping}
    except Exception as e:
        return {"status": "error", "message": str(e)}
