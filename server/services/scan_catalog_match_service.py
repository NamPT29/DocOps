import json
from server.services.arrangement_catalog_parser import parse_dossier_number, CatalogValueError

def match_scan_files_to_catalog(catalog_rows, file_paths, *, removed_rows=()):
    """So khớp thư mục scan với mục lục."""
    expected = {}
    for row in catalog_rows:
        expected[(row.dossier_number, row.dossier_suffix)] = f"{row.dossier_number}{row.dossier_suffix}"
    
    removed = set()
    for row in removed_rows:
        removed.add((row.dossier_number, row.dossier_suffix))

    catalog_total = len(expected)
    if catalog_total == 0 and len(removed) == 0:
        return {
            "match_status": "no_catalog",
            "summary": json.dumps({
                "catalog_total": 0,
                "folders_found": 0,
                "matched": [],
                "missing": [],
                "extra": [],
                "invalid_folders": [],
                "duplicate_folders": [],
                "only_cover": [],
                "removed_from_catalog": [],
                "misplaced_files": [],
                "truncated": False,
            })
        }

    folders = {}
    misplaced_files = []
    
    for path in file_paths:
        parts = path.strip("/").split("/")
        if len(parts) != 2:
            misplaced_files.append(path)
        else:
            folder, file = parts
            folders.setdefault(folder, []).append(file)

    invalid_folders = []
    duplicate_folders = []
    removed_from_catalog = []
    extra = []
    only_cover = []
    matched = []

    parsed_folders = {}
    for folder, files in folders.items():
        try:
            num, suffix = parse_dossier_number(folder)
            key = (num, suffix)
            
            non_cover_files = [f for f in files if "bia" not in f.lower()]
            if not non_cover_files:
                only_cover.append(folder)
                continue
                
            if key in parsed_folders:
                duplicate_folders.append(folder)
            else:
                parsed_folders[key] = folder
                
        except CatalogValueError:
            invalid_folders.append(folder)

    for key, folder in parsed_folders.items():
        if key in expected:
            matched.append(f"{key[0]}{key[1]}")
        elif key in removed:
            removed_from_catalog.append(folder)
        else:
            extra.append(folder)

    missing = []
    for key, label in expected.items():
        if key not in parsed_folders:
            missing.append(label)

    # Sort results for stability
    matched.sort(key=lambda x: (int(''.join(filter(str.isdigit, x))), x))
    missing.sort(key=lambda x: (int(''.join(filter(str.isdigit, x))), x))
    extra.sort()
    invalid_folders.sort()
    duplicate_folders.sort()
    only_cover.sort()
    removed_from_catalog.sort()
    misplaced_files.sort()

    truncated = False
    for lst in [matched, missing, extra, invalid_folders, duplicate_folders, only_cover, removed_from_catalog, misplaced_files]:
        if len(lst) > 50:
            lst[:] = lst[:50]
            truncated = True

    match_status = "matched"
    if missing or extra or invalid_folders or duplicate_folders or only_cover or removed_from_catalog or misplaced_files:
        match_status = "mismatch"

    summary = {
        "catalog_total": catalog_total,
        "folders_found": len(folders),
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "invalid_folders": invalid_folders,
        "duplicate_folders": duplicate_folders,
        "only_cover": only_cover,
        "removed_from_catalog": removed_from_catalog,
        "misplaced_files": misplaced_files,
        "truncated": truncated,
    }

    return {
        "match_status": match_status,
        "summary": json.dumps(summary)
    }
