import os
import runpy
from pathlib import Path

import uvicorn


API_ENTRYPOINT = Path(__file__).resolve().parents[1] / "api.py"
SERVICE_ENTRYPOINT = Path(__file__).resolve().parents[1] / "src" / "api" / "service.py"


def _launch_with_api_host(monkeypatch, value: str | None, entrypoint=API_ENTRYPOINT) -> str:
    captured = {}

    def fake_run(app, *, host, port):
        captured["host"] = host

    monkeypatch.setattr(uvicorn, "run", fake_run)
    if value is None:
        monkeypatch.delenv("API_HOST", raising=False)
    else:
        monkeypatch.setenv("API_HOST", value)

    runpy.run_path(str(entrypoint), run_name="__main__")
    return captured["host"]


def test_api_launcher_defaults_to_loopback(monkeypatch):
    assert _launch_with_api_host(monkeypatch, None) == "127.0.0.1"


def test_api_launcher_host_can_be_explicitly_overridden(monkeypatch):
    assert _launch_with_api_host(monkeypatch, "192.0.2.10") == "192.0.2.10"


def test_service_launcher_defaults_to_loopback(monkeypatch):
    assert _launch_with_api_host(monkeypatch, None, SERVICE_ENTRYPOINT) == "127.0.0.1"


def test_service_launcher_host_can_be_explicitly_overridden(monkeypatch):
    assert _launch_with_api_host(monkeypatch, "192.0.2.10", SERVICE_ENTRYPOINT) == "192.0.2.10"
