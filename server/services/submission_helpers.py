"""Small, dependency-free helpers shared by submission workflows."""

from urllib.parse import quote

from server.utils.folder_utils import NO_FOLDER_SENTINEL


COMPLETED_WITHOUT_FOLDER = NO_FOLDER_SENTINEL


def _pdf_url(uuid_filename: str) -> str:
    return f"/api/files/{quote(uuid_filename, safe='')}"
