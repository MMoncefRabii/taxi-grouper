from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from src.api import service
from src.data import sheets_repository


@pytest.fixture(autouse=True)
def clear_oauth_states():
    with service._OAUTH_STATE_LOCK:
        service._OAUTH_STATES.clear()
    yield
    with service._OAUTH_STATE_LOCK:
        service._OAUTH_STATES.clear()


def _run(coroutine):
    return asyncio.run(coroutine)


def _login_state(monkeypatch) -> str:
    monkeypatch.setattr(sheets_repository, "CLIENT_ID", "test-client-id")
    monkeypatch.setattr(sheets_repository, "CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(sheets_repository, "REDIRECT_URI", "http://testserver/auth/callback")
    response = _run(service.auth_login_url())
    return parse_qs(urlparse(response["auth_url"]).query)["state"][0]


def test_valid_oauth_flow_exchanges_code_and_saves_tokens(monkeypatch):
    saved_tokens = []
    exchanged_codes = []
    monkeypatch.setattr(
        service,
        "exchange_code_for_token",
        lambda code: exchanged_codes.append(code) or {"access_token": "test-token"},
    )
    monkeypatch.setattr(service, "save_google_tokens", saved_tokens.append)

    state = _login_state(monkeypatch)
    response = _run(service.auth_callback(code="test-code", state=state))

    assert response.status_code == 307
    assert exchanged_codes == ["test-code"]
    assert saved_tokens == [{"access_token": "test-token"}]


@pytest.mark.parametrize("state_kind", ["missing", "wrong", "expired"])
def test_invalid_oauth_state_does_not_exchange_or_save_tokens(monkeypatch, state_kind):
    exchange_calls = []
    saved_tokens = []
    monkeypatch.setattr(service, "exchange_code_for_token", lambda code: exchange_calls.append(code))
    monkeypatch.setattr(service, "save_google_tokens", saved_tokens.append)

    issued_state = _login_state(monkeypatch)
    callback_state = issued_state
    if state_kind == "missing":
        callback_state = None
    elif state_kind == "wrong":
        callback_state = "not-a-issued-state"
    else:
        with service._OAUTH_STATE_LOCK:
            service._OAUTH_STATES[issued_state] = service.time.monotonic() - 1

    with pytest.raises(HTTPException) as error:
        _run(service.auth_callback(code="test-code", state=callback_state))

    assert error.value.status_code == 400
    assert exchange_calls == []
    assert saved_tokens == []


def test_reused_oauth_state_is_rejected_without_a_second_exchange_or_save(monkeypatch):
    exchange_calls = []
    saved_tokens = []
    monkeypatch.setattr(
        service,
        "exchange_code_for_token",
        lambda code: exchange_calls.append(code) or {"access_token": "test-token"},
    )
    monkeypatch.setattr(service, "save_google_tokens", saved_tokens.append)

    state = _login_state(monkeypatch)
    _run(service.auth_callback(code="test-code", state=state))

    with pytest.raises(HTTPException) as error:
        _run(service.auth_callback(code="test-code", state=state))

    assert error.value.status_code == 400
    assert len(exchange_calls) == 1
    assert len(saved_tokens) == 1


def test_oauth_state_store_is_bounded_and_purges_expired_entries(monkeypatch):
    monkeypatch.setattr(service, "_OAUTH_STATE_STORE_MAX_SIZE", 3)
    with service._OAUTH_STATE_LOCK:
        service._OAUTH_STATES["expired-state"] = service.time.monotonic() - 1

    for _ in range(8):
        service._create_oauth_state()

    with service._OAUTH_STATE_LOCK:
        assert len(service._OAUTH_STATES) == 3
        assert "expired-state" not in service._OAUTH_STATES


def test_access_denied_error_still_redirects_without_token_exchange(monkeypatch):
    exchange_calls = []
    saved_tokens = []
    monkeypatch.setattr(service, "exchange_code_for_token", lambda code: exchange_calls.append(code))
    monkeypatch.setattr(service, "save_google_tokens", saved_tokens.append)
    monkeypatch.setattr(
        service,
        "get_frontend_redirect_url",
        lambda succeeded, error=None: f"https://frontend.test/?auth={'success' if succeeded else 'error'}&error={error}",
    )

    state = _login_state(monkeypatch)
    response = _run(service.auth_callback(state=state, error="access_denied"))

    assert response.status_code == 307
    assert response.headers["location"].endswith("error=access_denied")
    assert exchange_calls == []
    assert saved_tokens == []


def test_exchange_failure_does_not_echo_authorization_code(monkeypatch):
    authorization_code = "sensitive-auth-code"
    saved_tokens = []

    def fail_exchange(code):
        raise RuntimeError(code)

    monkeypatch.setattr(service, "exchange_code_for_token", fail_exchange)
    monkeypatch.setattr(service, "save_google_tokens", saved_tokens.append)
    monkeypatch.setattr(
        service,
        "get_frontend_redirect_url",
        lambda succeeded, error=None: f"https://frontend.test/?auth=error&error={error}",
    )

    state = _login_state(monkeypatch)
    response = _run(
        service.auth_callback(code=authorization_code, state=state)
    )

    assert response.status_code == 307
    assert authorization_code not in response.headers["location"]
    assert saved_tokens == []


def test_auth_url_builder_includes_provided_state(monkeypatch):
    monkeypatch.setattr(sheets_repository, "CLIENT_ID", "test-client-id")
    monkeypatch.setattr(sheets_repository, "CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(sheets_repository, "REDIRECT_URI", "http://testserver/auth/callback")

    query = parse_qs(urlparse(sheets_repository.get_auth_url("test-state")).query)

    assert query["state"] == ["test-state"]
