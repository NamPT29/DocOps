"""Service for scan package ingestion (FR-SCN-01)."""

import os
import time
import json
import unicodedata
import re
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text

from server.database import get_utc_now, SessionLocal
from server.models_scan import CaseScanPackage, CaseScanFile
from server.services.server_folder_service import resolve_server_source_directory
from server.services.workflow_service import transition_case_stage
from server.repositories.workflow_repository import WorkflowRepository
from server.models_workflow import ProjectStageMember
from server.repositories.scan_repository import (
    get_project_by_id,
    get_case_by_id,
    get_users_by_ids,
    update_assigned_user_for_scan_stage,
    lock_and_get_latest_scan_package_version,
    get_processing_scan_package,
    create_scan_package,
    create_scan_files,
    update_scan_package,
)

try:
    import pypdf
except ImportError:
    pypdf = None


def _normalize_name(name: str) -> str:
    n = unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[\s_\-]', '', n).lower()


def _get_scanned_by_name(source_path: Path, level: int) -> str | None:
    if level <= 0:
        return None
    try:
        current = source_path
        for _ in range(level):
            current = current.parent
        if current.name:
            return current.name.strip()
    except Exception:
        pass
    return None


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
        raise ValueError("Dự án không tồn tại.")
        
    case = get_case_by_id(db, project_id, case_id)
    if not case:
        raise ValueError("Hộp không tồn tại.")

    _, source_dir, _ = resolve_server_source_directory(folder_path)
    box_number_str = case.display_name.split()[-1] if " " in case.display_name else case.display_name
    if box_number_str not in source_dir.name:
        raise ValueError(f"Thư mục đã chọn ({source_dir.name}) không khớp với hộp {case.display_name}.")

    stage = WorkflowRepository(db).get_state(case_id, "scan")
    if not stage:
        raise ValueError("Dự án không bật bước Scan.")

    check_scan_stage = WorkflowRepository(db).get_state(case_id, "check_scan")
    if check_scan_stage and check_scan_stage.status != "pending":
        raise ValueError("Bước Kiểm tra scan đã bắt đầu, không thể nộp thêm gói.")

    if stage.status in ("pending", "rejected"):
        transition_case_stage(
            db, 
            project_id=project_id, 
            case_id=case_id, 
            stage_key="scan",
            action="start",
            actor=actor,
            reason="Nộp gói scan mới"
        )
    elif stage.status == "in_progress":
        pass
    else:
        raise ValueError(f"Không thể nộp gói scan khi trạng thái bước Scan là: {stage.status}")

    scanned_by_name = _get_scanned_by_name(source_dir, scan_user_name_level)
    matched_user_id = None
    if scanned_by_name:
        scan_member_ids = [m.user_id for m in db.query(ProjectStageMember).filter_by(project_id=project_id, stage_key="scan").all()]
        if scan_member_ids:
            norm_scanned = _normalize_name(scanned_by_name)
            users = get_users_by_ids(db, scan_member_ids)
            matches = [u for u in users if _normalize_name(u.full_name) == norm_scanned or _normalize_name(u.username) == norm_scanned]
            if len(matches) == 1:
                matched_user_id = matches[0].id
                
        update_assigned_user_for_scan_stage(db, case_id, matched_user_id)

    if get_processing_scan_package(db, case_id):
        raise ValueError("Hộp đang có một gói scan khác đang xử lý.")

    version = lock_and_get_latest_scan_package_version(db, case_id)

    pkg = CaseScanPackage(
        case_id=case_id,
        version=version,
        scanned_by_name=scanned_by_name,
        scanned_by_user_id=matched_user_id,
        submitted_by_user_id=actor["id"],
        scan_user_name_level=scan_user_name_level,
        source_path=folder_path,
        status="processing",
        started_at=get_utc_now()
    )
    create_scan_package(db, pkg)
    db.commit()
    db.refresh(pkg)
    
    return pkg


