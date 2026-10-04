"""Arrangement catalogue (mục lục chỉnh lý) import: preview, then apply.

FR-ARR-01, QC-16. A file only touches the boxes it lists. Inside such a box,
rows missing from the file are deleted while the box has not started
scanning, and kept with a warning flag once it has. Any error in the file
blocks the whole import.
"""

import hashlib
import json
from datetime import timezone

from fastapi import HTTPException

from server.models import ArrangementDossier, ArrangementImport, ProjectCase
from server.repositories.arrangement_repository import ArrangementRepository
from server.services import account_policy_service
from server.services.arrangement_catalog_parser import (
    DOSSIER_FIELDS,
    MAINTENANCE_CODES,
    MAX_REPORTED_ERRORS,
    box_number_from_folder,
    box_number_of_case_key,
    catalog_structure_problems,
    is_placeholder_box_key,
    parse_catalog_workbook,
    placeholder_box_key,
)

PREVIEW_LIST_LIMIT = 200


def _project_or_404(repository, project_id, *, lock=False):
    project = repository.lock_project(project_id) if lock else repository.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return project


def _box_cases(repository, project):
    """Map box number -> project case (box folder or box awaiting its scan)."""
    by_number, problems = {}, []
    for case_row in repository.cases(project.id):
        number = box_number_of_case_key(case_row.case_key)
        if number is None:
            continue
        if number in by_number:
            problems.append(
                f"Hộp {number} xuất hiện ở nhiều thư mục: "
                f"{by_number[number].case_key}, {case_row.case_key}."
            )
            continue
        by_number[number] = case_row
    return by_number, problems


def _dossier_label(item):
    return f"{item.dossier_number}{item.dossier_suffix}"


def _plan(repository, project, parsed):
    """Changes the file would make, with a token pinning the current state."""
    file_errors = list(parsed.file_errors)
    asset_paths = repository.active_asset_paths(project.id)
    if asset_paths:
        file_errors.extend(catalog_structure_problems(asset_paths, case_level=project.case_level))
    box_cases, case_problems = _box_cases(repository, project)
    file_errors.extend(problem for problem in case_problems if problem not in file_errors)
    if file_errors or parsed.errors:
        return file_errors, None

    rows_by_box = {}
    for row in parsed.rows:
        rows_by_box.setdefault(row.box_number, []).append(row)
    existing = {
        (item.box_number, item.dossier_number, item.dossier_suffix): item
        for item in repository.dossiers_for_boxes(project.id, rows_by_box)
    }
    started = repository.started_scan_case_ids(project.id)
    file_keys = {row.key for row in parsed.rows}

    plan = {"added": [], "updated": [], "unchanged": [], "removed": [], "kept": []}
    for row in parsed.rows:
        current = existing.get(row.key)
        if current is None:
            plan["added"].append(row)
        elif any(getattr(current, name) != row.values[name] for name in DOSSIER_FIELDS):
            plan["updated"].append((current, row))
        else:
            plan["unchanged"].append((current, row))
    for key, current in sorted(existing.items()):
        if key in file_keys:
            continue
        plan["kept" if current.case_id in started else "removed"].append(current)
    plan["box_cases"] = box_cases
    plan["new_boxes"] = sorted(number for number in rows_by_box if number not in box_cases)

    fingerprint = {
        "file": parsed.file_sha256,
        "boxes": {
            str(number): box_cases[number].id if number in box_cases else None
            for number in sorted(rows_by_box)
        },
        "existing": sorted(
            [item.id, item.updated_at.isoformat() if item.updated_at else "", item.missing_from_import_id]
            for item in existing.values()
        ),
        "started": sorted(
            case_row.id for number, case_row in box_cases.items()
            if number in rows_by_box and case_row.id in started
        ),
    }
    plan["token"] = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return file_errors, plan


def _listed(items):
    return [
        {"box": item.box_number, "dossier": _dossier_label(item), "title": item.title}
        for item in items[:PREVIEW_LIST_LIMIT]
    ]


def _summary(plan):
    return {
        "added": len(plan["added"]),
        "updated": len(plan["updated"]),
        "unchanged": len(plan["unchanged"]),
        "removed": len(plan["removed"]),
        "kept": len(plan["kept"]),
        "new_boxes": len(plan["new_boxes"]),
    }


def preview_catalog(db, *, project_id, file_name, content, today=None):
    repository = ArrangementRepository(db)
    project = _project_or_404(repository, project_id)
    parsed = parse_catalog_workbook(content, today=today or account_policy_service.vietnam_today())
    file_errors, plan = _plan(repository, project, parsed)
    return {
        "file_name": file_name,
        "file_sha256": parsed.file_sha256,
        "row_count": parsed.data_rows,
        "box_count": len({row.box_number for row in parsed.rows}),
        "file_errors": file_errors,
        "errors": parsed.errors[:MAX_REPORTED_ERRORS],
        "error_count": len(parsed.errors),
        "summary": _summary(plan) if plan else None,
        "removed": _listed(plan["removed"]) if plan else [],
        "kept": _listed(plan["kept"]) if plan else [],
        "plan_token": plan["token"] if plan else None,
        "can_import": plan is not None,
    }


