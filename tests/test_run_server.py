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

    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "run_server.py"),
        run_name="__main__",
    )

    assert calls == [
        (("server.main:app",), {"host": "127.0.0.1", "port": 8000, "reload": True})
    ]
