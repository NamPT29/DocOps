"""Check scan: xem từng file và trang của gói scan, so số trang với số tờ mục lục,
bôi trắng vết ghim (ghi đè file gốc).

Quy tắc (nghiệp vụ đã chốt): hồ sơ n tờ, bìa tách file riêng không đánh số, máy scan tự bỏ
trang trắng, mặt sau có chữ thì scan -> cần ít nhất n + 1 trang, nhiều nhất 2n + 1 trang.
Bôi trắng: chỉ khi Check scan của hộp đang làm, trên gói scan mới nhất; nét trắng được ghi
thêm vào nội dung trang (ảnh scan không bị nén lại), file gốc bị thay bằng file mới.
"""
import hashlib
import io
import logging
import os
import re
import threading
from pathlib import Path

import pypdf
from fastapi import HTTPException
from pypdf.generic import DecodedStreamObject

from server.repositories.scan_repository import (
    get_case_by_id,
    get_case_catalog_rows,
    get_scan_package,
    get_scan_package_file,
    list_scan_package_files,
    list_scan_packages,
)
from server.repositories.workflow_repository import WorkflowRepository
from server.services.arrangement_catalog_parser import CatalogValueError, parse_dossier_number
from server.services.server_folder_service import resolve_server_source_directory

audit_logger = logging.getLogger("server.audit.scan_whiteout")
_WRITE_LOCK = threading.Lock()

MAX_STROKES = 300
MAX_POINTS_PER_STROKE = 2000
MAX_STROKE_WIDTH = 0.2


def _is_cover(name: str) -> bool:
    return "bia" in name.lower()


def dossier_page_status(sheets, pages, unknown):
    """Trạng thái số trang của một hồ sơ: ok, missing, over, unknown, no_catalog."""
    if not isinstance(sheets, int) or sheets < 1:
        return "no_catalog", None, None
    minimum, maximum = sheets + 1, 2 * sheets + 1
    if unknown:
        return "unknown", minimum, maximum
    if pages < minimum:
        return "missing", minimum, maximum
    if pages > maximum:
        return "over", minimum, maximum
    return "ok", minimum, maximum


