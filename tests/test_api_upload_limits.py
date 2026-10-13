import asyncio
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from starlette.datastructures import UploadFile as StarletteUploadFile

from src.api import service
from src.config import TAXI_COLUMN


MULTIPART_OVERHEAD_LIMIT = 64 * 1024
TEST_LIMIT = 128


def _setup_grouping(monkeypatch):
    monkeypatch.setattr(service, "load_dispatch_excel", lambda *_args, **_kwargs: pd.DataFrame({"Address": ["A"]}))
    monkeypatch.setattr(service, "detect_columns", lambda _df: object())
    monkeypatch.setattr(service, "filter_dataframe", lambda df, *_args, **_kwargs: df)
    monkeypatch.setattr(
        service,
        "group_agents",
        lambda df, **_kwargs: (pd.DataFrame({TAXI_COLUMN: [1], "Zone": ["A"]}), []),
    )
    monkeypatch.setattr(
        service,
        "validate_dispatch",
        lambda *_args, **_kwargs: {"valid": True, "errors": [], "warnings": [], "taxi_reports": []},
    )
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(max_upload_size_bytes=TEST_LIMIT))


def _call_asgi_request(
    body: bytes,
    content_length: int | None = None,
    include_content_length: bool = True,
):
    boundary = "taxi-grouper-test-boundary"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/group",
        "raw_path": b"/api/group",
        "query_string": b"",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
    }
    if include_content_length:
        scope["headers"].append(
            (
                b"content-length",
                str(len(body) if content_length is None else content_length).encode(),
            )
        )
    messages = []
    body_sent = False

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(service.app(scope, receive, send))
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return response_start["status"], json.loads(response_body)


def _post_file(content: bytes, filename: str = "dispatch.xlsx"):
    boundary = "taxi-grouper-test-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return _call_asgi_request(body)


def test_upload_at_configured_limit_is_accepted(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))

    status, response = _post_file(b"PK" + b"x" * (TEST_LIMIT - 2))

    assert status == 200
    assert "grouped_data" in response
    assert list(tmp_path.iterdir()) == []


def test_upload_one_byte_over_limit_returns_413_and_cleans_temp_file(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))

    status, response = _post_file(b"PK" + b"x" * (TEST_LIMIT - 1))

    assert status == 413
    assert "128 bytes" in response["detail"]
    assert list(tmp_path.iterdir()) == []


def test_content_length_over_request_limit_is_rejected_before_processing(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))
    reads = []
    original_read = StarletteUploadFile.read

    async def track_read(upload, size=-1):
        reads.append(size)
        return await original_read(upload, size)

    monkeypatch.setattr(StarletteUploadFile, "read", track_read)
    status, response = _call_asgi_request(
        b"",
        content_length=TEST_LIMIT + MULTIPART_OVERHEAD_LIMIT + 1,
    )
    assert status == 413
    assert "128 bytes" in response["detail"]
    assert reads == []
    assert list(tmp_path.iterdir()) == []


def test_chunked_request_over_request_limit_is_rejected_during_stream(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))

    status, response = _call_asgi_request(
        b"x" * (TEST_LIMIT + MULTIPART_OVERHEAD_LIMIT + 1),
        include_content_length=False,
    )

    assert status == 413
    assert "128 bytes" in response["detail"]
    assert list(tmp_path.iterdir()) == []


def test_processing_error_removes_temporary_upload(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(
        service,
        "load_dispatch_excel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid workbook")),
    )

    status, _response = _post_file(b"PK" + b"x" * 20)

    assert status == 400
    assert list(tmp_path.iterdir()) == []


def test_upload_is_consumed_in_bounded_chunks(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))
    sizes = []
    original_read = StarletteUploadFile.read

    async def track_read(upload, size=-1):
        sizes.append(size)
        return await original_read(upload, size)

    monkeypatch.setattr(StarletteUploadFile, "read", track_read)

    status, _response = _post_file(b"PK" + b"x" * (TEST_LIMIT - 2))

    assert status == 200
    assert sizes
    assert all(0 < size <= 64 * 1024 for size in sizes)
    assert list(tmp_path.iterdir()) == []


def test_upload_requires_supported_extension_and_xlsx_signature(monkeypatch, tmp_path):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))

    unsupported_status, _unsupported_response = _post_file(b"PK" + b"x" * 20, "dispatch.csv")
    invalid_signature_status, _invalid_signature_response = _post_file(b"not a zip" + b"x" * 20)

    assert unsupported_status == 415
    assert invalid_signature_status == 400
    assert list(tmp_path.iterdir()) == []


def test_upload_limit_setting_is_configurable(monkeypatch):
    from src.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "2048")

    assert get_settings().max_upload_size_bytes == 2048


@pytest.mark.parametrize(
    ("filename", "signature"),
    [
        ("dispatch.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        ("dispatch.ods", b"PK"),
    ],
)
def test_other_previously_supported_workbook_types_remain_accepted(
    monkeypatch,
    tmp_path,
    filename,
    signature,
):
    _setup_grouping(monkeypatch)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))

    status, _response = _post_file(signature + b"x" * (TEST_LIMIT - len(signature)), filename)

    assert status == 200
    assert list(tmp_path.iterdir()) == []