def import_catalog(db, *, project_id, file_name, content, plan_token, actor_user_id, today=None):
    repository = ArrangementRepository(db)
    project = _project_or_404(repository, project_id, lock=True)
    parsed = parse_catalog_workbook(content, today=today or account_policy_service.vietnam_today())
    _file_errors, plan = _plan(repository, project, parsed)
    if plan is None:
        raise HTTPException(
            status_code=400,
            detail="File mục lục còn lỗi; hãy bấm Xem trước, sửa file rồi ghi lại.",
        )
    if plan["token"] != plan_token:
        raise HTTPException(
            status_code=409,
            detail="Mục lục hoặc file đã thay đổi kể từ lúc xem trước. Hãy bấm Xem trước lại.",
        )

    summary = _summary(plan)
    entry = repository.add_import(ArrangementImport(
        project_id=project.id,
        file_name=str(file_name or "muc_luc.xlsx")[:255],
        file_sha256=parsed.file_sha256,
        row_count=len(parsed.rows),
        added=summary["added"],
        updated=summary["updated"],
        unchanged=summary["unchanged"],
        removed=summary["removed"],
        kept=summary["kept"],
        imported_by_user_id=actor_user_id,
    ))
    box_cases = plan["box_cases"]
    for number in plan["new_boxes"]:
        box_cases[number] = repository.add_case(ProjectCase(
            project_id=project.id,
            case_key=placeholder_box_key(number),
            display_name=f"Hộp {number}",
        ))
    for row in plan["added"]:
        repository.add(ArrangementDossier(
            project_id=project.id,
            case_id=box_cases[row.box_number].id,
            box_number=row.box_number,
            dossier_number=row.dossier_number,
            dossier_suffix=row.dossier_suffix,
            source_row=row.row,
            import_id=entry.id,
            **row.values,
        ))
    for current, row in plan["updated"] + plan["unchanged"]:
        for name in DOSSIER_FIELDS:
            setattr(current, name, row.values[name])
        current.case_id = box_cases[row.box_number].id
        current.source_row = row.row
        current.import_id = entry.id
        current.missing_from_import_id = None
    for current in plan["removed"]:
        repository.delete(current)
    for current in plan["kept"]:
        current.missing_from_import_id = entry.id
    db.commit()
    return {"import_id": entry.id, "summary": summary}


def _utc(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def get_catalog(db, *, project_id):
    repository = ArrangementRepository(db)
    project = _project_or_404(repository, project_id)
    cases = {case_row.id: case_row for case_row in repository.cases(project.id)}
    started = repository.started_scan_case_ids(project.id)
    boxes = []
    for number, case_id, count, bad, missing in repository.box_summaries(project.id):
        case_row = cases.get(case_id)
        awaiting = case_row is None or is_placeholder_box_key(case_row.case_key)
        boxes.append({
            "box_number": number,
            "case_id": case_id,
            "folder": None if awaiting else case_row.case_key,
            "awaiting_scan": awaiting,
            "scan_started": case_id in started,
            "dossier_count": int(count or 0),
            "bad_paper_dossiers": int(bad or 0),
            "bad_paper_proposed": bool(bad),
            "missing_count": int(missing or 0),
        })
    return {
        "boxes": boxes,
        "dossier_total": sum(box["dossier_count"] for box in boxes),
        "imports": [
            {
                "created_at": _utc(entry.created_at),
                "file_name": entry.file_name,
                "imported_by": username,
                "row_count": entry.row_count,
                "added": entry.added,
                "updated": entry.updated,
                "unchanged": entry.unchanged,
                "removed": entry.removed,
                "kept": entry.kept,
            }
            for entry, username in repository.recent_imports(project.id)
        ],
        "maintenance_codes": MAINTENANCE_CODES,
    }


def get_box_dossiers(db, *, project_id, box_number):
    repository = ArrangementRepository(db)
    _project_or_404(repository, project_id)
    return [
        {
            "dossier": _dossier_label(item),
            "fonds_code": item.fonds_code,
            "catalog_number": item.catalog_number,
            "file_notation": item.file_notation,
            "title": item.title,
            "start_date": item.start_date,
            "end_date": item.end_date,
            "maintenance_code": item.maintenance_code,
            "sheet_count": item.sheet_count,
            "term": item.term,
            "bad_paper": item.bad_paper,
            "note": item.note,
            "source_row": item.source_row,
            "missing_from_last_import": item.missing_from_import_id is not None,
        }
        for item in repository.box_dossiers(project_id, box_number)
    ]


# --- Upload integration: box folders follow the catalogue (QC-16) ---


def require_catalog_upload_structure(db, project, relative_paths):
    """Refuse uploads that would attach PDFs at the wrong folder level."""
    repository = ArrangementRepository(db)
    if not repository.has_catalog(project.id):
        return
    existing = {}
    for case_row in repository.cases(project.id):
        number = box_number_of_case_key(case_row.case_key)
        if number is not None and not is_placeholder_box_key(case_row.case_key):
            existing.setdefault(number, case_row.case_key)
    problems = catalog_structure_problems(
        relative_paths,
        case_level=project.case_level,
        existing_box_keys=existing,
    )
    if problems:
        raise HTTPException(
            status_code=409,
            detail=(
                "Không nhận lần tải này vì cấu trúc thư mục không khớp mục lục chỉnh lý (QC-16):\n"
                + "\n".join(problems)
            ),
        )


def adopt_box_awaiting_scan(db, project, grouping):
    """Give the uploaded box folder to the catalogue box with the same number."""
    number = box_number_from_folder(grouping["case_name"])
    if number is None:
        return None
    case_row = ArrangementRepository(db).find_case_by_key(project.id, placeholder_box_key(number))
    if case_row is None:
        return None
    case_row.case_key = grouping["case_key"]
    case_row.display_name = grouping["case_name"]
    db.flush()
    return case_row
