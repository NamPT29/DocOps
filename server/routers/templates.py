import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from server.database import get_db
from server.models import Template
from server.routers.auth import get_admin_user
from server.services.excel_service import (
    ExcelTemplateError,
    get_don_vi_do_mapping,
    get_form_schema,
    get_ma_xa_mapping,
)
from server.services.upload_service import save_validated_upload
from server.services.template_cache_service import (
    template_artifact_cache,
    template_file_version,
)
from server.repositories import DictionaryRepository, TemplateRepository

router = APIRouter(prefix="/api/templates", tags=["templates"])
TEMPLATES_DIR = "templates"
os.makedirs(TEMPLATES_DIR, exist_ok=True)

@router.post("")
def upload_template(file: UploadFile = File(...), current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    filename = os.path.basename(file.filename or "")
    if os.path.splitext(filename)[1].lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file Excel .xlsx hoặc .xlsm")

    file_path = os.path.join(TEMPLATES_DIR, filename)
    staging_path = f"{file_path}.{uuid.uuid4().hex}.upload"
    backup_path = None
    installed = False

    try:
        repository = TemplateRepository(db)
        save_validated_upload(file, staging_path, kind="excel")
        template = repository.get_by_filename(filename)
        if not template:
            template = Template(name=filename, filename=filename)
            repository.add(template)
        else:
            template.is_active = True
        db.flush()

        if os.path.exists(file_path):
            backup_path = f"{file_path}.{uuid.uuid4().hex}.backup"
            os.replace(file_path, backup_path)
        os.replace(staging_path, file_path)
        installed = True

        db.commit()
        from server.routers.processing import invalidate_mappings
        invalidate_mappings(template.id)
        if backup_path and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass
        return {"status": "ok", "data": {"id": template.id, "name": template.name}}
    except HTTPException:
        db.rollback()
        if installed and os.path.exists(file_path):
            os.remove(file_path)
        if backup_path and os.path.exists(backup_path):
            os.replace(backup_path, file_path)
        if os.path.exists(staging_path):
            os.remove(staging_path)
        raise
    except Exception:
        db.rollback()
        if installed and os.path.exists(file_path):
            os.remove(file_path)
        if backup_path and os.path.exists(backup_path):
            os.replace(backup_path, file_path)
        if os.path.exists(staging_path):
            os.remove(staging_path)
        raise HTTPException(status_code=500, detail="Không thể lưu biểu mẫu")

@router.get("")
def get_templates(db: Session = Depends(get_db)):
    templates = TemplateRepository(db).list_active()
    return {"status": "ok", "data": [{"id": t.id, "name": t.name, "filename": t.filename} for t in templates]}

@router.get("/{template_id}/schema")
async def get_template_schema(template_id: int, db: Session = Depends(get_db)):
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    file_path = os.path.join(TEMPLATES_DIR, template.filename)
    file_version = template_file_version(file_path)
    
    import json
    config = {}
    if template.config_json:
        try:
            config = json.loads(template.config_json)
        except:
            pass
            
    cached = await run_in_threadpool(
        template_artifact_cache.get,
        "schema",
        template_id,
        file_version,
    )
    if cached is not None:
        return cached

    # Use a fresh DB read after shared invalidation; another worker's local
    # dictionary cache may still hold values from before the edit.
    dicts = DictionaryRepository(db).fresh_option_map_for_template(template_id)
    try:
        schema = await run_in_threadpool(get_form_schema, file_path, dicts, config)
    except ExcelTemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = {"status": "ok", "data": schema, "config": config}
    await run_in_threadpool(
        template_artifact_cache.set,
        "schema",
        template_id,
        file_version,
        response,
    )
    return response

@router.get("/{template_id}/maxa_mapping")
async def get_template_maxa_mapping(template_id: int, db: Session = Depends(get_db)):
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    file_path = os.path.join(TEMPLATES_DIR, template.filename)
    file_version = template_file_version(file_path)
    mapping = await run_in_threadpool(
        template_artifact_cache.get_or_compute,
        "maxa_mapping",
        template_id,
        file_version,
        lambda: get_ma_xa_mapping(file_path),
    )
    return {"status": "ok", "data": mapping}

@router.get("/{template_id}/don_vi_do_mapping")
async def get_template_don_vi_do_mapping(template_id: int, db: Session = Depends(get_db)):
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    file_path = os.path.join(TEMPLATES_DIR, template.filename)
    file_version = template_file_version(file_path)
    mapping = await run_in_threadpool(
        template_artifact_cache.get_or_compute,
        "don_vi_do_mapping",
        template_id,
        file_version,
        lambda: get_don_vi_do_mapping(file_path),
    )
    return {"status": "ok", "data": mapping}

@router.get("/{template_id}/config")
def get_template_config(template_id: int, db: Session = Depends(get_db)):
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    import json
    config = {}
    if template.config_json:
        try:
            config = json.loads(template.config_json)
        except:
            pass
            
    return {"status": "ok", "data": config}

@router.post("/{template_id}/config")
def save_template_config(template_id: int, data: dict, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    import json
    template.config_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    template_artifact_cache.invalidate(template_id)
    
    return {"status": "ok"}

@router.delete("/{template_id}")
def delete_template(template_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    # Soft-delete: mark inactive instead of actual removal to preserve references
    template.is_active = False
    db.commit()
    return {"status": "ok"}
