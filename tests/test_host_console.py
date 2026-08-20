import asyncio
import os
import time

from host_console import (
    ConsoleDashboard,
    RequestStats,
    SystemSnapshot,
    TrafficMonitor,
    _read_memory_usage,
    format_duration,
    format_status_line,
    format_system_line,
)


def test_request_stats_counts_traffic_errors_and_clients():
    stats = RequestStats()

    first = stats.begin("10.0.0.10")
    stats.finish(first, 200, 120)
    second = stats.begin("10.0.0.11")
    stats.finish(second, 503, 30)

    snapshot = stats.snapshot()
    assert snapshot.total == 2
    assert snapshot.active == 0
    assert snapshot.errors == 1
    assert snapshot.per_minute == 2
    assert snapshot.unique_clients == 2
    assert snapshot.bytes_sent == 150
    assert snapshot.average_ms >= 0


def test_traffic_monitor_wraps_http_without_changing_response():
    stats = RequestStats()
    sent_messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"created"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/example",
        "client": ("192.168.1.20", 50000),
    }
    asyncio.run(TrafficMonitor(app, stats)(scope, receive, send))

    assert sent_messages[0]["status"] == 201
    assert sent_messages[1]["body"] == b"created"
    snapshot = stats.snapshot()
    assert snapshot.total == 1
    assert snapshot.errors == 0
    assert snapshot.unique_clients == 1
    assert snapshot.bytes_sent == 7


def test_traffic_monitor_counts_uncaught_exception_as_error():
    stats = RequestStats()

    async def app(scope, receive, send):
        raise RuntimeError("boom")

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        return None

    scope = {"type": "http", "method": "GET", "path": "/boom", "client": None}
    try:
        asyncio.run(TrafficMonitor(app, stats)(scope, receive, send))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("TrafficMonitor must preserve application exceptions")

    snapshot = stats.snapshot()
    assert snapshot.total == 1
    assert snapshot.errors == 1
    assert snapshot.active == 0


def test_status_line_contains_requested_live_metrics_without_color():
    stats = RequestStats()
    started = stats.begin("10.0.0.1")
    stats.finish(started, 200, 10)
    system = SystemSnapshot(
        cpu_percent=2.5,
        process_ram_mb=128,
        system_ram_percent=42,
        disk_percent=61,
    )

    traffic_line = format_status_line(
        "ONLINE", stats.snapshot(), system, use_color=False
    )
    system_line = format_system_line(system, use_color=False, uptime_seconds=65)

    assert "ONLINE" in traffic_line
    assert "Truy cập 1" in traffic_line
    assert "Người dùng 1" in traffic_line
    assert "Đang xử lý 0" in traffic_line
    assert "Lỗi 0" in traffic_line
    assert "CPU toàn máy 2.5%" in system_line
    assert "RAM ứng dụng 128MB" in system_line
    assert "RAM toàn máy 42%" in system_line
    assert "Đĩa 61%" in system_line
    assert "00:01:05" in system_line
    assert len(traffic_line) < 120
    assert len(system_line) < 120
    assert "\033[" not in traffic_line + system_line


def test_http_error_is_stored_without_printing_a_scrolling_line(capsys):
    dashboard = ConsoleDashboard(RequestStats(), use_color=False, interval=1)

    dashboard.report_http_error("GET", "/api/khong-ton-tai", 404)

    assert capsys.readouterr().out == ""
    assert dashboard._last_error == (404, "GET", "/api/khong-ton-tai")


def test_dashboard_renders_fixed_rows_without_newlines(capsys):
    dashboard = ConsoleDashboard(RequestStats(), use_color=True, interval=1)

    dashboard._render_lines("traffic", "system", "last error")

    output = capsys.readouterr().out
    assert "\n" not in output
    assert "\033[18;1H\033[2Ktraffic" in output
    assert "\033[19;1H\033[2Ksystem" in output
    assert "\033[20;1H\033[2Klast error" in output


def test_format_duration_supports_long_running_server():
    assert format_duration(65) == "00:01:05"
    assert format_duration(90061) == "1d 01:01:01"


def test_memory_metrics_are_available_on_windows():
    process_ram_mb, system_ram_percent = _read_memory_usage()

    assert process_ram_mb >= 0
    assert 0 <= system_ram_percent <= 100
    if os.name == "nt":
        assert process_ram_mb > 0
