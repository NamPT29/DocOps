from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from server.routers import submissions
from server import export_worker
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


def test_download_export_job_does_not_expose_internal_path_error(monkeypatch, caplog):
    job_id = "a" * 32
    monkeypatch.setattr(
        submissions,
        "read_export_job",
        lambda _job_id: {"state": "completed", "extension": ".xlsx"},
    )

    def fail_output_path(_job_id, _extension):
        raise ValueError("C:\\secret\\internal-export-path")

    monkeypatch.setattr(submissions, "export_job_output_path", fail_output_path)

    with caplog.at_level("ERROR", logger="server.routers.submissions"):
        with pytest.raises(HTTPException) as error:
            submissions.api_download_export_job(
                job_id,
                BackgroundTasks(),
                current_user={"id": 1, "role": "admin"},
            )

    assert error.value.status_code == 500
    assert error.value.detail == "Không thể xác định file xuất"
    assert "C:\\secret\\internal-export-path" not in error.value.detail
    assert "Invalid export output path" in caplog.text


def test_cleanup_export_job_retries_a_temporarily_locked_windows_log(
    isolated_export_jobs,
    monkeypatch,
):
    job_id = "b" * 32
    export_job_service.write_export_job(job_id, {
        "job_id": job_id,
        "state": "completed",
        "extension": ".xlsx",
    })
    log_path = isolated_export_jobs / f"export_job_{job_id}.log"
    output_path = export_job_service.export_job_output_path(job_id, ".xlsx")
    log_path.write_bytes(b"worker log")
    output_path.write_bytes(b"workbook")
    real_unlink = Path.unlink
    log_attempts = 0

    def temporarily_locked_unlink(path, *args, **kwargs):
        nonlocal log_attempts
        if path == log_path:
            log_attempts += 1
            if log_attempts < 3:
                raise PermissionError(13, "file is being used", str(path))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", temporarily_locked_unlink)
    monkeypatch.setattr(export_job_service.time, "sleep", lambda _seconds: None)

    result = export_job_service.cleanup_export_job(job_id)

    assert log_attempts == 3
    assert result == {"removed": 3, "retained": []}
    assert not list(isolated_export_jobs.glob(f"*{job_id}*"))


def test_cleanup_export_job_keeps_locked_log_without_raising(
    isolated_export_jobs,
    monkeypatch,
):
    job_id = "c" * 32
    export_job_service.write_export_job(job_id, {
        "job_id": job_id,
        "state": "completed",
        "extension": ".xlsx",
    })
    log_path = isolated_export_jobs / f"export_job_{job_id}.log"
    output_path = export_job_service.export_job_output_path(job_id, ".xlsx")
    log_path.write_bytes(b"worker log")
    output_path.write_bytes(b"workbook")
    real_unlink = Path.unlink

    def permanently_locked_unlink(path, *args, **kwargs):
        if path == log_path:
            raise PermissionError(13, "file is being used", str(path))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", permanently_locked_unlink)
    monkeypatch.setattr(export_job_service.time, "sleep", lambda _seconds: None)

    result = export_job_service.cleanup_export_job(job_id)

    assert result["removed"] == 2
    assert result["retained"] == [str(log_path)]
    assert log_path.is_file()
    assert not output_path.exists()


def test_start_export_job_recovers_lock_from_dead_worker(
    isolated_export_jobs,
    monkeypatch,
):
    stale_job_id = "d" * 32
    export_job_service.write_export_job(stale_job_id, {
        "job_id": stale_job_id,
        "state": "running",
        "extension": ".xlsx",
        "worker_pid": 999999,
        "updated_at": export_job_service._utc_timestamp(),
    })
    export_job_service.EXPORT_LOCK_PATH.write_text(stale_job_id, encoding="utf-8")
    monkeypatch.setattr(export_job_service, "_process_is_running", lambda _pid: False)

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(
        export_job_service.subprocess,
        "Popen",
        lambda _command, **_kwargs: FakeProcess(),
    )

    new_job = export_job_service.start_export_job(
        template_id=2,
        extension=".xlsx",
        include_pending_review=False,
        folder_path=None,
        start_date=None,
        end_date=None,
        requested_by_user_id=1,
    )

    stale_job = export_job_service.read_export_job(stale_job_id)
    assert stale_job["state"] == "error"
    assert "khóa đã được thu hồi" in stale_job["message"]
    assert new_job["worker_pid"] == 4321
    assert export_job_service.EXPORT_LOCK_PATH.read_text(encoding="utf-8") == new_job["job_id"]

    export_job_service.update_export_job(new_job["job_id"], state="completed")
    export_job_service.release_export_lock(new_job["job_id"])
    export_job_service.cleanup_export_job(stale_job_id)
    export_job_service.cleanup_export_job(new_job["job_id"])


def test_export_worker_retries_transient_file_error_and_completes(
    isolated_export_jobs,
    monkeypatch,
):
    job_id = "e" * 32
    export_job_service.write_export_job(job_id, {
        "job_id": job_id,
        "state": "queued",
        "extension": ".xlsx",
        "filename": "retry.xlsx",
    })
    export_job_service.EXPORT_LOCK_PATH.write_text(job_id, encoding="utf-8")
    sessions = []

    class FakeSession:
        def __init__(self):
            self.rolled_back = False
            self.closed = False

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    def create_session():
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(export_worker, "SessionLocal", create_session)
    monkeypatch.setattr(
        export_worker,
        "LookupRepository",
        lambda _db: SimpleNamespace(
            get_template=lambda _template_id: SimpleNamespace(filename="retry.xlsx"),
        ),
    )
    monkeypatch.setattr(
        export_worker,
        "SubmissionRepository",
        lambda _db: SimpleNamespace(approved_for_export=lambda **_kwargs: [SimpleNamespace(id=1)]),
    )
    monkeypatch.setenv("EXPORT_JOB_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("EXPORT_JOB_RETRY_DELAY_SECONDS", "0.01")
    monkeypatch.setattr(export_worker.time, "sleep", lambda _seconds: None)
    attempts = []

    def flaky_export(_template_path, _submissions, output_path):
        attempts.append(output_path)
        if len(attempts) == 1:
            raise OSError("temporary file lock")
        Path(output_path).write_bytes(b"workbook")

    monkeypatch.setattr(export_worker, "export_submissions_to_excel", flaky_export)
    args = SimpleNamespace(
        job_id=job_id,
        extension=".xlsx",
        project_id=None,
        template_id=2,
        include_pending_review=False,
        folder_path=None,
        start_date=None,
        end_date=None,
    )

    assert export_worker.run_export_job(args) == 0

    completed = export_job_service.read_export_job(job_id)
    assert len(attempts) == 2
    assert completed["state"] == "completed"
    assert completed["attempt"] == 2
    assert completed["max_attempts"] == 3
    assert sessions[0].rolled_back is True
    assert all(session.closed for session in sessions)
    assert not export_job_service.EXPORT_LOCK_PATH.exists()
