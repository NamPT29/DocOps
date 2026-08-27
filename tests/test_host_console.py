import asyncio
import os
import time

import host_console
from host_console import (
    ConsoleDashboard,
    HostCommandCenter,
    RequestStats,
    SystemSnapshot,
    TrafficMonitor,
    _read_memory_usage,
    build_dashboard_frame,
    format_duration,
    normalize_command_selection,
    read_log_tail,
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


def test_http_error_is_stored_without_printing_a_scrolling_line(capsys):
    dashboard = ConsoleDashboard(RequestStats(), use_color=False, interval=1)

    dashboard.report_http_error("GET", "/api/khong-ton-tai", 404)

    assert capsys.readouterr().out == ""
    assert dashboard._last_error == (404, "GET", "/api/khong-ton-tai")


def test_dashboard_renders_fixed_rows_without_newlines(monkeypatch, capsys):
    monkeypatch.setattr(host_console, "IS_WINDOWS", False, raising=False)
    dashboard = ConsoleDashboard(RequestStats(), use_color=True, interval=1)

    dashboard._render_lines("traffic", "system", "last error")

    output = capsys.readouterr().out
    assert "\n" not in output
    assert "\033[12;1H\033[2Ktraffic" in output
    assert "\033[13;1H\033[2Ksystem" in output
    assert "\033[14;1H\033[2Klast error" in output


def test_dashboard_uses_native_writer_on_windows(monkeypatch, capsys):
    calls = []

    def fake_writer(lines, start_row, width):
        calls.append((lines, start_row, width))
        return True

    monkeypatch.setattr(host_console, "IS_WINDOWS", True, raising=False)
    monkeypatch.setattr(
        host_console,
        "_write_windows_console_rows",
        fake_writer,
        raising=False,
    )
    dashboard = ConsoleDashboard(RequestStats(), use_color=True, interval=1)

    dashboard._render_lines("traffic", "system", "last error")

    assert calls == [
        (("traffic", "system", "last error"), 12, host_console.CONSOLE_WIDTH)
    ]
    assert capsys.readouterr().out == ""


def test_windows_line_padding_ignores_ansi_color_bytes():
    colored = "\033[92mONLINE\033[0m"

    padded = host_console._pad_console_line(colored, width=12)

    assert padded == f"{colored}{' ' * 5}"


def test_windows_line_padding_clips_before_console_wraps():
    padded = host_console._pad_console_line("123456789", width=8)

    assert padded == "123456…"
    assert len(padded) == 7


def test_format_duration_supports_long_running_server():
    assert format_duration(65) == "00:01:05"
    assert format_duration(90061) == "1d 01:01:01"


def test_memory_metrics_are_available_on_windows():
    process_ram_mb, system_ram_percent = _read_memory_usage()

    assert process_ram_mb >= 0
    assert 0 <= system_ram_percent <= 100
    if os.name == "nt":
        assert process_ram_mb > 0


def test_dashboard_frame_keeps_live_metrics_inside_one_box():
    traffic = RequestStats().snapshot()
    system = SystemSnapshot(
        cpu_percent=12.5,
        process_ram_mb=256,
        system_ram_percent=48,
        disk_percent=62,
    )

    lines = build_dashboard_frame(
        state="ONLINE",
        traffic=traffic,
        system=system,
        last_error=(404, "GET", "/api/missing"),
        uptime_seconds=65,
        use_color=False,
    )

    assert len(lines) == 8
    assert lines[0].startswith("  ╭")
    assert lines[-1].startswith("  ╰")
    assert all(line.startswith(("  │", "  ├", "  ╭", "  ╰")) for line in lines)
    assert "GIÁM SÁT TRỰC TIẾP" in lines[1]
    assert "ONLINE" in lines[2]
    assert "Truy cập [0]" in lines[2]
    assert "CPU toàn máy [12.5]%" in lines[3]
    assert "RAM ứng dụng [256]MB" in lines[3]
    assert "RAM toàn máy [48]%" in lines[3]
    assert "Đĩa [62]%" in lines[3]
    assert "HTTP [404]" in lines[4]
    separator_positions = [
        [index for index, character in enumerate(line) if character == "│"]
        for line in lines[2:5]
    ]
    assert separator_positions[0] == separator_positions[1] == separator_positions[2]
    assert "com" in lines[6]


def test_command_palette_accepts_numbers_and_command_names():
    assert normalize_command_selection("1") == "errorlog"
    assert normalize_command_selection(" ERRORLOG ") == "errorlog"
    assert normalize_command_selection("2") == "applog"
    assert normalize_command_selection("status") == "status"
    assert normalize_command_selection("6") == "stop"
    assert normalize_command_selection("unknown") is None


def test_command_center_opens_with_com(monkeypatch):
    class FakeServer:
        should_exit = False

    dashboard = ConsoleDashboard(RequestStats(), use_color=False, interval=1)
    command_center = HostCommandCenter(dashboard, FakeServer(), use_color=False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "com")
    monkeypatch.setattr(command_center, "_menu_loop", lambda: True)
    monkeypatch.setattr(dashboard, "pause", lambda: None)
    monkeypatch.setattr(dashboard, "redraw", lambda: None)
    monkeypatch.setattr(dashboard, "resume", lambda: None)

    command_center._run()


def test_read_log_tail_returns_only_recent_sanitized_lines(tmp_path):
    log_path = tmp_path / "error.log"
    log_path.write_text(
        "old\nsecond\nthird\tvalue\nfourth\x00value\n",
        encoding="utf-8",
    )

    lines = read_log_tail(log_path, limit=2)

    assert lines == ["third    value", "fourth value"]


def test_read_log_tail_merges_process_specific_worker_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("MULTIPROCESS_LOGGING", "1")
    (tmp_path / "app.100.log").write_text("worker-one\n", encoding="utf-8")
    (tmp_path / "app.200.log").write_text("worker-two\n", encoding="utf-8")

    lines = read_log_tail(tmp_path / "app.log", limit=5)

    assert sorted(lines) == [
        "[app.100.log] worker-one",
        "[app.200.log] worker-two",
    ]


def test_stop_command_requires_explicit_confirmation(monkeypatch):
    class FakeServer:
        should_exit = False

    dashboard = ConsoleDashboard(RequestStats(), use_color=False, interval=1)
    server = FakeServer()
    command_center = HostCommandCenter(dashboard, server, use_color=False)
    responses = iter(["6", "not-stop", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    should_stop_thread = command_center._menu_loop()

    assert should_stop_thread is False
    assert server.should_exit is False

    confirmed_center = HostCommandCenter(dashboard, server, use_color=False)
    responses = iter(["stop", "STOP"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    should_stop_thread = confirmed_center._menu_loop()

    assert should_stop_thread is True
    assert server.should_exit is True
