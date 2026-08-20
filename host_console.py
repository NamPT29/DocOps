"""Colored host console and lightweight traffic monitor for the FastAPI app."""

from __future__ import annotations

import ctypes
import os
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


BASE_DIR = Path(__file__).resolve().parent
STARTED_AT = time.monotonic()


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


def format_status_line(
    state: str,
    traffic: TrafficSnapshot,
    system: SystemSnapshot,
    *,
    use_color: bool,
) -> str:
    state_color = Ansi.GREEN if state == "ONLINE" else Ansi.YELLOW
    if state in {"LỖI", "OFFLINE"}:
        state_color = Ansi.RED
    state_text = paint(f"● {state}", state_color, use_color, bold=True)
    total_text = paint(f"Truy cập {traffic.total}", Ansi.CYAN, use_color, bold=True)
    error_color = Ansi.RED if traffic.errors else Ansi.GREEN
    error_text = paint(f"Lỗi {traffic.errors}", error_color, use_color, bold=True)
    return (
        f" {state_text} │ {total_text} │ Người dùng {traffic.unique_clients}"
        f" │ Đang xử lý {traffic.active} │ {error_text} │ {traffic.per_minute}/phút"
        f" │ TB {traffic.average_ms:.0f}ms │ CPU {system.cpu_percent:.1f}%"
        f" │ RAM {system.process_ram_mb:.0f}MB ({system.system_ram_percent:.0f}%)"
        f" │ Đĩa {system.disk_percent:.0f}% │ {format_duration(time.monotonic() - STARTED_AT)} "
    )


class ConsoleDashboard:
    def __init__(self, stats: RequestStats, use_color: bool, interval: float) -> None:
        self.stats = stats
        self.use_color = use_color
        self.interval = max(0.5, interval)
        self.sampler = SystemSampler()
        self._state = "ĐANG NẠP"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def print_banner(self, host: str, port: int) -> None:
        os.system("cls" if os.name == "nt" else "clear")
        colors = (Ansi.CYAN, Ansi.CYAN, Ansi.BLUE, Ansi.BLUE, Ansi.MAGENTA, Ansi.MAGENTA)
        print()
        for line, color in zip(BANNER, colors):
            print(paint(f"  {line}", color, self.use_color, bold=True))
        print(paint("  HỆ THỐNG SỐ HÓA TÀI LIỆU • BẢNG GIÁM SÁT MÁY CHỦ", Ansi.WHITE, self.use_color, bold=True))
        print()

        local_url = f"http://127.0.0.1{f':{port}' if port != 80 else ''}"
        lan_url = f"http://{find_lan_ip()}{f':{port}' if port != 80 else ''}"
        border = "─" * 74

        def print_info_row(label: str, value: str, color: str = Ansi.WHITE) -> None:
            plain_prefix = f"  {label:<12}"
            padding = " " * max(0, len(border) - len(plain_prefix) - len(value))
            edge = paint("│", Ansi.BLUE, self.use_color)
            colored_value = paint(value, color, self.use_color, bold=True)
            print(f"  {edge}{plain_prefix}{colored_value}{padding}{edge}")

        print(paint(f"  ╭{border}╮", Ansi.BLUE, self.use_color))
        print_info_row("MÁY CHỦ", local_url, Ansi.CYAN)
        print_info_row("MẠNG NỘI BỘ", lan_url, Ansi.GREEN)
        print_info_row("LẮNG NGHE", f"{host}:{port}", Ansi.YELLOW)
        print_info_row("NHẬT KÝ", "logs\\app.log và logs\\error.log")
        print_info_row("ĐIỀU KHIỂN", "Nhấn Ctrl+C hoặc đóng cửa sổ để dừng máy chủ")
        print(paint(f"  ╰{border}╯", Ansi.BLUE, self.use_color))
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

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            print("\r\033[2K", end="", flush=True)

    def report_http_error(self, method: str, path: str, status_code: int) -> None:
        with self._lock:
            print("\r\033[2K", end="")
            label = paint(f"HTTP {status_code}", Ansi.RED, self.use_color, bold=True)
            print(f" {label} │ {method} {path}")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            traffic = self.stats.snapshot()
            system = self.sampler.sample()
            with self._lock:
                line = format_status_line(
                    self._state,
                    traffic,
                    system,
                    use_color=self.use_color,
                )
                print(f"\r\033[2K{line}", end="", flush=True)
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


def main() -> int:
    os.chdir(BASE_DIR)
    load_dotenv(BASE_DIR / ".env")
    use_color = configure_console()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "80"))
    interval = float(os.getenv("CONSOLE_STATS_INTERVAL", "1"))

    stats = RequestStats()
    dashboard = ConsoleDashboard(stats, use_color, interval)
    dashboard.print_banner(host, port)

    try:
        from server.main import app
    except Exception as exc:
        dashboard.set_state("LỖI")
        print(paint(f"\n  KHÔNG THỂ NẠP MÁY CHỦ: {exc}", Ansi.RED, use_color, bold=True))
        return 1

    monitored_app = TrafficMonitor(app, stats, dashboard)
    dashboard.start()
    config = uvicorn.Config(
        monitored_app,
        host=host,
        port=port,
        access_log=False,
        log_level="warning",
        use_colors=use_color,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.set_state("OFFLINE")
        dashboard.stop()

    final_stats = stats.snapshot()
    print(paint("  Máy chủ đã dừng an toàn.", Ansi.YELLOW, use_color, bold=True))
    print(
        f"  Phiên làm việc: {format_duration(time.monotonic() - STARTED_AT)}"
        f" • {final_stats.total} truy cập • {final_stats.errors} lỗi"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
