from pathlib import Path
from types import SimpleNamespace

import pytest

from server import packaged_services


def test_start_packaged_caddy_skips_when_port_is_already_listening(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(packaged_services, "is_tcp_port_open", lambda *_args: True)

    process, status = packaged_services.start_packaged_caddy(tmp_path, tmp_path)

    assert process is None
    assert status == "already-running"


def test_start_packaged_caddy_uses_bundled_binary_and_config(monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    resource_root = tmp_path / "resources"
    app_dir.mkdir()
    resource_root.mkdir()
    (app_dir / "caddy.exe").write_bytes(b"caddy")
    (resource_root / "Caddyfile").write_text("http://example.test {}", encoding="utf-8")

    port_states = iter((False, True))
    monkeypatch.setattr(
        packaged_services,
        "is_tcp_port_open",
        lambda *_args: next(port_states),
    )
    calls = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(packaged_services.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(packaged_services.time, "sleep", lambda _seconds: None)

    process, status = packaged_services.start_packaged_caddy(
        app_dir,
        resource_root,
        attempts=1,
        delay_seconds=0,
    )

    assert isinstance(process, FakeProcess)
    assert status == "started"
    assert calls == [
        (
            [
                str(app_dir / "caddy.exe"),
                "run",
                "--config",
                str(resource_root / "Caddyfile"),
                "--adapter",
                "caddyfile",
            ],
            {"cwd": str(app_dir)},
        )
    ]


def test_start_packaged_caddy_requires_bundled_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(packaged_services, "is_tcp_port_open", lambda *_args: False)
    (tmp_path / "Caddyfile").write_text("http://example.test {}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="caddy.exe"):
        packaged_services.start_packaged_caddy(tmp_path, tmp_path)


@pytest.mark.parametrize(
    ("state_code", "expected"),
    (("4", "running"), ("1", "stopped"), ("2", "start-pending")),
)
def test_query_windows_service_state_uses_numeric_scm_state(
    monkeypatch, state_code, expected
):
    monkeypatch.setattr(
        packaged_services.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"STATE              : {state_code}  localized-text",
        ),
    )

    assert packaged_services.query_windows_service_state("Cloudflared") == expected


def test_ensure_cloudflared_service_starts_a_stopped_service(monkeypatch):
    states = iter(("stopped", "running"))
    starts = []
    monkeypatch.setattr(
        packaged_services,
        "query_windows_service_state",
        lambda _name: next(states),
    )
    monkeypatch.setattr(
        packaged_services.subprocess,
        "run",
        lambda command, **_kwargs: starts.append(command)
        or SimpleNamespace(returncode=0, stdout=""),
    )
    monkeypatch.setattr(packaged_services.time, "sleep", lambda _seconds: None)

    assert packaged_services.ensure_cloudflared_service() == "running"
    assert starts == [["sc.exe", "start", "Cloudflared"]]
