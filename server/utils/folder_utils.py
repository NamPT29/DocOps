import hashlib

NO_FOLDER_SENTINEL = "__NO_FOLDER__"


def normalize_folder_path(folder_path: object) -> str:
    return str(folder_path or "").replace("\\", "/").strip("/")


def folder_path_key(folder_path: object) -> str:
    normalized = normalize_folder_path(folder_path) or NO_FOLDER_SENTINEL
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
