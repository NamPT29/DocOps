from pathlib import Path

import pytest

from server.host_runtime_paths import (
    HOST_DATA_ROOT_ENV,
    HostRuntimePaths,
    resolve_host_data_root,
)


def test_explicit_host_data_root_takes_priority():
    configured = resolve_host_data_root(
        {HOST_DATA_ROOT_ENV: "D:/scan-data", "PROGRAMDATA": "C:/ProgramData"}
    )

    assert configured == Path("D:/scan-data")


def test_host_data_root_defaults_to_program_data():
    configured = resolve_host_data_root({"PROGRAMDATA": "C:/ProgramData"})

    assert configured == Path("C:/ProgramData/ScanToExcelHost")


def test_host_data_root_requires_a_windows_data_location():
    with pytest.raises(RuntimeError, match=HOST_DATA_ROOT_ENV):
        resolve_host_data_root({})


def test_runtime_paths_create_only_host_owned_directories(tmp_path):
    paths = HostRuntimePaths(tmp_path / "host-data")

    paths.ensure_directories()

    assert paths.config_path == tmp_path / "host-data/config/host.env"
    assert all(
        directory.is_dir()
        for directory in (
            paths.config_dir,
            paths.uploads_dir,
            paths.templates_dir,
            paths.source_documents_dir,
            paths.exports_dir,
            paths.logs_dir,
            paths.updates_dir,
        )
    )
