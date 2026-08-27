import posixpath
from pathlib import Path

from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles


_PRIVATE_FRONTEND_PATHS = frozenset({"temp.html"})


def is_private_frontend_path(path: str) -> bool:
    normalized = posixpath.normpath(str(path).replace("\\", "/")).lstrip("/")
    return normalized.casefold() in _PRIVATE_FRONTEND_PATHS


def resolve_public_frontend_file(frontend_dir: Path, path: str) -> Path | None:
    if is_private_frontend_path(path):
        return None

    resolved_frontend_dir = frontend_dir.resolve()
    file_path = (resolved_frontend_dir / path).resolve()
    try:
        file_path.relative_to(resolved_frontend_dir)
    except ValueError:
        return None
    return file_path if file_path.is_file() else None


class PublicFrontendStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if is_private_frontend_path(path):
            raise HTTPException(status_code=404, detail="File not found")
        return await super().get_response(path, scope)