def _package_for_case(db, project_id, case_id, package_id):
    case = get_case_by_id(db, project_id, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Hộp không thuộc dự án này hoặc không tồn tại.")
    pkg = get_scan_package(db, package_id)
    if not pkg or pkg.case_id != case.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy gói scan của hộp.")
    return pkg


def get_scan_check_view(db, *, project_id, case_id, package_id, actor=None):
    pkg = _package_for_case(db, project_id, case_id, package_id)
    sheets_by_key = {}
    for row in get_case_catalog_rows(db, case_id):
        sheets_by_key[(row.dossier_number, row.dossier_suffix)] = row.sheet_count

    folders, misplaced = {}, []
    for scan_file in list_scan_package_files(db, pkg.id):
        parts = scan_file.relative_path.strip("/").split("/")
        item = {
            "id": scan_file.id,
            "name": parts[-1],
            "relative_path": scan_file.relative_path,
            "page_count": scan_file.page_count,
            "status": scan_file.status,
            "is_pdf": bool(scan_file.is_pdf),
            "is_cover": _is_cover(parts[-1]),
        }
        if len(parts) != 2:
            misplaced.append(item)
            continue
        folders.setdefault(parts[0], []).append(item)

    dossiers = []
    for folder, files in folders.items():
        try:
            key = parse_dossier_number(folder)
        except CatalogValueError:
            key = None
        files.sort(key=lambda f: (not f["is_cover"], _natural_key(f["name"])))
        pdfs = [f for f in files if f["is_pdf"]]
        unknown = any(f["page_count"] < 1 for f in pdfs)
        pages = sum(f["page_count"] for f in pdfs if f["page_count"] > 0)
        sheets = sheets_by_key.get(key) if key else None
        status, minimum, maximum = dossier_page_status(sheets, pages, unknown)
        dossiers.append({
            "folder": folder,
            "sheets": sheets,
            "min_pages": minimum,
            "max_pages": maximum,
            "pages": pages,
            "status": status,
            "has_cover": any(f["is_cover"] for f in pdfs),
            "files": files,
            "_sort": (key or (10 ** 9, folder)),
        })
    dossiers.sort(key=lambda d: d.pop("_sort"))
    edit_block = whiteout_block_reason(db, project_id=project_id, pkg=pkg, actor=actor) if actor else (403, "")
    return {
        "package": {"id": pkg.id, "version": pkg.version, "status": pkg.status},
        "dossiers": dossiers,
        "misplaced_files": misplaced,
        "can_whiteout": edit_block is None,
        "whiteout_hint": edit_block[1] if edit_block else "",
    }


def _natural_key(name):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def resolve_scan_file(db, *, project_id, case_id, package_id, file_id) -> Path:
    pkg = _package_for_case(db, project_id, case_id, package_id)
    scan_file = get_scan_package_file(db, pkg.id, file_id)
    if not scan_file or not scan_file.is_pdf:
        raise HTTPException(status_code=404, detail="Không tìm thấy file PDF trong gói scan.")
    _, source_dir, _ = resolve_server_source_directory(pkg.source_path)
    target = source_dir.joinpath(*Path(scan_file.relative_path).parts).resolve()
    try:
        target.relative_to(source_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn file nằm ngoài thư mục gói scan.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File không còn trong thư mục scan trên máy chủ.")
    return target


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Bôi trắng vết ghim -----------------------------------------------------------


def whiteout_block_reason(db, *, project_id, pkg, actor):
    """None khi người này được bôi trắng gói này; nếu không, (mã HTTP, lý do)."""
    packages = list_scan_packages(db, pkg.case_id)
    if not packages or packages[0].id != pkg.id:
        return 409, "Chỉ bôi trắng trên gói scan mới nhất của hộp."
    if pkg.status != "done":
        return 409, "Gói scan chưa xử lý xong."
    repository = WorkflowRepository(db)
    state = repository.get_state(pkg.case_id, "scan_qc")
    if state is None or state.status != "in_progress":
        return 409, "Bấm Bắt đầu Check scan của hộp trước khi bôi trắng."
    if actor.get("role") == "admin":
        return None
    if not repository.user_is_stage_member(project_id, actor["id"], "scan_qc"):
        return 403, "Chỉ người check scan của dự án được bôi trắng."
    if state.assigned_user_id not in (None, actor["id"]):
        return 403, "Hộp đang được người khác check scan."
    return None


def to_pdf_point(u, v, box, rotation):
    """Điểm (u, v) trên trang đang hiển thị (0..1, gốc trên trái) -> tọa độ PDF của trang."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    rotation %= 360
    if rotation == 90:
        return x0 + v * width, y0 + u * height
    if rotation == 180:
        return x1 - u * width, y0 + v * height
    if rotation == 270:
        return x1 - v * width, y1 - u * height
    return x0 + u * width, y1 - v * height


def _number(value, *, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=400, detail=f"{label} phải là số.")
    value = float(value)
    if not (low <= value <= high):
        raise HTTPException(status_code=400, detail=f"{label} nằm ngoài khoảng cho phép.")
    return value


def _clean_strokes(strokes):
    if not isinstance(strokes, list) or not strokes:
        raise HTTPException(status_code=400, detail="Chưa có nét bôi nào.")
    if len(strokes) > MAX_STROKES:
        raise HTTPException(status_code=400, detail=f"Mỗi lần lưu tối đa {MAX_STROKES} nét.")
    cleaned = []
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise HTTPException(status_code=400, detail="Nét bôi không hợp lệ.")
        width = _number(stroke.get("width"), low=0.001, high=MAX_STROKE_WIDTH, label="Độ rộng nét")
        points = stroke.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS_PER_STROKE:
            raise HTTPException(status_code=400, detail="Nét bôi phải có từ 1 đến 2000 điểm.")
        pairs = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise HTTPException(status_code=400, detail="Điểm của nét bôi không hợp lệ.")
            pairs.append((
                _number(point[0], low=0, high=1, label="Tọa độ"),
                _number(point[1], low=0, high=1, label="Tọa độ"),
            ))
        cleaned.append((width, pairs))
    return cleaned


def whiteout_operations(strokes, box, rotation):
    """Lệnh PDF vẽ các nét trắng, đầu tròn, trong hệ tọa độ của trang."""
    x0, y0, x1, y1 = box
    shown_width = (y1 - y0) if rotation % 180 == 90 else (x1 - x0)
    lines = ["q", "1 1 1 RG", "1 J", "1 j"]
    for width, points in strokes:
        lines.append(f"{width * shown_width:.2f} w")
        first = to_pdf_point(*points[0], box, rotation)
        lines.append(f"{first[0]:.2f} {first[1]:.2f} m")
        for u, v in (points[1:] or points[:1]):
            x, y = to_pdf_point(u, v, box, rotation)
            lines.append(f"{x:.2f} {y:.2f} l")
        lines.append("S")
    lines.append("Q")
    return ("\n".join(lines) + "\n").encode("ascii")


def whiteout_scan_page(db, *, project_id, case_id, package_id, file_id, actor, page, base_sha256, strokes):
    pkg = _package_for_case(db, project_id, case_id, package_id)
    block = whiteout_block_reason(db, project_id=project_id, pkg=pkg, actor=actor)
    if block:
        raise HTTPException(status_code=block[0], detail=block[1])
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise HTTPException(status_code=400, detail="Số trang không hợp lệ.")
    cleaned = _clean_strokes(strokes)
    target = resolve_scan_file(db, project_id=project_id, case_id=case_id, package_id=package_id, file_id=file_id)
    scan_file = get_scan_package_file(db, pkg.id, file_id)

    with _WRITE_LOCK:
        original = target.read_bytes()
        before = hashlib.sha256(original).hexdigest()
        if before != str(base_sha256 or ""):
            raise HTTPException(
                status_code=409,
                detail="File đã thay đổi kể từ lúc mở (có người vừa lưu). Hãy mở lại file rồi bôi tiếp.",
            )
        try:
            reader = pypdf.PdfReader(io.BytesIO(original), strict=False)
            if reader.is_encrypted:
                raise ValueError("File PDF bị mã hóa.")
            page_total = len(reader.pages)
            if page > page_total:
                raise HTTPException(status_code=400, detail=f"File chỉ có {page_total} trang.")
            writer = pypdf.PdfWriter(clone_from=reader)
            pdf_page = writer.pages[page - 1]
            crop = pdf_page.cropbox
            box = (float(crop.left), float(crop.bottom), float(crop.right), float(crop.top))
            current = pdf_page.get_contents()
            body = current.get_data() if current is not None else b""
            content = DecodedStreamObject()
            content.set_data(b"q\n" + body + b"\nQ\n" + whiteout_operations(cleaned, box, pdf_page.rotation))
            pdf_page.replace_contents(content)
            pdf_page.compress_content_streams()
            output = io.BytesIO()
            writer.write(output)
            data = output.getvalue()
            if len(pypdf.PdfReader(io.BytesIO(data), strict=False).pages) != page_total:
                raise ValueError("Số trang sau khi ghi không khớp.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Không ghi được PDF: {exc}")

        temporary = target.with_name(f".{target.name}.docops-tmp")
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except OSError:
            raise HTTPException(
                status_code=409,
                detail="Không ghi đè được file (file đang mở ở máy khác hoặc không có quyền ghi).",
            )
        finally:
            if temporary.exists():
                temporary.unlink()

    after = hashlib.sha256(data).hexdigest()
    scan_file.sha256 = after
    scan_file.file_size = len(data)
    db.commit()
    audit_logger.info(
        "scan_whiteout user_id=%s package_id=%s file_id=%s page=%s strokes=%s sha256 %s -> %s",
        actor["id"], pkg.id, scan_file.id, page, len(cleaned), before, after,
    )
    return {"file_id": scan_file.id, "page": page, "sha256": after, "file_size": len(data)}
