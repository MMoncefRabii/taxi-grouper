import asyncio

import pandas as pd

from src.api import service
from src.data.sheets_repository import GroupedSheetOutputs


def _grouped_output():
    return pd.DataFrame({"Groupe Taxi": [1], "Zone": ["Ariana"], "InternalOnly": ["secret"]})


def _validation_result():
    return {
        "valid": True,
        "errors": [],
        "warnings": [],
        "taxi_reports": [],
    }


def test_group_sheet_response_preserves_aliases_and_keys_state_by_client_output(monkeypatch):
    written = {}
    stored = {}
    monkeypatch.setattr(service, "_ensure_native_sheet", lambda sheet_id: (sheet_id, None, False))
    monkeypatch.setattr(service, "read_sheet_to_dataframe", lambda _sheet_id: pd.DataFrame({"Adresse": ["Ariana"]}))
    monkeypatch.setattr(service, "detect_columns", lambda _df: object())
    monkeypatch.setattr(service, "filter_dataframe", lambda df, *_args, **_kwargs: df)
    monkeypatch.setattr(service, "group_agents", lambda *_args, **_kwargs: (_grouped_output(), []))
    monkeypatch.setattr(service, "validate_dispatch", lambda *_args, **_kwargs: _validation_result())

    def write(source_sheet_id, _grouped, **kwargs):
        written.update(source_sheet_id=source_sheet_id, **kwargs)
        return GroupedSheetOutputs(
            client_sheet_id="client-id",
            client_sheet_url="client-url",
            internal_sheet_id="internal-id",
            internal_sheet_url="internal-url",
        )

    monkeypatch.setattr(service, "write_grouped_df_to_sheet", write)
    monkeypatch.setattr(
        service,
        "store_pre_correction_state",
        lambda sheet_id, _df: stored.setdefault("sheet_id", sheet_id),
    )

    response = asyncio.run(
        service.group_sheet_endpoint(
            sheet_id="source-id",
            time_filter=None,
            type_course_filter=None,
            operation_filter=None,
            use_ml=False,
            client_sheet_id=None,
            internal_sheet_id=None,
            overwrite_output=False,
        )
    )

    assert response["sheet_url"] == "client-url"
    assert response["sheet_id"] == "client-id"
    assert response["client_sheet_url"] == "client-url"
    assert response["internal_sheet_url"] == "internal-url"
    assert response["client_sheet_id"] == "client-id"
    assert response["internal_sheet_id"] == "internal-id"
    assert written["source_sheet_id"] == "source-id"
    assert stored["sheet_id"] == "client-id"


def test_group_sheet_never_passes_source_or_converted_copy_as_output(monkeypatch):
    received = {}
    monkeypatch.setattr(
        service,
        "_ensure_native_sheet",
        lambda _sheet_id: ("converted-id", "converted-url", True),
    )
    monkeypatch.setattr(service, "read_sheet_to_dataframe", lambda _sheet_id: pd.DataFrame({"Adresse": ["Ariana"]}))
    monkeypatch.setattr(service, "detect_columns", lambda _df: object())
    monkeypatch.setattr(service, "filter_dataframe", lambda df, *_args, **_kwargs: df)
    monkeypatch.setattr(service, "group_agents", lambda *_args, **_kwargs: (_grouped_output(), []))
    monkeypatch.setattr(service, "validate_dispatch", lambda *_args, **_kwargs: _validation_result())

    def write(source_sheet_id, _grouped, **kwargs):
        received.update(source_sheet_id=source_sheet_id, **kwargs)
        return GroupedSheetOutputs("client-id", "client-url", "internal-id", "internal-url")

    monkeypatch.setattr(service, "write_grouped_df_to_sheet", write)
    monkeypatch.setattr(service, "store_pre_correction_state", lambda *_args: None)

    asyncio.run(
        service.group_sheet_endpoint(
            sheet_id="source-id",
            time_filter=None,
            type_course_filter=None,
            operation_filter=None,
            use_ml=False,
            client_sheet_id=None,
            internal_sheet_id=None,
            overwrite_output=False,
        )
    )

    assert received["source_sheet_id"] == "converted-id"
    assert received["source_sheet_ids"] == {"source-id", "converted-id"}


def test_group_sheet_requires_both_output_ids_and_explicit_overwrite(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_ensure_native_sheet", lambda sheet_id: (sheet_id, None, False))
    monkeypatch.setattr(service, "read_sheet_to_dataframe", lambda _sheet_id: pd.DataFrame({"Adresse": ["Ariana"]}))
    monkeypatch.setattr(service, "detect_columns", lambda _df: object())
    monkeypatch.setattr(service, "filter_dataframe", lambda df, *_args, **_kwargs: df)
    monkeypatch.setattr(service, "group_agents", lambda *_args, **_kwargs: (_grouped_output(), []))
    monkeypatch.setattr(service, "validate_dispatch", lambda *_args, **_kwargs: _validation_result())
    monkeypatch.setattr(service, "write_grouped_df_to_sheet", lambda *_args, **_kwargs: called.append(True))

    try:
        asyncio.run(
            service.group_sheet_endpoint(
                sheet_id="source-id",
                time_filter=None,
                type_course_filter=None,
                operation_filter=None,
                use_ml=False,
                client_sheet_id="existing-client-id",
                internal_sheet_id="existing-internal-id",
                overwrite_output=False,
            )
        )
    except service.HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Existing output IDs without overwrite must be rejected")

    assert called == []


def test_save_drive_response_keeps_legacy_fields_and_adds_both_outputs(monkeypatch):
    monkeypatch.setattr(
        service,
        "create_google_sheet_from_dataframe",
        lambda *_args, **_kwargs: GroupedSheetOutputs(
            "client-id",
            "client-url",
            "internal-id",
            "internal-url",
        ),
    )

    response = asyncio.run(
        service.save_drive_endpoint(
            service.SaveToDriveRequest(grouped_data=[{"Groupe Taxi": 1}], sheet_name="Results")
        )
    )

    assert response == {
        "sheet_url": "client-url",
        "sheet_id": "client-id",
        "client_sheet_url": "client-url",
        "internal_sheet_url": "internal-url",
        "client_sheet_id": "client-id",
        "internal_sheet_id": "internal-id",
    }


def test_validate_corrections_uses_client_output_id_for_cached_state(monkeypatch):
    observed = {}
    client_df = pd.DataFrame({"Groupe Taxi": [1]})
    monkeypatch.setattr(service, "_load_debug_post_correction_state", lambda _sheet_id: None)
    monkeypatch.setattr(
        service,
        "_ensure_native_sheet",
        lambda sheet_id: (sheet_id, None, False),
    )
    monkeypatch.setattr(service, "read_sheet_to_dataframe", lambda _sheet_id: client_df)
    monkeypatch.setattr(service, "validate_dispatch", lambda *_args, **_kwargs: _validation_result())

    def extract(sheet_id, _df, **_kwargs):
        observed["sheet_id"] = sheet_id
        return {"success": True, "corrections": [], "stats": {}}

    monkeypatch.setattr(service, "extract_training_examples_from_corrections", extract)
    monkeypatch.setattr(service, "_load_debug_post_correction_state", lambda _sheet_id: None)

    result = asyncio.run(
        service.validate_sheet_endpoint(
            service.SheetInfoRequest(sheet_id="client-output-id"),
            service.BackgroundTasks(),
        )
    )

    assert observed["sheet_id"] == "client-output-id"
    assert result["validation"]["valid"] is True
