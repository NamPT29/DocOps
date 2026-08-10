from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from server.database import get_db
from server.models import Dictionary, DictionaryItem
from server.routers.auth import get_admin_user
import os

# Router for /api/templates/{id}/dictionaries
template_dict_router = APIRouter(prefix="/api/templates", tags=["dictionaries"])

@template_dict_router.get("/{template_id}/dictionaries")
def get_dictionaries(template_id: int, db: Session = Depends(get_db)):
    dicts = db.query(Dictionary).filter(Dictionary.template_id == template_id).all()
    result = [{"id": d.id, "name": d.name, "description": d.description} for d in dicts]
    return {"status": "ok", "data": result}

@template_dict_router.post("/{template_id}/dictionaries")
def create_dictionary(template_id: int, data: dict, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    name = data.get("name")
    description = data.get("description", name)
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    existing = db.query(Dictionary).filter(Dictionary.template_id == template_id, Dictionary.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Dictionary already exists for this template")
    new_dict = Dictionary(template_id=template_id, name=name, description=description)
    db.add(new_dict)
    db.commit()
    db.refresh(new_dict)
    return {"status": "ok", "id": new_dict.id}


# Router for /api/dictionaries/{id}/...
router = APIRouter(prefix="/api/dictionaries", tags=["dictionaries"])

@router.get("/{dict_id}/items")
def get_dictionary_items(dict_id: int, db: Session = Depends(get_db)):
    dictionary = db.query(Dictionary).filter(Dictionary.id == dict_id).first()
    if not dictionary:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    items = db.query(DictionaryItem).filter(DictionaryItem.dictionary_id == dict_id).order_by(DictionaryItem.id).all()
    result = [{"id": item.id, "code": item.code, "value": item.value} for item in items]
    return {"status": "ok", "data": result}

@router.post("/{dict_id}/items")
def create_dictionary_item(dict_id: int, data: dict, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    code = data.get("code")
    value = data.get("value")
    if not value:
        raise HTTPException(status_code=400, detail="Value is required")
    dictionary = db.query(Dictionary).filter(Dictionary.id == dict_id).first()
    if not dictionary:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    new_item = DictionaryItem(dictionary_id=dict_id, code=code, value=value)
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return {"status": "ok", "id": new_item.id}

@router.delete("/{dict_id}")
def delete_dictionary(dict_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    dictionary = db.query(Dictionary).filter(Dictionary.id == dict_id).first()
    if not dictionary:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    db.delete(dictionary)
    db.commit()
    return {"status": "ok"}

@router.delete("/items/{item_id}")
def delete_dictionary_item(item_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    item = db.query(DictionaryItem).filter(DictionaryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"status": "ok"}
