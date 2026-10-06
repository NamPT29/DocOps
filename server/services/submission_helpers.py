"""Small, dependency-free helpers shared by submission workflows."""

from urllib.parse import quote

from server.utils.folder_utils import NO_FOLDER_SENTINEL
import os
from fastapi import HTTPException
from fastapi.responses import FileResponse


COMPLETED_WITHOUT_FOLDER = NO_FOLDER_SENTINEL


def _pdf_url(uuid_filename: str) -> str:
    return f"/api/files/{quote(uuid_filename, safe='')}"

def create_document_file_response(document, storage_path: str):
    
    filepath = os.path.join(storage_path, document.uuid_filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File không tồn tại")

    extension = os.path.splitext(document.uuid_filename)[1].lower()
    media_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_types.get(extension)
    if not media_type:
        raise HTTPException(status_code=415, detail="Định dạng file không được hỗ trợ")

    encoded_name = quote(str(document.original_filename), safe="")
    return FileResponse(
        filepath,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
        },
    )
