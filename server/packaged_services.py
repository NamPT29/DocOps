"""Lifecycle helpers for packaged Windows reverse-proxy dependencies."""

from __future__ import annotations

import re
import socket
import subprocess
from pathlib import Path
import time


_SERVICE_STATES = {
    1: "stopped",
    2: "start-pending",
    3: "stop-pending",
    4: "running",
    5: "continue-pending",
    6: "pause-pending",
    7: "paused",
}


def is_tcp_port_open(host: str, port: int, *, timeout_seconds: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def start_packaged_caddy(
    application_dir: str | Path,
    resource_root: str | Path,
    *,
    attempts: int = 20,
    delay_seconds: float = 0.25,
) -> tuple[subprocess.Popen[bytes] | None, str]:
    """Start the bundled Caddy only when no process is already serving port 80."""
    if is_tcp_port_open("127.0.0.1", 80):
        return None, "already-running"

    app_dir = Path(application_dir)
    resources = Path(resource_root)
    caddy_executable = app_dir / "caddy.exe"
    caddy_config = resources / "Caddyfile"
    if not caddy_executable.is_file():
        raise RuntimeError(f"Khong tim thay Caddy dong kem: {caddy_executable}")
    if not caddy_config.is_file():
        raise RuntimeError(f"Khong tim thay Caddyfile: {caddy_config}")

    process = subprocess.Popen(
        [
            str(caddy_executable),
            "run",
            "--config",
            str(caddy_config),
            "--adapter",
            "caddyfile",
        ],
        cwd=str(app_dir),
    )
    for _attempt in range(attempts):
        if process.poll() is not None:
            raise RuntimeError(
                f"Caddy da dung voi ma thoat {process.poll()}. Kiem tra console."
            )
        time.sleep(delay_seconds)
        if is_tcp_port_open("127.0.0.1", 80):
            return process, "started"

    stop_managed_caddy(process)
    raise RuntimeError("Caddy khong lang nghe tren cong 80 sau khi khoi dong.")


def stop_managed_caddy(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def query_windows_service_state(service_name: str) -> str:
    """Return a locale-independent Windows SCM state using its numeric code."""
    try:
        result = subprocess.run(
            ["sc.exe", "query", service_name],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not-installed"
    if result.returncode != 0:
        return "not-installed"

    match = re.search(r"STATE\s*:\s*(\d+)", result.stdout, flags=re.IGNORECASE)
    if not match:
        return "unknown"
    return _SERVICE_STATES.get(int(match.group(1)), "unknown")


def ensure_cloudflared_service(service_name: str = "Cloudflared") -> str:
    """Start an already-installed Tunnel service when possible, without tokens."""
    state = query_windows_service_state(service_name)
    if state != "stopped":
        return state

    try:
        subprocess.run(
            ["sc.exe", "start", service_name],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "stopped"
    time.sleep(1)
    return query_windows_service_state(service_name)
