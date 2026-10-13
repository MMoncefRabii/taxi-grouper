import asyncio
import json

from src.api.service import app


API_KEY = "test-only-api-key-with-at-least-32-bytes"
PUBLIC_AND_OAUTH_HANDSHAKE = {
    ("GET", "/health"),
    ("GET", "/api/auth/login-url"),
    ("GET", "/auth/callback"),
}


def _request(method: str, path: str, api_key: str | None = None):
    headers = [(b"host", b"testserver")]
    if api_key is not None:
        headers.append((b"authorization", f"Bearer {api_key}".encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 123),
        "server": ("testserver", 80),
    }
    sent = []
    body_received = False

    async def receive():
        nonlocal body_received
        if not body_received:
            body_received = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    return status, json.loads(body) if body else {}


def _registered_routes():
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            for method in methods:
                yield method, path


def test_every_registered_non_public_route_rejects_missing_api_key(monkeypatch):
    monkeypatch.setenv("TAXI_GROUPER_API_KEY", API_KEY)
    protected_routes = set(_registered_routes()) - PUBLIC_AND_OAUTH_HANDSHAKE
    assert protected_routes

    for method, path in sorted(protected_routes):
        status, response = _request(method, path)
        assert status == 401, f"{method} {path} should require authentication, got {status}: {response}"
        assert response == {"detail": "Unauthorized"}


def test_health_route_remains_public(monkeypatch):
    monkeypatch.delenv("TAXI_GROUPER_API_KEY", raising=False)

    status, response = _request("GET", "/health")

    assert status == 200
    assert response == {"status": "ok"}


def test_protected_route_rejects_wrong_key_and_accepts_configured_key(monkeypatch):
    monkeypatch.setenv("TAXI_GROUPER_API_KEY", API_KEY)

    wrong_status, _wrong_response = _request("POST", "/api/export", "incorrect")
    valid_status, _valid_response = _request("POST", "/api/export", API_KEY)

    assert wrong_status == 401
    assert valid_status != 401


def test_protected_route_fails_closed_when_server_key_is_missing(monkeypatch):
    monkeypatch.delenv("TAXI_GROUPER_API_KEY", raising=False)

    status, response = _request("POST", "/api/export", API_KEY)

    assert status == 503
    assert response == {"detail": "Service authentication is not configured."}