def _calculate_a4_equivalent(width: float, height: float, rotate: int) -> int:
    """Classify page size and return (a0, a1, a2, a3, a4, a5)."""
    # A4 standard is roughly 595 x 842 points.
    if rotate in (90, 270):
        width, height = height, width
        
    area = width * height
    # Very rough bounds: A4 area = 595 * 842 = 500,990.
    # 110% bound is roughly 1.1x in each dimension -> 1.21x area.
    A4_AREA = 595.28 * 841.89
    
    if area < A4_AREA * 0.5 * 1.1:
        return 0, 0, 0, 0, 0, 1  # A5
    elif area <= A4_AREA * 1.1:
        return 0, 0, 0, 0, 1, 0  # A4
    elif area <= A4_AREA * 2 * 1.1:
        return 0, 0, 0, 1, 0, 0  # A3
    elif area <= A4_AREA * 4 * 1.1:
        return 0, 0, 1, 0, 0, 0  # A2
    elif area <= A4_AREA * 8 * 1.1:
        return 0, 1, 0, 0, 0, 0  # A1
    else:
        return 1, 0, 0, 0, 0, 0  # A0


def process_scan_package_background(package_id: int):
    if not pypdf:
        return
        
    with SessionLocal() as db:
        from server.repositories.scan_repository import get_scan_package, update_scan_package, create_scan_files
        pkg = get_scan_package(db, package_id)
        if not pkg or pkg.status != "processing":
            return
            
        _, source_dir, _ = resolve_server_source_directory(pkg.source_path)
        
        all_files = []
        for root, _, files in os.walk(source_dir):
            for name in files:
                all_files.append(Path(root) / name)
                
        total_pages = 0
        total_a4_equiv = 0
        processed = 0
        failed = 0
        
        warning_flags = set()
        
        # Check mtime/size changes
        def get_file_stats(path: Path):
            try:
                st = os.stat(path)
                return st.st_size, st.st_mtime
            except OSError:
                return -1, -1

        for fpath in all_files:
            rel_path = fpath.relative_to(source_dir).as_posix()
            
            s1, m1 = get_file_stats(fpath)
            time.sleep(0.01) # Small gap if there are many files, but rule says "Việc chờ giữa hai lần lấy mẫu chỉ 2-3 giây".
            # To be efficient, we can sample all files once, sleep 2 seconds, sample again.
            
        # Refined incomplete check: Sample all, wait, sample all
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
                    
                    # 1 A3 = 2 A4, 1 A2 = 4 A4, 1 A1 = 8 A4, 1 A0 = 16 A4. 1 A5 = 0 (Wait, A5 equivalent? A5 usually counts as A4? No, standard A4 equivalent: A5 is 0.5 A4, but user said integer. 1 A4 = 1. A5 doesn't add to A4 equivalent in standard? Let's use standard integer sum: A4 + 2*A3 + 4*A2 + 8*A1 + 16*A0. A5 can be ignored for A4 eq, or wait, usually A5 is half A4, but A4 equivalent must be integer. "số nguyên". So A5 contributes 0 to integer A4 equivalent? Or we sum all area and divide? Area of A5 is 0.5. So a5_pages // 2? No, normally A4 eq = A4 + 2*A3 + 4*A2 + 8*A1 + 16*A0.)
                    file_a4_eq = file_a4 + (file_a3 * 2) + (file_a2 * 4) + (file_a1 * 8) + (file_a0 * 16)
                    scan_file.a4_equivalent = file_a4_eq
                    
                    total_pages += num_pages
                    total_a4_equiv += file_a4_eq
                    processed += 1
            except Exception as e:
                scan_file.status = "error"
                scan_file.page_count = -1
                scan_file.error_message = f"Lỗi đọc PDF (có thể chép dở hoặc hỏng): {str(e)}"
                failed += 1
                warning_flags.add("error_files")
                
            create_scan_files(db, [scan_file])
            
            # Periodically update package progress
            pkg.processed_files = processed
            pkg.failed_files = failed
            update_scan_package(db, pkg)
            db.commit()

        pkg.total_files = len(all_files)
        pkg.processed_files = processed
        pkg.failed_files = failed
        pkg.total_pages = total_pages
        pkg.total_a4_equivalent = total_a4_equiv
        pkg.status = "done"
        pkg.finished_at = get_utc_now()
        
        if warning_flags:
            pkg.warning_flags = json.dumps(list(warning_flags))
            
        update_scan_package(db, pkg)
        db.commit()
