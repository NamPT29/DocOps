"""Service for scan package ingestion (FR-SCN-01)."""

import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy.orm import Session

from server.database import get_utc_now, SessionLocal
from server.models_scan import CaseScanPackage, CaseScanFile
from server.services.arrangement_catalog_parser import box_number_of_case_key
from server.services.server_folder_service import resolve_server_source_directory
from server.services.workflow_service import transition_case_stage
from server.repositories.workflow_repository import WorkflowRepository
from server.repositories.scan_repository import (
    get_project_by_id,
    get_case_by_id,
    get_users_by_ids,
    get_scan_stage_member_ids,
    update_assigned_user_for_scan_stage,
    lock_and_get_latest_scan_package_version,
    get_processing_scan_package,
    get_scan_package,
    create_scan_package,
    create_scan_files,
    update_scan_package,
)

try:
    import pypdf
except ImportError:
    pypdf = None

logger = logging.getLogger(__name__)


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    name = name.replace('đ', 'd').replace('Đ', 'd')
    n = unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[\s_\-]', '', n).lower()


def _extract_box_number(s: str | None) -> int | None:
    if not s:
        return None
    match = re.search(r"\d+", s)
    return int(match.group()) if match else None


def submit_scan_package(
    db: Session,
    *,
    project_id: int,
    case_id: int,
    folder_path: str,
    scan_user_name_level: int = 1,
    actor: dict,
) -> CaseScanPackage:
    project = get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại.")
        
    case = get_case_by_id(db, project_id, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Hộp không tồn tại.")

    if scan_user_name_level < 0:
        raise HTTPException(status_code=400, detail="Mức thư mục tên người scan không hợp lệ.")

    try:
        _, source_dir, norm_path = resolve_server_source_directory(folder_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    case_box = box_number_of_case_key(case.case_key) or _extract_box_number(case.display_name)
    folder_box = _extract_box_number(source_dir.name)
    
    if case_box is None or folder_box is None or case_box != folder_box:
        raise HTTPException(status_code=409, detail=f"Thư mục đã chọn ({source_dir.name}) không khớp số hộp với hộp {case.display_name}.")

    workflow_repo = WorkflowRepository(db)
    enabled_stages = {s.stage_key for s in workflow_repo.stage_rows(project_id) if s.is_enabled}
    if "scan" not in enabled_stages:
        raise HTTPException(status_code=409, detail="Dự án không bật bước Scan.")

    stage = workflow_repo.get_state(case_id, "scan")
    # If there is no state yet but it's enabled, it acts as pending.
    stage_status = stage.status if stage else "pending"

    if stage_status not in ("pending", "in_progress", "rejected"):
        raise HTTPException(status_code=409, detail=f"Không thể nộp gói scan khi trạng thái bước Scan là: {stage_status}")

    check_scan_stage = workflow_repo.get_state(case_id, "scan_qc")
    if check_scan_stage and check_scan_stage.status != "pending":
        raise HTTPException(status_code=409, detail="Bước Kiểm tra scan đã bắt đầu, không thể nộp thêm gói.")

    if get_processing_scan_package(db, case_id):
        raise HTTPException(status_code=409, detail="Hộp đang có một gói scan khác đang xử lý.")

    # Execute workflow changes
    if stage_status in ("pending", "rejected"):
        transition_case_stage(
            db, 
            project_id=project_id, 
            case_id=case_id, 
            stage_key="scan",
            action="start",
            actor=actor,
            reason="Nộp gói scan mới"
        )

    # Calculate scanned_by_name
    parts = Path(norm_path).parts
    scanned_by_name = None
    warning_flags = set()
    
    if scan_user_name_level > 0:
        if len(parts) > scan_user_name_level:
            scanned_by_name = parts[-(scan_user_name_level + 1)]
        else:
            warning_flags.add("missing_scan_user")

    matched_user_id = None
    if scanned_by_name:
        scan_member_ids = get_scan_stage_member_ids(db, project_id)
        if scan_member_ids:
            norm_scanned = _normalize_name(scanned_by_name)
            users = get_users_by_ids(db, scan_member_ids)
            matches = [u for u in users if _normalize_name(u.full_name) == norm_scanned or _normalize_name(u.username) == norm_scanned]
            if len(matches) == 1:
                matched_user_id = matches[0].id
                
    update_assigned_user_for_scan_stage(db, case_id, matched_user_id)

    version = lock_and_get_latest_scan_package_version(db, case_id)

    pkg = CaseScanPackage(
        case_id=case_id,
        version=version,
        scanned_by_name=scanned_by_name,
        scanned_by_user_id=matched_user_id,
        submitted_by_user_id=actor["id"],
        scan_user_name_level=scan_user_name_level,
        source_path=norm_path,
        status="processing",
        warning_flags=json.dumps(list(warning_flags)) if warning_flags else None,
        started_at=get_utc_now()
    )
    create_scan_package(db, pkg)
    db.commit()
    db.refresh(pkg)
    
    return pkg


def _calculate_a4_equivalent(width: float, height: float, rotate: int) -> tuple[int, ...]:
    """Classify page size and return (a0, a1, a2, a3, a4, a5)."""
    if rotate in (90, 270):
        width, height = height, width
        
    area = width * height
    # Bảng khổ (điểm) theo QC-06
    sizes = [
        (420 * 595, (0, 0, 0, 0, 0, 1)),   # A5
        (595 * 842, (0, 0, 0, 0, 1, 0)),   # A4
        (842 * 1190, (0, 0, 0, 1, 0, 0)),  # A3
        (1190 * 1684, (0, 0, 1, 0, 0, 0)), # A2
        (1684 * 2384, (0, 1, 0, 0, 0, 0)), # A1
        (2384 * 3370, (1, 0, 0, 0, 0, 0)), # A0
    ]
    
    for ref_area, result in sizes:
        if ref_area * 1.10 >= area:
            return result
    return (1, 0, 0, 0, 0, 0)  # Lớn hơn A0 thì tính A0


def _merge_warning_flags(stored: str | None, new_flags: set[str]) -> str | None:
    """Keep flags set at submission (e.g. missing_scan_user) and add the new ones."""
    try:
        existing = set(json.loads(stored)) if stored else set()
    except (TypeError, ValueError):
        existing = set()
    merged = existing | set(new_flags)
    return json.dumps(sorted(merged)) if merged else None


def _mark_failed(db: Session, package_id: int, message: str) -> None:
    """Finish a package as failed even after a database error in the session."""
    db.rollback()
    pkg = get_scan_package(db, package_id)
    if pkg is None:
        return
    pkg.status = "failed"
    pkg.error_message = message
    pkg.finished_at = get_utc_now()
    update_scan_package(db, pkg)
    db.commit()


def process_scan_package_background(package_id: int, session_factory=SessionLocal):
    with session_factory() as db:
        pkg = get_scan_package(db, package_id)
        if not pkg or pkg.status != "processing":
            return
            
        if not pypdf:
            pkg.status = "failed"
            pkg.error_message = "Thư viện pypdf chưa được cài đặt."
            pkg.finished_at = get_utc_now()
            update_scan_package(db, pkg)
            db.commit()
            return

        try:
            _, source_dir, _ = resolve_server_source_directory(pkg.source_path)
            
            all_files = []
            for root, _, files in os.walk(source_dir):
                for name in files:
                    all_files.append(Path(root) / name)
                    
            pkg.total_files = len(all_files)
            update_scan_package(db, pkg)
            db.commit()
                    
            total_pages = 0
            total_a4_equiv = 0
            processed = 0
            failed = 0
            warning_flags = set()
            
            def get_file_stats(path: Path):
                try:
                    st = os.stat(path)
                    return st.st_size, st.st_mtime
                except OSError:
                    return -1, -1
                    
            initial_stats = {f: get_file_stats(f) for f in all_files}
            time.sleep(2.5)
            final_stats = {f: get_file_stats(f) for f in all_files}
            
            for fpath in all_files:
                rel_path = fpath.relative_to(source_dir).as_posix()
                s1, m1 = initial_stats[fpath]
                s2, m2 = final_stats[fpath]
                
                if s1 < 0 or s2 < 0:
                    continue
                    
                scan_file = CaseScanFile(
                    package_id=pkg.id,
                    relative_path=rel_path,
                    file_size=s2,
                )
                
                if s1 != s2 or m1 != m2:
                    scan_file.status = "incomplete"
                    scan_file.error_message = "File đang được chép dở (kích thước/mtime thay đổi)."
                    scan_file.page_count = -1
                    failed += 1
                    warning_flags.add("incomplete_files")
                    create_scan_files(db, [scan_file])
                    continue
                    
                if fpath.suffix.lower() != ".pdf":
                    scan_file.is_pdf = False
                    scan_file.status = "not_pdf"
                    scan_file.page_count = 0
                    warning_flags.add("non_pdf_files")
                    create_scan_files(db, [scan_file])
                    processed += 1
                    continue
                    
                try:
                    with open(fpath, "rb") as f:
                        reader = pypdf.PdfReader(f, strict=False)
                        if reader.is_encrypted:
                            raise ValueError("File PDF bị mã hóa.")
                        num_pages = len(reader.pages)
                        
                        if num_pages == 0:
                            raise ValueError("PDF 0 trang.")
                            
                        file_a0 = file_a1 = file_a2 = file_a3 = file_a4 = file_a5 = 0
                        
                        for page in reader.pages:
                            mb = page.mediabox
                            rotate = page.get("/Rotate", 0)
                            user_unit = float(page.get("/UserUnit", 1.0))
                            
                            w = float(mb.width) * user_unit
                            h = float(mb.height) * user_unit
                            
                            a0, a1, a2, a3, a4, a5 = _calculate_a4_equivalent(w, h, rotate)
                            file_a0 += a0
                            file_a1 += a1
                            file_a2 += a2
                            file_a3 += a3
                            file_a4 += a4
                            file_a5 += a5
                            
                        scan_file.page_count = num_pages
                        scan_file.a0_pages = file_a0
                        scan_file.a1_pages = file_a1
                        scan_file.a2_pages = file_a2
                        scan_file.a3_pages = file_a3
                        scan_file.a4_pages = file_a4
                        scan_file.a5_pages = file_a5
                        
                        file_a4_eq = file_a5 + file_a4 + (file_a3 * 2) + (file_a2 * 4) + (file_a1 * 8) + (file_a0 * 16)
                        scan_file.a4_equivalent = file_a4_eq
                        
                        total_pages += num_pages
                        total_a4_equiv += file_a4_eq
                        processed += 1
                except Exception as e:
                    scan_file.status = "error"
                    scan_file.page_count = -1
                    scan_file.error_message = f"Lỗi đọc PDF: {str(e)}"
                    failed += 1
                    warning_flags.add("error_files")
                    
                create_scan_files(db, [scan_file])
                
                pkg.processed_files = processed
                pkg.failed_files = failed
                update_scan_package(db, pkg)
                db.commit()

            pkg.processed_files = processed
            pkg.failed_files = failed
            pkg.total_pages = total_pages
            pkg.total_a4_equivalent = total_a4_equiv
            pkg.status = "done"
            pkg.finished_at = get_utc_now()
            pkg.warning_flags = _merge_warning_flags(pkg.warning_flags, warning_flags)
            update_scan_package(db, pkg)
            db.commit()
        except Exception as e:
            try:
                _mark_failed(db, package_id, f"Lỗi bất ngờ: {e}")
            except Exception:
                # The database itself is unreachable; startup maintenance
                # (fail_stuck_processing_packages) closes the package later.
                logger.exception("Không thể đánh dấu gói scan %s là failed", package_id)
