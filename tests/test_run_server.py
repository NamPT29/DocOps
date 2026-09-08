import runpy
import sys
from pathlib import Path
from types import SimpleNamespace


def test_legacy_direct_launcher_is_loopback_development_only(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))),
    )
    monkeypatch.setitem(
        sys.modules,
        "server.migration_runner",
        SimpleNamespace(
            upgrade_database=lambda *_args, **_kwargs: SimpleNamespace(
                previous="0001_current_schema",
                current="0001_current_schema",
            ),
        ),
    )

    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "run_server.py"),
        run_name="__main__",
    )

    assert calls == [
        (("server.main:app",), {"host": "127.0.0.1", "port": 8000, "reload": True})
    ]
