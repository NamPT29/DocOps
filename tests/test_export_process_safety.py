"""Exercise real OS process/lock behavior, without accessing business data."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import app_launcher
from server import export_worker
from server.services import export_job_service as jobs


@pytest.fixture
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "EXPORT_SCRATCH_DIR", tmp_path)
    monkeypatch.setattr(jobs, "EXPORT_LOCK_PATH", tmp_path / "export_all.lock")
    return tmp_path


def start_job():
    return jobs.start_export_job(
        template_id=1, extension=".xlsx", include_pending_review=False,
        folder_path=None, start_date=None, end_date=None, requested_by_user_id=1,
    )


def test_live_worker_survives_checks_and_second_export(isolated_jobs, monkeypatch):
    worker = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        if os.name == "nt":
            def forbidden_kill(*_args):
                pytest.fail("Windows process checks must never use os.kill")
            monkeypatch.setattr(jobs.os, "kill", forbidden_kill)
        assert jobs._process_is_running(worker.pid)
        monkeypatch.setattr(jobs.subprocess, "Popen", lambda *_args, **_kw: worker)
        first = start_job()
        with pytest.raises(jobs.ExportJobBusyError) as busy:
            start_job()
        assert busy.value.job_id == first["job_id"]
        assert jobs.cleanup_stale_export_jobs()["skipped"] == 1
        assert worker.poll() is None
        worker.communicate(timeout=5)
        assert not jobs._process_is_running(worker.pid)
    finally:
        if worker.poll() is None:
            worker.terminate()
        worker.communicate(timeout=5)


def test_concurrent_start_waits_for_initial_status(isolated_jobs, monkeypatch):
    entered = threading.Event()
    finish_write = threading.Event()
    second_started = threading.Event()
    second_wrote = threading.Event()
    real_write = jobs.write_export_job
    writes = []

    def delayed_write(job_id, payload):
        writes.append(job_id)
        if len(writes) == 1:
            entered.set()
            assert finish_write.wait(5)
        else:
            second_wrote.set()
        return real_write(job_id, payload)

    def contender():
        second_started.set()
        return start_job()

    monkeypatch.setattr(jobs, "write_export_job", delayed_write)
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *_a, **_kw: SimpleNamespace())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(start_job)
        try:
            assert entered.wait(5)
            second = executor.submit(contender)
            assert second_started.wait(5)
            assert not second_wrote.wait(0.2)
        finally:
            finish_write.set()
        first_job = first.result(timeout=5)
        with pytest.raises(jobs.ExportJobBusyError):
            second.result(timeout=5)
    assert jobs.EXPORT_LOCK_PATH.read_text() == first_job["job_id"]
    assert len(writes) == 1


def test_processes_cannot_both_reclaim_an_abandoned_lock(isolated_jobs):
    jobs.EXPORT_LOCK_PATH.write_text("abandoned")
    script = """
import sys
from pathlib import Path
from server.services import export_job_service as jobs
jobs.EXPORT_SCRATCH_DIR = Path(sys.argv[1])
jobs.EXPORT_LOCK_PATH = jobs.EXPORT_SCRATCH_DIR / 'export_all.lock'
job_id = sys.argv[2] * 32
print('ready', flush=True)
sys.stdin.readline()
try:
    jobs._acquire_export_lock(job_id, {
        'job_id': job_id, 'state': 'queued', 'updated_at': jobs._utc_timestamp(),
    })
except jobs.ExportJobBusyError:
    print('busy')
else:
    print('acquired')
"""
    children = []
    try:
        for digit in "123":
            children.append(subprocess.Popen(
                [sys.executable, "-B", "-c", script, str(isolated_jobs), digit],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env={**os.environ, "DATABASE_URL": "sqlite:///:memory:"},
            ))
        for child in children:
            assert child.stdout.readline().strip() == "ready"
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        outcomes = []
        for child in children:
            output, errors = child.communicate(timeout=15)
            assert child.returncode == 0, errors
            outcomes.append(output.strip())
        assert sorted(outcomes) == ["acquired", "busy", "busy"]
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)


def test_releasing_old_job_preserves_new_owner(isolated_jobs):
    jobs.EXPORT_LOCK_PATH.write_text("b" * 32)
    jobs.release_export_lock("a" * 32)
    assert jobs.EXPORT_LOCK_PATH.read_text() == "b" * 32
    jobs.release_export_lock("b" * 32)
    assert not jobs.EXPORT_LOCK_PATH.exists()


def test_frozen_export_command_uses_worker_mode(isolated_jobs, monkeypatch):
    commands = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    def capture(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace()
    monkeypatch.setattr(jobs.subprocess, "Popen", capture)
    start_job()
    assert commands[0][:2] == [sys.executable, "--export-worker"]
    assert "-m" not in commands[0]


def test_launcher_worker_mode_prepares_environment_without_starting_host(monkeypatch):
    calls = []
    monkeypatch.setattr(app_launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(app_launcher, "prepare_runtime_environment", lambda: calls.append("env"))
    def run(args):
        assert calls == ["env"]
        assert args.job_id == "a" * 32
        assert args.template_id == 1
        return 7
    monkeypatch.setattr(export_worker, "run_export_job", run)
    assert app_launcher.main([
        "--export-worker", "--job-id", "a" * 32,
        "--template-id", "1", "--extension", ".xlsx",
    ]) == 7


def test_packaging_lock_contains_migration_runtime():
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    lock = Path(__file__).resolve().parents[1] / "requirements-package.lock"
    names = {
        canonicalize_name(Requirement(line).name)
        for line in lock.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {"alembic", "mako", "markupsafe"} <= names
