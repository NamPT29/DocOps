from pathlib import Path

import pytest

from server.services import export_job_service


@pytest.fixture()
def isolated_export_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(export_job_service, "EXPORT_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(export_job_service, "EXPORT_LOCK_PATH", tmp_path / "export_all.lock")
    return tmp_path


def test_start_export_job_spawns_hidden_worker_and_prevents_parallel_jobs(
    isolated_export_jobs,
    monkeypatch,
):
    calls = []

    class FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(export_job_service.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(export_job_service.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    job = export_job_service.start_export_job(
        template_id=2,
        extension=".xlsx",
        include_pending_review=True,
        folder_path=None,
        start_date=None,
        end_date=None,
        requested_by_user_id=1,
    )

    assert job["state"] == "queued"
    assert job["include_pending_review"] is True
    assert export_job_service.read_export_job(job["job_id"])["filename"].startswith(
        "BaoCao_TatCa_2_"
    )
    command, options = calls[0]
    assert command[1:3] == ["-m", "server.export_worker"]
    assert "--include-pending-review" in command
    assert options["cwd"] == str(export_job_service.PROJECT_ROOT)
    assert options["creationflags"] == 0x08000000

    with pytest.raises(export_job_service.ExportJobBusyError) as busy:
        export_job_service.start_export_job(
            template_id=2,
            extension=".xlsx",
            include_pending_review=True,
            folder_path=None,
            start_date=None,
            end_date=None,
            requested_by_user_id=1,
        )
    assert busy.value.job_id == job["job_id"]

    export_job_service.update_export_job(job["job_id"], state="completed")
    export_job_service.release_export_lock(job["job_id"])
    export_job_service.cleanup_export_job(job["job_id"])
    assert not list(Path(isolated_export_jobs).glob(f"*{job['job_id']}*"))


def test_export_job_paths_reject_invalid_identifiers(isolated_export_jobs):
    with pytest.raises(ValueError, match="Mã tác vụ"):
        export_job_service.export_job_status_path("../../unsafe")
    with pytest.raises(ValueError, match="Định dạng"):
        export_job_service.export_job_output_path("a" * 32, ".exe")
