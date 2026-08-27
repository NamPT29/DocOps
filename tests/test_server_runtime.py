import asyncio
from pathlib import Path

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


def test_docker_runtime_uses_configurable_workers_and_bounded_pool():
    project_root = Path(__file__).parents[1]
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'CMD ["python", "-m", "server.runtime_config"]' in dockerfile
    assert "DB_POOL_SIZE=${DB_POOL_SIZE:-5}" in compose
    assert "DB_MAX_OVERFLOW=${DB_MAX_OVERFLOW:-2}" in compose


def test_app_launcher_passes_worker_count_to_uvicorn(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(app_launcher, "get_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(app_launcher.os, "chdir", lambda _path: None)
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

    app_launcher.main()

    assert calls[0][0] == ("server.main:app",)
    assert calls[0][1]["workers"] == 3


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
