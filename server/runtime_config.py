from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass


MAX_UVICORN_WORKERS = 8
MAX_TOTAL_DB_CONNECTIONS = 64
DEFAULT_TOTAL_DB_POOL_SIZE = 20
DEFAULT_TOTAL_DB_OVERFLOW = 10


@dataclass(frozen=True)
class ServerRuntimeConfig:
    workers: int
    db_pool_size: int
    db_max_overflow: int


def _positive_int(value: str | None, *, name: str, default: int) -> int:
    try:
        parsed = int(value) if value else default
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là số nguyên dương.") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} phải là số nguyên dương.")
    return parsed


def _default_worker_count(cpu_count: int | None) -> int:
    available_cpus = max(1, int(cpu_count or 1))
    return min(4, max(1, available_cpus // 2))


def configure_server_runtime(
    environment: MutableMapping[str, str] | None = None,
    *,
    cpu_count: int | None = None,
) -> ServerRuntimeConfig:
    """Resolve worker count and bound default DB connections across workers."""
    target = environment if environment is not None else os.environ
    worker_count = _positive_int(
        target.get("UVICORN_WORKERS"),
        name="UVICORN_WORKERS",
        default=_default_worker_count(cpu_count if cpu_count is not None else os.cpu_count()),
    )
    if worker_count > MAX_UVICORN_WORKERS:
        raise RuntimeError(
            f"UVICORN_WORKERS không được vượt quá {MAX_UVICORN_WORKERS}."
        )

    default_pool_size = max(2, DEFAULT_TOTAL_DB_POOL_SIZE // worker_count)
    default_overflow = max(1, DEFAULT_TOTAL_DB_OVERFLOW // worker_count)
    target.setdefault("DB_POOL_SIZE", str(default_pool_size))
    target.setdefault("DB_MAX_OVERFLOW", str(default_overflow))

    pool_size = _positive_int(
        target.get("DB_POOL_SIZE"),
        name="DB_POOL_SIZE",
        default=default_pool_size,
    )
    max_overflow = _positive_int(
        target.get("DB_MAX_OVERFLOW"),
        name="DB_MAX_OVERFLOW",
        default=default_overflow,
    )
    total_connections = worker_count * (pool_size + max_overflow)
    if total_connections > MAX_TOTAL_DB_CONNECTIONS:
        raise RuntimeError(
            "Tổng kết nối database theo workers vượt quá "
            f"{MAX_TOTAL_DB_CONNECTIONS}: {worker_count} x "
            f"({pool_size} + {max_overflow}) = {total_connections}."
        )
    if worker_count > 1:
        target["MULTIPROCESS_LOGGING"] = "1"

    return ServerRuntimeConfig(
        workers=worker_count,
        db_pool_size=pool_size,
        db_max_overflow=max_overflow,
    )


def main() -> None:
    """Start Uvicorn through the same validated runtime contract in containers."""
    import uvicorn

    runtime = configure_server_runtime()
    port = _positive_int(os.environ.get("PORT"), name="PORT", default=8000)
    uvicorn.run(
        "server.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        workers=runtime.workers,
    )


if __name__ == "__main__":
    main()
