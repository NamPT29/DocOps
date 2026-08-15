import os
import uuid
import zipfile

from fastapi import HTTPException, UploadFile


DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


def _is_supported_document(extension: str, header: bytes) -> bool:
    if extension == ".pdf":
        return header.startswith(b"%PDF-")
    if extension == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if extension == ".webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    return False


def _is_supported_excel(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def save_validated_upload(
    upload: UploadFile,
    destination: str,
    *,
    kind: str,
    max_bytes: int | None = None,
) -> str:
    original_filename = os.path.basename(upload.filename or "")
    if not original_filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ")

    extension = os.path.splitext(original_filename)[1].lower()
    allowed = DOCUMENT_EXTENSIONS if kind == "document" else EXCEL_EXTENSIONS
    if extension not in allowed:
        expected = "PDF hoặc ảnh PNG/JPEG/WebP" if kind == "document" else "Excel .xlsx hoặc .xlsm"
        raise HTTPException(status_code=400, detail=f"Chỉ hỗ trợ file {expected}")

    directory = os.path.dirname(destination) or "."
    os.makedirs(directory, exist_ok=True)
    temporary_path = f"{destination}.{uuid.uuid4().hex}.part"
    header = b""
    total = 0

    try:
        upload.file.seek(0)
        with open(temporary_path, "xb") as output:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                if len(header) < 32:
                    header += chunk[: 32 - len(header)]
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File vượt quá giới hạn {max_bytes // (1024 * 1024)} MB",
                    )
                output.write(chunk)

        if total == 0:
            raise HTTPException(status_code=400, detail="File rỗng")
        if kind == "document" and not _is_supported_document(extension, header):
            raise HTTPException(status_code=400, detail="Nội dung file không đúng định dạng")
        if kind == "excel" and not _is_supported_excel(temporary_path):
            raise HTTPException(status_code=400, detail="File Excel không hợp lệ")

        os.replace(temporary_path, destination)
        return original_filename
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise
