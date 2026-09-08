"""Colored host console and lightweight traffic monitor for the FastAPI app."""

from __future__ import annotations

import ctypes
import logging
import multiprocessing
import os
import re
import signal
import shutil
import socket
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import uvicorn
from dotenv import load_dotenv
from server.runtime_config import configure_server_runtime


BASE_DIR = Path(__file__).resolve().parent
STARTED_AT = time.monotonic()
IS_WINDOWS = os.name == "nt"
CONSOLE_WIDTH = 112
PANEL_CONTENT_WIDTH = 105
METRIC_COLUMN_WIDTHS = (14, 21, 22, 22, 14)
LOG_TAIL_LINES = 14
ANSI_ESCAPE_RE = re.compile(r"\033\[[0-9;]*m")


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


BANNER = (
    "███████╗ ██████╗     ██╗  ██╗ ██████╗  █████╗",
    "██╔════╝██╔═══██╗    ██║  ██║██╔═══██╗██╔══██╗",
    "███████╗██║   ██║    ███████║██║   ██║███████║",
    "╚════██║██║   ██║    ██╔══██║██║   ██║██╔══██║",
    "███████║╚██████╔╝    ██║  ██║╚██████╔╝██║  ██║",
    "╚══════╝ ╚═════╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝",
)


def _enable_windows_console() -> bool:
    if os.name != "nt":
        return sys.stdout.isatty()

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleTitleW("SỐ HÓA • HOST SERVER")
        stdout_handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)
            return True
    except (AttributeError, OSError):
        pass
    return False


def configure_console() -> bool:
    """Enable UTF-8 and ANSI colors when the terminal supports them."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass

    if os.getenv("NO_COLOR") is not None:
        return False
    return _enable_windows_console() or (
        sys.stdout.isatty() and os.getenv("TERM", "").lower() != "dumb"
    )


def paint(text: str, color: str, enabled: bool, *, bold: bool = False) -> str:
    if not enabled:
        return text
    prefix = f"{Ansi.BOLD if bold else ''}{color}"
    return f"{prefix}{text}{Ansi.RESET}"


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class TrafficSnapshot:
    total: int
    active: int
    errors: int
    per_minute: int
    unique_clients: int
    average_ms: float
    bytes_sent: int


class RequestStats:
    """Thread-safe counters for requests handled by this server process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0
        self._active = 0
        self._errors = 0
        self._total_duration = 0.0
        self._bytes_sent = 0
        self._clients: set[str] = set()
        self._recent_requests: deque[float] = deque()

    def begin(self, client_ip: str) -> float:
        started = time.monotonic()
        with self._lock:
            self._active += 1
            if client_ip:
                self._clients.add(client_ip)
        return started

    def finish(self, started: float, status_code: int, bytes_sent: int) -> None:
        finished = time.monotonic()
        with self._lock:
            self._active = max(0, self._active - 1)
            self._total += 1
            if status_code >= 400:
                self._errors += 1
            self._total_duration += max(0.0, finished - started)
            self._bytes_sent += max(0, bytes_sent)
            self._recent_requests.append(finished)
            self._prune_recent(finished)

    def _prune_recent(self, now: float) -> None:
        cutoff = now - 60.0
        while self._recent_requests and self._recent_requests[0] < cutoff:
            self._recent_requests.popleft()

    def snapshot(self) -> TrafficSnapshot:
        now = time.monotonic()
        with self._lock:
            self._prune_recent(now)
            average_ms = (
                self._total_duration * 1000.0 / self._total if self._total else 0.0
            )
            return TrafficSnapshot(
                total=self._total,
                active=self._active,
                errors=self._errors,
                per_minute=len(self._recent_requests),
                unique_clients=len(self._clients),
                average_ms=average_ms,
                bytes_sent=self._bytes_sent,
            )


@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: float
    process_ram_mb: float
    system_ram_percent: float
    disk_percent: float


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong),
    ]


class _ConsoleCoord(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SmallRect(ctypes.Structure):
    _fields_ = [
        ("Left", ctypes.c_short),
        ("Top", ctypes.c_short),
        ("Right", ctypes.c_short),
        ("Bottom", ctypes.c_short),
    ]


class _ConsoleScreenBufferInfo(ctypes.Structure):
    _fields_ = [
        ("dwSize", _ConsoleCoord),
        ("dwCursorPosition", _ConsoleCoord),
        ("wAttributes", ctypes.c_ushort),
        ("srWindow", _SmallRect),
        ("dwMaximumWindowSize", _ConsoleCoord),
    ]


def _pad_console_line(line: str, width: int) -> str:
    writable_width = max(1, width - 1)
    visible_line = ANSI_ESCAPE_RE.sub("", line)
    visible_length = len(visible_line)
    if visible_length > writable_width:
        if writable_width == 1:
            return visible_line[:1]
        return f"{visible_line[:writable_width - 1]}…"
    return f"{line}{' ' * max(0, writable_width - visible_length)}"


def _write_windows_console_rows(
    lines: tuple[str, ...],
    start_row: int,
    width: int,
) -> bool:
    """Position and overwrite rows with the native Windows console API."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.SetConsoleCursorPosition.argtypes = [
            ctypes.c_void_p,
            _ConsoleCoord,
        ]
        kernel32.SetConsoleCursorPosition.restype = ctypes.c_int
        kernel32.GetConsoleScreenBufferInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ConsoleScreenBufferInfo),
        ]
        kernel32.GetConsoleScreenBufferInfo.restype = ctypes.c_int
        stdout_handle = kernel32.GetStdHandle(-11 & 0xFFFFFFFF)
        if not stdout_handle or stdout_handle == ctypes.c_void_p(-1).value:
            return False

        saved_position: _ConsoleCoord | None = None
        writable_width = width
        buffer_info = _ConsoleScreenBufferInfo()
        if kernel32.GetConsoleScreenBufferInfo(stdout_handle, ctypes.byref(buffer_info)):
            saved_position = _ConsoleCoord(
                buffer_info.dwCursorPosition.X,
                buffer_info.dwCursorPosition.Y,
            )
            writable_width = min(width, max(2, int(buffer_info.dwSize.X)))

        sys.stdout.flush()
        try:
            for offset, line in enumerate(lines):
                position = _ConsoleCoord(0, max(0, start_row - 1 + offset))
                if not kernel32.SetConsoleCursorPosition(stdout_handle, position):
                    return False
                sys.stdout.write(_pad_console_line(line, writable_width))
                sys.stdout.flush()
        finally:
            if saved_position is not None:
                kernel32.SetConsoleCursorPosition(stdout_handle, saved_position)
        return True
    except (AttributeError, OSError, ValueError):
        return False


def _filetime_value(value: _FileTime) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _read_system_cpu_times() -> tuple[int, int, int] | None:
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetSystemTimes.argtypes = [
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        kernel32.GetSystemTimes.restype = ctypes.c_int
        idle = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        return _filetime_value(idle), _filetime_value(kernel), _filetime_value(user)
    except (AttributeError, OSError):
        return None


def _read_memory_usage() -> tuple[float, float]:
    """Return process RAM in MB and total system RAM load percentage."""
    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_ProcessMemoryCounters),
                ctypes.c_ulong,
            ]
            psapi.GetProcessMemoryInfo.restype = ctypes.c_int
            kernel32.GlobalMemoryStatusEx.argtypes = [
                ctypes.POINTER(_MemoryStatusEx)
            ]
            kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            process = kernel32.GetCurrentProcess()
            process_ok = psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            )

            memory = _MemoryStatusEx()
            memory.dwLength = ctypes.sizeof(memory)
            system_ok = kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
            process_mb = counters.WorkingSetSize / (1024 * 1024) if process_ok else 0.0
            system_percent = float(memory.dwMemoryLoad) if system_ok else 0.0
            return process_mb, system_percent
        except (AttributeError, OSError):
            return 0.0, 0.0

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        with open("/proc/self/statm", encoding="ascii") as statm:
            resident_pages = int(statm.read().split()[1])
        process_mb = resident_pages * page_size / (1024 * 1024)
        total_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        system_percent = (1.0 - available_pages / total_pages) * 100.0
        return process_mb, system_percent
    except (AttributeError, OSError, ValueError, IndexError):
        return 0.0, 0.0


class SystemSampler:
    def __init__(self, disk_path: Path = BASE_DIR) -> None:
        self._disk_path = disk_path
        self._last_wall = time.monotonic()
        self._last_cpu = time.process_time()
        self._last_system_cpu = _read_system_cpu_times()

    def sample(self) -> SystemSnapshot:
        now_wall = time.monotonic()
        now_cpu = time.process_time()
        wall_delta = max(0.000001, now_wall - self._last_wall)
        cpu_delta = max(0.0, now_cpu - self._last_cpu)
        self._last_wall = now_wall
        self._last_cpu = now_cpu
        cpu_count = max(1, os.cpu_count() or 1)
        cpu_percent = min(100.0, cpu_delta / wall_delta * 100.0 / cpu_count)

        system_cpu = _read_system_cpu_times()
        if self._last_system_cpu is not None and system_cpu is not None:
            idle_delta = max(0, system_cpu[0] - self._last_system_cpu[0])
            kernel_delta = max(0, system_cpu[1] - self._last_system_cpu[1])
            user_delta = max(0, system_cpu[2] - self._last_system_cpu[2])
            total_delta = kernel_delta + user_delta
            if total_delta:
                cpu_percent = min(
                    100.0,
                    max(0.0, (total_delta - idle_delta) / total_delta * 100.0),
                )
        self._last_system_cpu = system_cpu

        process_ram_mb, system_ram_percent = _read_memory_usage()
        disk = shutil.disk_usage(self._disk_path)
        disk_percent = (disk.used / disk.total * 100.0) if disk.total else 0.0
        return SystemSnapshot(
            cpu_percent=cpu_percent,
            process_ram_mb=process_ram_mb,
            system_ram_percent=system_ram_percent,
            disk_percent=disk_percent,
        )


def find_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass

    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass
    return "127.0.0.1"


def _fit_console_text(text: str, width: int) -> str:
    visible = ANSI_ESCAPE_RE.sub("", text)
    if len(visible) <= width:
        return text
    return f"{visible[:max(0, width - 1)]}…"


def format_panel_row(
    content: str,
    *,
    use_color: bool,
    width: int = PANEL_CONTENT_WIDTH,
) -> str:
    fitted = _fit_console_text(content.strip(), width)
    visible_length = len(ANSI_ESCAPE_RE.sub("", fitted))
    edge = paint("│", Ansi.BLUE, use_color)
    return f"  {edge} {fitted}{' ' * max(0, width - visible_length)} {edge}"


def format_panel_rule(
    left: str,
    fill: str,
    right: str,
    *,
    use_color: bool,
    width: int = PANEL_CONTENT_WIDTH,
) -> str:
    return paint(f"  {left}{fill * (width + 2)}{right}", Ansi.BLUE, use_color)


def format_metric_row(cells: tuple[str, ...]) -> str:
    if len(cells) != len(METRIC_COLUMN_WIDTHS):
        raise ValueError("Số ô giám sát không khớp cấu hình cột")
    formatted_cells = []
    for cell, width in zip(cells, METRIC_COLUMN_WIDTHS):
        fitted = _fit_console_text(cell.strip(), width)
        visible_length = len(ANSI_ESCAPE_RE.sub("", fitted))
        formatted_cells.append(
            f"{fitted}{' ' * max(0, width - visible_length)}"
        )
    return " │ ".join(formatted_cells)


def format_monitor_lines(
    state: str,
    traffic: TrafficSnapshot,
    system: SystemSnapshot,
    last_error: tuple[int, str, str] | None,
    *,
    use_color: bool,
    uptime_seconds: float,
) -> tuple[str, str, str]:
    state_color = Ansi.GREEN if state == "ONLINE" else Ansi.YELLOW
    if state in {"LỖI", "OFFLINE"}:
        state_color = Ansi.RED
    state_cell = paint(f"● {state}", state_color, use_color, bold=True)

    traffic_line = format_metric_row((
        state_cell,
        f"Truy cập [{traffic.total}]",
        f"Người dùng [{traffic.unique_clients}]",
        f"Đang xử lý [{traffic.active}]",
        f"Lỗi [{traffic.errors}]",
    ))
    system_line = format_metric_row((
        paint("HỆ THỐNG", Ansi.MAGENTA, use_color, bold=True),
        f"CPU toàn máy [{system.cpu_percent:.1f}]%",
        f"RAM ứng dụng [{system.process_ram_mb:.0f}]MB",
        f"RAM toàn máy [{system.system_ram_percent:.0f}]%",
        f"Đĩa [{system.disk_percent:.0f}]%",
    ))
    rate_text = f"[{traffic.per_minute}]/phút · TB [{traffic.average_ms:.0f}]ms"
    uptime_text = f"Hoạt động [{format_duration(uptime_seconds)}]"
    if last_error is None:
        error_cells = (
            "LỖI GẦN NHẤT",
            "[Không có lỗi HTTP]",
            rate_text,
            uptime_text,
            "",
        )
    else:
        status_code, method, path = last_error
        error_cells = (
            "LỖI GẦN NHẤT",
            f"[HTTP [{status_code}] {method}]",
            path,
            rate_text,
            f"[{format_duration(uptime_seconds)}]",
        )
    return traffic_line, system_line, format_metric_row(error_cells)


def build_dashboard_frame(
    *,
    state: str,
    traffic: TrafficSnapshot,
    system: SystemSnapshot,
    last_error: tuple[int, str, str] | None,
    uptime_seconds: float,
    use_color: bool,
) -> tuple[str, ...]:
    monitor_title = paint("GIÁM SÁT TRỰC TIẾP", Ansi.WHITE, use_color, bold=True)
    command_hint = paint("com", Ansi.CYAN, use_color, bold=True)
    monitor_lines = format_monitor_lines(
        state,
        traffic,
        system,
        last_error,
        use_color=use_color,
        uptime_seconds=uptime_seconds,
    )
    return (
        format_panel_rule("╭", "─", "╮", use_color=use_color),
        format_panel_row(monitor_title, use_color=use_color),
        *(format_panel_row(line, use_color=use_color) for line in monitor_lines),
        format_panel_rule("├", "─", "┤", use_color=use_color),
        format_panel_row(
            f"LỆNH          Gõ {command_hint} rồi Enter để mở trung tâm lệnh",
            use_color=use_color,
        ),
        format_panel_rule("╰", "─", "╯", use_color=use_color),
    )


class ConsoleDashboard:
    STATUS_ROW = 12

    def __init__(self, stats: RequestStats, use_color: bool, interval: float) -> None:
        self.stats = stats
        self.use_color = use_color
        self.interval = max(0.5, interval)
        self.sampler = SystemSampler()
        self._state = "ĐANG NẠP"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: tuple[int, str, str] | None = None
        self._host = "0.0.0.0"
        self._port = 80
        self._local_url = "http://127.0.0.1"
        self._lan_url = "http://127.0.0.1"

    def print_banner(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        port_suffix = f":{port}" if port != 80 else ""
        self._local_url = f"http://127.0.0.1{port_suffix}"
        self._lan_url = f"http://{find_lan_ip()}{port_suffix}"
        traffic = self.stats.snapshot()
        system = self.sampler.sample()
        with self._lock:
            state = self._state
            last_error = self._last_error
            os.system("cls" if os.name == "nt" else "clear")
            colors = (
                Ansi.CYAN,
                Ansi.CYAN,
                Ansi.BLUE,
                Ansi.BLUE,
                Ansi.MAGENTA,
                Ansi.MAGENTA,
            )
            print()
            for line, color in zip(BANNER, colors):
                print(paint(f"  {line}", color, self.use_color, bold=True))
            print(paint(
                "  HỆ THỐNG SỐ HÓA TÀI LIỆU • BẢNG GIÁM SÁT MÁY CHỦ",
                Ansi.WHITE,
                self.use_color,
                bold=True,
            ))
            print()
            for line in build_dashboard_frame(
                state=state,
                traffic=traffic,
                system=system,
                last_error=last_error,
                uptime_seconds=time.monotonic() - STARTED_AT,
                use_color=self.use_color,
            ):
                print(line)
            print()

    def set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="host-console-dashboard",
            daemon=True,
        )
        self._thread.start()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def redraw(self) -> None:
        self.print_banner(self._host, self._port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            print("\r\033[2K", end="", flush=True)

    def report_http_error(self, method: str, path: str, status_code: int) -> None:
        with self._lock:
            self._last_error = (status_code, method, path)

    def _render_lines(self, *lines: str) -> None:
        if IS_WINDOWS:
            _write_windows_console_rows(lines, self.STATUS_ROW, CONSOLE_WIDTH)
            return
        if self.use_color:
            frame = "".join(
                f"\033[{self.STATUS_ROW + offset};1H\033[2K{line}"
                for offset, line in enumerate(lines)
            )
        else:
            frame = f"\r{lines[0][:118]:<118}"
        sys.stdout.write(frame)
        sys.stdout.flush()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                self._stop_event.wait(0.1)
                continue
            traffic = self.stats.snapshot()
            system = self.sampler.sample()
            with self._lock:
                monitor_lines = format_monitor_lines(
                    self._state,
                    traffic,
                    system,
                    self._last_error,
                    use_color=self.use_color,
                    uptime_seconds=time.monotonic() - STARTED_AT,
                )
                self._render_lines(*(
                    format_panel_row(item, use_color=self.use_color)
                    for item in monitor_lines
                ))
            self._stop_event.wait(self.interval)


ASGIApp = Callable[
    [dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]],
    Awaitable[None],
]


class TrafficMonitor:
    """ASGI wrapper that gathers traffic metrics without changing FastAPI routes."""

    def __init__(
        self,
        app: ASGIApp,
        stats: RequestStats,
        dashboard: ConsoleDashboard | None = None,
    ) -> None:
        self.app = app
        self.stats = stats
        self.dashboard = dashboard

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return
        if scope_type != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client") or ("", 0)
        client_ip = str(client[0]) if client else ""
        started = self.stats.begin(client_ip)
        status_code = 500
        bytes_sent = 0

        async def monitored_send(message: dict[str, Any]) -> None:
            nonlocal status_code, bytes_sent
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            elif message.get("type") == "http.response.body":
                body = message.get("body", b"")
                bytes_sent += len(body) if body else 0
            await send(message)

        try:
            await self.app(scope, receive, monitored_send)
        finally:
            self.stats.finish(started, status_code, bytes_sent)
            if status_code >= 400 and self.dashboard is not None:
                self.dashboard.report_http_error(
                    str(scope.get("method", "HTTP")),
                    str(scope.get("path", "/")),
                    status_code,
                )

    async def _handle_lifespan(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        async def monitored_send(message: dict[str, Any]) -> None:
            message_type = message.get("type")
            if self.dashboard is not None:
                if message_type == "lifespan.startup.complete":
                    self.dashboard.set_state("ONLINE")
                elif message_type == "lifespan.startup.failed":
                    self.dashboard.set_state("LỖI")
                elif message_type == "lifespan.shutdown.complete":
                    self.dashboard.set_state("OFFLINE")
            await send(message)

        await self.app(scope, receive, monitored_send)


COMMAND_OPTIONS = (
    ("1", "errorlog", "Xem các dòng lỗi gần nhất"),
    ("2", "applog", "Xem hoạt động gần nhất của ứng dụng"),
    ("3", "status", "Xem đầy đủ trạng thái và tài nguyên"),
    ("4", "network", "Xem địa chỉ truy cập và cổng lắng nghe"),
    ("5", "refresh", "Làm mới và quay về bảng giám sát"),
    ("6", "stop", "Dừng máy chủ an toàn (cần xác nhận)"),
    ("0", "back", "Đóng trung tâm lệnh"),
)
COMMAND_ALIASES = {
    alias: name
    for number, name, _description in COMMAND_OPTIONS
    for alias in (number, name)
}


def normalize_command_selection(value: str) -> str | None:
    return COMMAND_ALIASES.get(value.strip().lower())


def read_log_tail(path: Path, limit: int = LOG_TAIL_LINES) -> list[str]:
    candidates = [path] if path.is_file() else []
    if os.environ.get("MULTIPROCESS_LOGGING") == "1":
        worker_logs = [
            candidate
            for candidate in path.parent.glob(f"{path.stem}.*{path.suffix}")
            if candidate.is_file()
        ]
        if worker_logs:
            candidates = worker_logs
    if not candidates:
        return [f"Không tìm thấy tệp: {path}"]

    candidates.sort(key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name))
    annotate_source = len(candidates) > 1 or candidates[0] != path
    raw_lines: deque[str] = deque(maxlen=max(1, limit))
    try:
        for candidate in candidates:
            with candidate.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    prefix = f"[{candidate.name}] " if annotate_source else ""
                    raw_lines.append(f"{prefix}{raw_line}")
    except OSError as exc:
        return [f"Không thể đọc nhật ký: {exc}"]
    if not raw_lines:
        return ["Nhật ký đang trống."]
    cleaned_lines = []
    for raw_line in raw_lines:
        line = ANSI_ESCAPE_RE.sub("", raw_line.rstrip("\r\n"))
        line = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", line)
        cleaned_lines.append(line.replace("\t", "    ") or " ")
    return cleaned_lines


class HostCommandCenter:
    """Interactive command palette kept separate from the live dashboard."""

    def __init__(
        self,
        dashboard: ConsoleDashboard,
        server: uvicorn.Server,
        *,
        use_color: bool,
    ) -> None:
        self.dashboard = dashboard
        self.server = server
        self.use_color = use_color
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None or not sys.stdin:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="host-console-commands",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                raw_command = input("  LỆNH > ").strip().lower()
            except (EOFError, OSError):
                return
            if not raw_command:
                continue
            if raw_command not in {"com", "cm", "command"}:
                print(paint(
                    "  Lệnh chưa nhận diện. Gõ com rồi Enter để mở danh sách lệnh.",
                    Ansi.YELLOW,
                    self.use_color,
                ))
                continue

            self.dashboard.pause()
            try:
                should_return = self._menu_loop()
            finally:
                if not self._stop_event.is_set() and not self.server.should_exit:
                    self.dashboard.redraw()
                    self.dashboard.resume()
            if should_return:
                return

    def _menu_loop(self) -> bool:
        while not self._stop_event.is_set():
            self._show_menu()
            try:
                selection = input("  CHỌN LỆNH > ")
            except (EOFError, OSError):
                return True
            command = normalize_command_selection(selection)
            if command is None:
                self._show_result(
                    "LỆNH KHÔNG HỢP LỆ",
                    ["Hãy nhập số hoặc tên lệnh đúng như danh sách."],
                )
                if not self._wait_for_menu():
                    return True
                continue
            if command in {"back", "refresh"}:
                return False
            if command == "stop":
                if self._confirm_stop():
                    self.server.should_exit = True
                    self._stop_event.set()
                    return True
                continue

            title, lines = self._command_result(command)
            self._show_result(title, lines)
            if not self._wait_for_menu():
                return True
        return True

    def _show_menu(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")
        title = paint("COM • TRUNG TÂM LỆNH", Ansi.CYAN, self.use_color, bold=True)
        print(format_panel_rule("╭", "─", "╮", use_color=self.use_color))
        print(format_panel_row(title, use_color=self.use_color))
        print(format_panel_rule("├", "─", "┤", use_color=self.use_color))
        for number, name, description in COMMAND_OPTIONS:
            command_name = paint(name, Ansi.YELLOW, self.use_color, bold=True)
            print(format_panel_row(
                f"{number}. {command_name:<12} {description}",
                use_color=self.use_color,
            ))
        print(format_panel_rule("╰", "─", "╯", use_color=self.use_color))
        print()

    def _show_result(self, title: str, lines: list[str]) -> None:
        os.system("cls" if os.name == "nt" else "clear")
        colored_title = paint(title, Ansi.CYAN, self.use_color, bold=True)
        print(format_panel_rule("╭", "─", "╮", use_color=self.use_color))
        print(format_panel_row(colored_title, use_color=self.use_color))
        print(format_panel_rule("├", "─", "┤", use_color=self.use_color))
        for line in lines:
            print(format_panel_row(line, use_color=self.use_color))
        print(format_panel_rule("╰", "─", "╯", use_color=self.use_color))
        print()

    def _command_result(self, command: str) -> tuple[str, list[str]]:
        if command == "errorlog":
            return "ERROR LOG • DÒNG GẦN NHẤT", read_log_tail(
                BASE_DIR / "logs" / "error.log"
            )
        if command == "applog":
            return "APP LOG • DÒNG GẦN NHẤT", read_log_tail(
                BASE_DIR / "logs" / "app.log"
            )
        if command == "network":
            return "THÔNG TIN KẾT NỐI", [
                f"Máy chủ:      {self.dashboard._local_url}",
                f"Mạng nội bộ:  {self.dashboard._lan_url}",
                f"Lắng nghe:    {self.dashboard._host}:{self.dashboard._port}",
                f"Tiến trình:   PID {os.getpid()}",
            ]

        traffic = self.dashboard.stats.snapshot()
        system = self.dashboard.sampler.sample()
        with self.dashboard._lock:
            state = self.dashboard._state
            last_error = self.dashboard._last_error
        error_text = (
            "Không có lỗi HTTP"
            if last_error is None
            else f"HTTP {last_error[0]} • {last_error[1]} {last_error[2]}"
        )
        return "TRẠNG THÁI MÁY CHỦ", [
            f"Trạng thái: {state}    │    Hoạt động: {format_duration(time.monotonic() - STARTED_AT)}",
            f"Truy cập: {traffic.total}    │    Người dùng: {traffic.unique_clients}    │    Đang xử lý: {traffic.active}",
            f"Lỗi: {traffic.errors}    │    Tốc độ: {traffic.per_minute}/phút    │    Trung bình: {traffic.average_ms:.0f}ms",
            f"CPU toàn máy: {system.cpu_percent:.1f}%    │    RAM ứng dụng: {system.process_ram_mb:.0f}MB",
            f"RAM toàn máy: {system.system_ram_percent:.0f}%    │    Đĩa: {system.disk_percent:.0f}%",
            f"Lỗi gần nhất: {error_text}",
        ]

    def _wait_for_menu(self) -> bool:
        try:
            input("  Nhấn Enter để quay lại danh sách lệnh...")
        except (EOFError, OSError):
            return False
        return True

    def _confirm_stop(self) -> bool:
        self._show_result(
            "XÁC NHẬN DỪNG MÁY CHỦ",
            [
                "Các kết nối đang xử lý sẽ được đóng theo cơ chế an toàn.",
                "Nhập STOP để xác nhận; nhập giá trị khác để hủy.",
            ],
        )
        try:
            return input("  XÁC NHẬN > ").strip().upper() == "STOP"
        except (EOFError, OSError):
            return False


def silence_console_logging() -> None:
    """Remove any StreamHandler sending logs to stdout/stderr so the dashboard remains clean."""
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if type(handler) is logging.StreamHandler or (
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ):
            root_logger.removeHandler(handler)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "alembic",
        "alembic.runtime.migration",
        "sqlalchemy",
        "sqlalchemy.engine",
        "server",
        "server.http",
        "server.audit",
        "server.upload_timing",
    ):
        target_logger = logging.getLogger(logger_name)
        target_logger.handlers = [
            h
            for h in target_logger.handlers
            if not (isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler))
        ]


class _StderrLogRedirector:
    """Redirect unhandled stderr output to logs/error.log to keep the console dashboard clean."""

    def __init__(self, target_path: Path) -> None:
        self._target_path = target_path
        self._original_stderr = sys.stderr
        self._file: Any = None

    def __enter__(self) -> _StderrLogRedirector:
        try:
            self._target_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self._target_path, "a", encoding="utf-8", errors="replace")
            sys.stderr = self._file
        except OSError:
            pass
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass
            self._file = None
        sys.stderr = self._original_stderr


class SignalServerController:
    """Adapter that lets the command center stop Uvicorn's public supervisor."""

    def __init__(self) -> None:
        self._should_exit = False

    @property
    def should_exit(self) -> bool:
        return self._should_exit

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        if value and not self._should_exit:
            self._should_exit = True
            signal.raise_signal(signal.SIGINT)


def migrate_database_before_server():
    """Run Alembic once in the parent process before workers are created."""
    from server.database import engine
    from server.migration_runner import upgrade_database

    # A pre-Alembic database is stamped only after read-only validation of all
    # required baseline structures. Partial/legacy schemas stop with an error.
    return upgrade_database(engine, base_dir=BASE_DIR, adopt_existing=True)


def main() -> int:
    os.chdir(BASE_DIR)
    load_dotenv(BASE_DIR / ".env")
    use_color = configure_console()
    silence_console_logging()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "80"))
    interval = float(os.getenv("CONSOLE_STATS_INTERVAL", "1"))
    runtime = configure_server_runtime()
    try:
        migration = migrate_database_before_server()
        print(
            paint(
                (
                    f"  Database migration: {migration.previous or '<none>'} "
                    f"-> {migration.current}"
                    f"{' (adopted existing schema)' if migration.adopted_existing else ''}"
                ),
                Ansi.GREEN,
                use_color,
                bold=True,
            )
        )
    except Exception as exc:
        print(paint(f"  KHÔNG THỂ MIGRATE DATABASE: {exc}", Ansi.RED, use_color, bold=True))
        print("  Schema không khớp baseline; hãy backup và kiểm tra migration log.")
        return 1

    silence_console_logging()
    stats = RequestStats()
    dashboard = ConsoleDashboard(stats, use_color, interval)
    dashboard.print_banner(host, port)

    dashboard.start()
    if runtime.workers == 1:
        try:
            from server.main import app
        except Exception as exc:
            dashboard.set_state("LỖI")
            dashboard.stop()
            print(paint(f"\n  KHÔNG THỂ NẠP MÁY CHỦ: {exc}", Ansi.RED, use_color, bold=True))
            return 1
        monitored_app = TrafficMonitor(app, stats, dashboard)
        config = uvicorn.Config(
            monitored_app,
            host=host,
            port=port,
            access_log=False,
            log_level="warning",
            use_colors=use_color,
            log_config=None,
        )
        server = uvicorn.Server(config)
        run_server = server.run
    else:
        dashboard.set_state(f"ONLINE • {runtime.workers} WORKERS")
        server = SignalServerController()

        def run_server():
            uvicorn.run(
                "server.main:app",
                host=host,
                port=port,
                access_log=False,
                log_level="warning",
                use_colors=use_color,
                workers=runtime.workers,
                log_config=None,
            )

    command_center = HostCommandCenter(
        dashboard,
        server,
        use_color=use_color,
    )
    command_center.start()
    try:
        with _StderrLogRedirector(BASE_DIR / "logs" / "error.log"):
            run_server()
    except KeyboardInterrupt:
        pass
    finally:
        command_center.stop()
        dashboard.set_state("OFFLINE")
        dashboard.stop()

    final_stats = stats.snapshot()
    print(paint("  Máy chủ đã dừng an toàn.", Ansi.YELLOW, use_color, bold=True))
    if runtime.workers == 1:
        print(
            f"  Phiên làm việc: {format_duration(time.monotonic() - STARTED_AT)}"
            f" • {final_stats.total} truy cập • {final_stats.errors} lỗi"
        )
    else:
        print(
            f"  Phiên làm việc: {format_duration(time.monotonic() - STARTED_AT)}"
            f" • {runtime.workers} workers • dùng lệnh applog để xem log theo worker"
        )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
