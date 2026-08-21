import hashlib
import json
import re
import unicodedata
from pathlib import PurePosixPath


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProjectManifestError(ValueError):
    pass


def canonicalize_project_relative_path(relative_path):
    if not isinstance(relative_path, str):
        raise ProjectManifestError("Đường dẫn tệp phải là chuỗi.")

    normalized = unicodedata.normalize("NFC", relative_path.strip()).replace("\\", "/")
    if not normalized or "\x00" in normalized:
        raise ProjectManifestError("Đường dẫn tệp không hợp lệ.")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ProjectManifestError("Chỉ chấp nhận đường dẫn tương đối trong thư mục dự án.")

    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ProjectManifestError("Đường dẫn không được đi ra ngoài thư mục dự án.")

    canonical = PurePosixPath(*parts).as_posix()
    if canonical.endswith("/") or PurePosixPath(canonical).suffix.casefold() != ".pdf":
        raise ProjectManifestError("Kho dự án chỉ nhận tệp PDF.")
    return canonical


def project_relative_path_key(relative_path):
    return canonicalize_project_relative_path(relative_path).casefold()


def derive_project_group_keys(relative_path, *, case_level, report_mode, report_level=None):
    canonical_path = canonicalize_project_relative_path(relative_path)
    path_key = canonical_path.casefold()
    folder_parts = path_key.split("/")[:-1]

    if not isinstance(case_level, int) or isinstance(case_level, bool) or case_level < 1:
        raise ProjectManifestError("Cấp hồ sơ phải là số nguyên lớn hơn hoặc bằng 1.")
    if len(folder_parts) < case_level:
        raise ProjectManifestError(
            f"Tệp '{canonical_path}' không đủ {case_level} cấp thư mục hồ sơ."
        )

    case_key = "/".join(folder_parts[:case_level])
    if report_mode == "pdf":
        return {
            "case_key": case_key,
            "report_key": path_key,
            "case_name": folder_parts[case_level - 1],
            "report_name": PurePosixPath(canonical_path).name,
        }

    if report_mode != "folder_level":
        raise ProjectManifestError("Kiểu báo cáo phải là 'folder_level' hoặc 'pdf'.")
    if (
        not isinstance(report_level, int)
        or isinstance(report_level, bool)
        or report_level <= case_level
    ):
        raise ProjectManifestError("Cấp báo cáo phải lớn hơn cấp hồ sơ.")
    if len(folder_parts) < report_level:
        raise ProjectManifestError(
            f"Tệp '{canonical_path}' không đủ {report_level} cấp thư mục báo cáo."
        )

    report_key = "/".join(folder_parts[:report_level])
    return {
        "case_key": case_key,
        "report_key": report_key,
        "case_name": folder_parts[case_level - 1],
        "report_name": folder_parts[report_level - 1],
    }


def _normalize_manifest_item(raw_item, *, case_level, report_mode, report_level):
    if not isinstance(raw_item, dict):
        raise ProjectManifestError("Mỗi mục manifest phải là một đối tượng.")

    canonical_path = canonicalize_project_relative_path(raw_item.get("relative_path"))
    path_key = canonical_path.casefold()
    sha256 = str(raw_item.get("sha256") or "").strip().casefold()
    if not SHA256_PATTERN.fullmatch(sha256):
        raise ProjectManifestError(f"SHA-256 của '{canonical_path}' không hợp lệ.")

    size = raw_item.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ProjectManifestError(f"Dung lượng của '{canonical_path}' không hợp lệ.")

    grouping = derive_project_group_keys(
        canonical_path,
        case_level=case_level,
        report_mode=report_mode,
        report_level=report_level,
    )
    return {
        "relative_path": canonical_path,
        "normalized_relative_path": path_key,
        "sha256": sha256,
        "size": size,
        "last_modified": raw_item.get("last_modified"),
        **grouping,
    }


def prepare_project_manifest(
    raw_items,
    *,
    case_level,
    report_mode,
    report_level=None,
    maximum_files=100_000,
):
    if not isinstance(raw_items, list):
        raise ProjectManifestError("Manifest phải là một danh sách tệp.")
    if len(raw_items) > maximum_files:
        raise ProjectManifestError(f"Manifest vượt quá giới hạn {maximum_files} tệp.")

    items_by_path = {}
    for raw_item in raw_items:
        item = _normalize_manifest_item(
            raw_item,
            case_level=case_level,
            report_mode=report_mode,
            report_level=report_level,
        )
        path_key = item["normalized_relative_path"]
        previous = items_by_path.get(path_key)
        if previous is None:
            items_by_path[path_key] = item
            continue
        if previous["sha256"] != item["sha256"] or previous["size"] != item["size"]:
            raise ProjectManifestError(
                f"Đường dẫn '{item['relative_path']}' xuất hiện với nhiều nội dung khác nhau."
            )

    items = sorted(items_by_path.values(), key=lambda item: item["normalized_relative_path"])
    cases = {}
    reports = {}
    for item in items:
        cases.setdefault(
            item["case_key"],
            {"case_key": item["case_key"], "case_name": item["case_name"], "file_count": 0},
        )["file_count"] += 1
        reports.setdefault(
            item["report_key"],
            {
                "case_key": item["case_key"],
                "report_key": item["report_key"],
                "report_name": item["report_name"],
                "file_count": 0,
            },
        )["file_count"] += 1

    digest_payload = [
        [item["normalized_relative_path"], item["size"], item["sha256"]]
        for item in items
    ]
    digest = hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "manifest_digest": digest,
        "items": items,
        "cases": sorted(cases.values(), key=lambda row: row["case_key"]),
        "reports": sorted(reports.values(), key=lambda row: row["report_key"]),
        "total_files": len(items),
        "total_cases": len(cases),
        "total_reports": len(reports),
    }


def select_required_project_uploads(prepared_items, existing_assets):
    existing_identities = {
        (
            str(asset["normalized_relative_path"]).casefold(),
            str(asset["content_sha256"]).casefold(),
            int(asset["byte_size"]),
        )
        for asset in existing_assets
        if asset.get("status", "active") == "active"
    }
    return [
        item
        for item in prepared_items
        if (
            item["normalized_relative_path"],
            item["sha256"],
            item["size"],
        )
        not in existing_identities
    ]
