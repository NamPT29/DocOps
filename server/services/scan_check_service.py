"""Check scan: xem từng file và trang của gói scan, so số trang với số tờ mục lục (chỉ đọc).

Quy tắc (nghiệp vụ đã chốt): hồ sơ n tờ, bìa tách file riêng không đánh số, máy scan tự bỏ
trang trắng, mặt sau có chữ thì scan -> cần ít nhất n + 1 trang, nhiều nhất 2n + 1 trang.
"""
import re
from pathlib import Path

from fastapi import HTTPException

from server.repositories.scan_repository import (
    get_case_by_id,
    get_case_catalog_rows,
    get_scan_package,
    get_scan_package_file,
    list_scan_package_files,
)
from server.services.arrangement_catalog_parser import CatalogValueError, parse_dossier_number
from server.services.server_folder_service import resolve_server_source_directory


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


def get_scan_check_view(db, *, project_id, case_id, package_id):
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
    return {
        "package": {"id": pkg.id, "version": pkg.version, "status": pkg.status},
        "dossiers": dossiers,
        "misplaced_files": misplaced,
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
