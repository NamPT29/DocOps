"""Persistent paths owned by a packaged ScanToExcel Host installation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


HOST_DATA_ROOT_ENV = "SCAN_TO_EXCEL_DATA_DIR"
HOST_DATA_FOLDER_NAME = "ScanToExcelHost"


def resolve_host_data_root(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the host-owned data root without creating it."""
    source = os.environ if environment is None else environment
    configured = str(source.get(HOST_DATA_ROOT_ENV, "") or "").strip()
    if configured:
        return Path(configured)

    # The packaged host is installed per-user and runs without elevation, so its
    # writable state belongs in LOCALAPPDATA. PROGRAMDATA remains a fallback for
    # service-style deployments and can always be selected explicitly through
    # SCAN_TO_EXCEL_DATA_DIR.
    base_directory = str(
        source.get("LOCALAPPDATA") or source.get("PROGRAMDATA") or ""
    ).strip()
    if not base_directory:
        raise RuntimeError(
            "Không xác định được thư mục dữ liệu. "
            f"Hãy đặt {HOST_DATA_ROOT_ENV}."
        )
    return Path(base_directory) / HOST_DATA_FOLDER_NAME


@dataclass(frozen=True)
class HostRuntimePaths:
    """All mutable files for one installed host, outside the app version folder."""

    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "host.env"

    @property
    def uploads_dir(self) -> Path:
        return self.root / "uploads"

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"

    @property
    def source_documents_dir(self) -> Path:
        return self.root / "source_documents"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def updates_dir(self) -> Path:
        return self.root / "updates"

    def ensure_directories(self) -> None:
        for path in (
            self.config_dir,
            self.uploads_dir,
            self.templates_dir,
            self.source_documents_dir,
            self.exports_dir,
            self.logs_dir,
            self.updates_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

