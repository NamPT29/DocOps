from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os

from server.database import get_db
from server.services.excel_service import get_ma_xa_mapping, get_don_vi_do_mapping
from server.services.address_service import process_address
from server.routers.auth import get_current_user
from server.repositories import TemplateRepository

router = APIRouter(prefix="/api/templates", tags=["processing"])
class ProcessFieldRequest(BaseModel):
    field_name: str
    value: str

# In-memory cache to avoid reading Excel file on every keystroke
MAPPING_CACHE = {}


def invalidate_mappings(template_id: int) -> None:
    MAPPING_CACHE.pop(template_id, None)


def get_mappings(template_id: int, db: Session):
    if template_id in MAPPING_CACHE:
        return MAPPING_CACHE[template_id]
        
    template = TemplateRepository(db).get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    file_path = os.path.join("templates", template.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Template file not found")
        
    ma_xa = get_ma_xa_mapping(file_path)
    don_vi = get_don_vi_do_mapping(file_path)
    
    MAPPING_CACHE[template_id] = {
        "ma_xa": ma_xa,
        "don_vi": don_vi
    }
    return MAPPING_CACHE[template_id]

@router.post("/{template_id}/process-field")
def api_process_field(template_id: int, req: ProcessFieldRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    mappings = get_mappings(template_id, db)

    if req.field_name in ['col_20', 'col_37', 'col_92']:
        result = process_address(
            val=req.value,
            field_name=req.field_name,
            ma_xa_mapping=mappings["ma_xa"],
            don_vi_do_mapping=mappings["don_vi"]
        )
        return {"status": "ok", "data": result}
        
    return {"status": "ok", "data": {}}
