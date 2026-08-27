import asyncio
import logging
import time

import pytest

import app_launcher
import host_console
from server.routers import documents, project_uploads, submissions
from server.runtime_config import configure_server_runtime


def test_runtime_uses_half_cpu_up_to_four_workers_and_bounds_db_pool():
    environment = {}

    configured = configure_server_runtime(environment, cpu_count=16)

    assert configured.workers == 4
    assert configured.db_pool_size == 5
    assert configured.db_max_overflow == 2
    assert environment["DB_POOL_SIZE"] == "5"
    assert environment["DB_MAX_OVERFLOW"] == "2"
    assert environment["MULTIPROCESS_LOGGING"] == "1"


def test_runtime_honors_explicit_worker_and_pool_configuration():
    environment = {
        "UVICORN_WORKERS": "3",
        "DB_POOL_SIZE": "7",
        "DB_MAX_OVERFLOW": "4",
    }

    configured = configure_server_runtime(environment, cpu_count=2)

    assert configured.workers == 3
    assert configured.db_pool_size == 7
    assert configured.db_max_overflow == 4


def test_runtime_rejects_excessive_worker_count():
    with pytest.raises(RuntimeError, match="không được vượt quá"):
        configure_server_runtime({"UVICORN_WORKERS": "9"}, cpu_count=16)


def test_runtime_rejects_excessive_total_database_connections():
    with pytest.raises(RuntimeError, match="Tổng kết nối database"):
        configure_server_runtime({
            "UVICORN_WORKERS": "4",
            "DB_POOL_SIZE": "20",
            "DB_MAX_OVERFLOW": "20",
        })


def test_app_launcher_passes_worker_count_to_uvicorn(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(app_launcher, "get_resource_root", lambda: tmp_path)
    monkeypatch.setattr(app_launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(app_launcher, "prepare_runtime_environment", lambda: None)
    monkeypatch.setattr(app_launcher, "verify_database_connection", lambda: None)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setattr(app_launcher.threading, "Thread", lambda **_kwargs: type(
        "FakeThread",
        (),
        {"start": lambda self: None},
    )())
    monkeypatch.setattr(
        app_launcher,
        "configure_server_runtime",
        lambda: type("Runtime", (), {"workers": 3})(),
    )
    monkeypatch.setattr(app_launcher.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert app_launcher.main() == 0

    assert calls[0][0] == ("server.main:app",)
    assert calls[0][1]["workers"] == 3
    assert calls[0][1]["port"] == 8123


def test_async_upload_routes_offload_complete_sync_units(monkeypatch):
    calls = []

    async def fake_run_in_threadpool(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr(documents, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(submissions, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(project_uploads, "run_in_threadpool", fake_run_in_threadpool)

    asyncio.run(documents.upload_and_assign_documents(
        template_id=1,
        user_ids="2",
        reviewer_user_ids="3",
        files=[],
        current_user={"id": 1},
        db=object(),
    ))
    asyncio.run(submissions.api_upload_pdf(
        file=object(),
        current_user={"id": 2},
        db=object(),
    ))

    class FakeRequest:
        async def body(self):
            return b"%PDF-test"

    asyncio.run(project_uploads.api_upload_project_file_chunk(
        session_id="session-1",
        file_id=1,
        request=FakeRequest(),
        upload_offset=0,
        current_user={"id": 1},
        db=object(),
    ))

    assert [call[0] for call in calls] == [
        documents._upload_and_assign_documents_sync,
        submissions._upload_pdf_sync,
        project_uploads.enforce_project_upload_chunk_rate_limit,
        project_uploads.write_upload_chunk,
    ]
    assert "timing_marks" in calls[-1][2]


def test_upload_route_emits_cloudflare_timing_event(monkeypatch, caplog):
    async def fake_run_in_threadpool(function, *args, **kwargs):
        if function is project_uploads.write_upload_chunk:
            marks = kwargs["timing_marks"]
            now = time.perf_counter()
            for name in (
                "file_lock_started",
                "file_lock_acquired",
                "file_write_started",
                "file_written",
                "fsync_started",
                "fsync_completed",
                "sha256_started",
                "sha256_completed",
                "database_update_started",
                "database_commit_started",
                "database_committed",
            ):
                marks[name] = now
                now += 0.001
            return {"status": "ok", "state": "uploaded"}
        return None

    class FakeRequest:
        headers = {"cf-ray": "test-ray"}
        state = type(
            "State",
            (),
            {"request_started_at": time.perf_counter() - 0.01},
        )()

        async def body(self):
            return b"%PDF-test"

    monkeypatch.setattr(project_uploads, "run_in_threadpool", fake_run_in_threadpool)
    with caplog.at_level(logging.INFO, logger="server.upload_timing"):
        result = asyncio.run(project_uploads.api_upload_project_file_chunk(
            session_id="session-1",
            file_id=7,
            request=FakeRequest(),
            upload_offset=0,
            current_user={"id": 1},
            db=object(),
        ))

    event = next(
        record.event_data
        for record in caplog.records
        if record.name == "server.upload_timing"
    )
    assert result["state"] == "uploaded"
    assert event["name"] == "project_upload_chunk_timing"
    assert event["request_source"] == "cloudflare"
    assert event["chunk_bytes"] == len(b"%PDF-test")
    assert event["body_received_ms"] is not None
    assert event["file_lock_acquired_ms"] is not None
    assert event["database_committed_ms"] is not None
    assert event["total_ms"] >= event["body_received_ms"]


def test_signal_server_controller_translates_stop_to_sigint(monkeypatch):
    signals = []
    monkeypatch.setattr(host_console.signal, "raise_signal", signals.append)
    controller = host_console.SignalServerController()

    controller.should_exit = True

    assert controller.should_exit is True
    assert signals == [host_console.signal.SIGINT]


def test_host_console_uses_public_multiworker_supervisor(monkeypatch):
    calls = []

    class FakeDashboard:
        def __init__(self, stats, _use_color, _interval):
            self.stats = stats

        def print_banner(self, _host, _port):
            return None

        def start(self):
            return None

        def stop(self):
            return None

        def set_state(self, _state):
            return None

    class FakeCommandCenter:
        def __init__(self, _dashboard, _server, *, use_color):
            self.use_color = use_color

        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr(host_console.os, "chdir", lambda _path: None)
    monkeypatch.setattr(host_console, "load_dotenv", lambda _path: None)
    monkeypatch.setattr(host_console, "configure_console", lambda: False)
    monkeypatch.setattr(
        host_console,
        "configure_server_runtime",
        lambda: type("Runtime", (), {"workers": 3})(),
    )
    monkeypatch.setattr(host_console, "ConsoleDashboard", FakeDashboard)
    monkeypatch.setattr(host_console, "HostCommandCenter", FakeCommandCenter)
    monkeypatch.setattr(
        host_console.uvicorn,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert host_console.main() == 0
    assert calls[0][0] == ("server.main:app",)
    assert calls[0][1]["workers"] == 3
