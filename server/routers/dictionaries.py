from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database import get_db
from server.models import Dictionary, DictionaryItem
from server.repositories import DictionaryRepository
from server.routers.auth import get_admin_user
import re
from typing import Literal

# Router for /api/templates/{id}/dictionaries
template_dict_router = APIRouter(prefix="/api/templates", tags=["dictionaries"])

MAX_BULK_DICTIONARY_LINES = 5000


class BulkDictionaryItemsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)
    duplicate_mode: Literal["skip", "update"] = "skip"


def _parse_bulk_dictionary_items(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    if len(lines) > MAX_BULK_DICTIONARY_LINES:
        raise HTTPException(
            status_code=400,
            detail=f"Mỗi lần chỉ được nhập tối đa {MAX_BULK_DICTIONARY_LINES} dòng",
        )

    items = []
    errors = []
    seen_codes = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        match = re.match(r"^(.*?)\s+-\s+(.+?)$", line)
        if match:
            code, value = match.group(1).strip(), match.group(2).strip()
        elif "\t" in line:
            code, value = (part.strip() for part in line.split("\t", 1))
        else:
            errors.append(f"Dòng {line_number}: cần định dạng 'id - value'")
            continue

        if not code:
            errors.append(f"Dòng {line_number}: id không được để trống")
            continue
        if not value:
            errors.append(f"Dòng {line_number}: value không được để trống")
            continue
        if len(code) > 50:
            errors.append(f"Dòng {line_number}: id vượt quá 50 ký tự")
            continue
        if len(value) > 255:
            errors.append(f"Dòng {line_number}: value vượt quá 255 ký tự")
            continue

        normalized_code = code.casefold()
        if normalized_code in seen_codes:
            errors.append(
                f"Dòng {line_number}: id '{code}' bị trùng với dòng "
                f"{seen_codes[normalized_code]}"
            )
            continue
        seen_codes[normalized_code] = line_number
        items.append((code, value))

    if not items and not errors:
        errors.append("Không có dữ liệu để nhập")
    if errors:
        shown_errors = "; ".join(errors[:20])
        if len(errors) > 20:
            shown_errors += f"; và {len(errors) - 20} lỗi khác"
        raise HTTPException(status_code=400, detail=shown_errors)
    return items

@template_dict_router.get("/{template_id}/dictionaries")
def get_dictionaries(template_id: int, db: Session = Depends(get_db)):
    dicts = DictionaryRepository(db).list_for_template(template_id)
    result = [{"id": d.id, "name": d.name, "description": d.description} for d in dicts]
    return {"status": "ok", "data": result}

@template_dict_router.post("/{template_id}/dictionaries")
def create_dictionary(template_id: int, data: dict, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    name = data.get("name")
    description = data.get("description", name)
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    repository = DictionaryRepository(db)
    existing = repository.find_for_template(template_id, name)
    if existing:
        raise HTTPException(status_code=400, detail="Dictionary already exists for this template")
    new_dict = Dictionary(template_id=template_id, name=name, description=description)
    repository.add(new_dict)
    db.commit()
    db.refresh(new_dict)
    return {"status": "ok", "id": new_dict.id}


@template_dict_router.post("/{template_id}/dictionaries/{dict_id}/items/bulk")
def bulk_import_dictionary_items(
    template_id: int,
    dict_id: int,
    request: BulkDictionaryItemsRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    repository = DictionaryRepository(db)
    dictionary = repository.get_for_template(dict_id, template_id)
    if not dictionary:
        raise HTTPException(
            status_code=404,
            detail="Từ điển không thuộc biểu mẫu đang chọn",
        )

    parsed_items = _parse_bulk_dictionary_items(request.text)
    existing_items = repository.list_items(dict_id)
    existing_by_code = {}
    for item in existing_items:
        if item.code:
            existing_by_code.setdefault(item.code.strip().casefold(), item)

    added = 0
    updated = 0
    skipped = 0
    for code, value in parsed_items:
        existing = existing_by_code.get(code.casefold())
        if existing:
            if request.duplicate_mode == "update" and existing.value != value:
                existing.value = value
                updated += 1
            else:
                skipped += 1
            continue

        new_item = DictionaryItem(
            dictionary_id=dict_id,
            code=code,
            value=value,
        )
        repository.add_item(new_item)
        existing_by_code[code.casefold()] = new_item
        added += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Không thể lưu dữ liệu từ điển")

    return {
        "status": "ok",
        "data": {
            "dictionary_id": dict_id,
            "template_id": template_id,
            "parsed": len(parsed_items),
            "added": added,
            "updated": updated,
            "skipped": skipped,
        },
    }


# Router for /api/dictionaries/{id}/...
router = APIRouter(prefix="/api/dictionaries", tags=["dictionaries"])

@router.get("/{dict_id}/items")
def get_dictionary_items(dict_id: int, db: Session = Depends(get_db)):
    repository = DictionaryRepository(db)
    dictionary = repository.get_dictionary(dict_id)
    if not dictionary:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    items = repository.list_items(dict_id)
    result = [{"id": item.id, "code": item.code, "value": item.value} for item in items]
    return {"status": "ok", "data": result}

@router.post("/{dict_id}/items")
def create_dictionary_item(dict_id: int, data: dict, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    code = data.get("code")
    value = data.get("value")
    if not value:
        raise HTTPException(status_code=400, detail="Value is required")
    repository = DictionaryRepository(db)
    dictionary = repository.get_dictionary(dict_id)
    if not dictionary:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    new_item = DictionaryItem(dictionary_id=dict_id, code=code, value=value)
    repository.add_item(new_item)
    db.commit()
    db.refresh(new_item)
    return {"status": "ok", "id": new_item.id}

@router.delete("/{dict_id}")
def delete_dictionary(dict_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    repository = DictionaryRepository(db)
    dictionary = repository.get_dictionary(dict_id)
    if not dictionary:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    repository.delete(dictionary)
    db.commit()
    return {"status": "ok"}

@router.delete("/items/{item_id}")
def delete_dictionary_item(item_id: int, current_user: dict = Depends(get_admin_user), db: Session = Depends(get_db)):
    repository = DictionaryRepository(db)
    item = repository.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    repository.delete_item(item)
    db.commit()
    return {"status": "ok"}
