from unittest.mock import Mock

import pandas as pd

from src.data import sheets_repository


def test_client_sheet_exposes_unassigned_status_and_internal_reason(monkeypatch):
    writes = {}
    created = iter(["client-output-id", "internal-output-id"])
    monkeypatch.setattr(sheets_repository, "_get_file_metadata", lambda _sheet_id: {"name": "dispatch"})
    monkeypatch.setattr(
        sheets_repository,
        "_create_google_sheet",
        lambda _title, _folder_id: (next(created), "output-url"),
    )
    monkeypatch.setattr(
        sheets_repository,
        "_ensure_output_tab",
        lambda _sheet_id, title, _is_new: 1 if title == sheets_repository.CLIENT_SHEET_NAME else 2,
    )
    monkeypatch.setattr(sheets_repository, "_apply_client_sheet_formatting", lambda *_args: None)
    monkeypatch.setattr(
        sheets_repository,
        "_write_values_to_sheet",
        lambda sheet_id, title, values: writes.__setitem__((sheet_id, title), values),
    )
    monkeypatch.setattr(sheets_repository, "OUTPUT_FOLDER_ID", "configured-folder-id")

    df = pd.DataFrame(
        {
            "Date": [None],
            "Matricule": [1],
            "Nom - Prénom": ["Missing date"],
            "Adresse": ["Ariana"],
            "Heure d'arrivée": ["07:00"],
            "Groupe Taxi": [""],
            "UnassignedReason": ["MISSING_DATE"],
            "AssignmentStatus": ["A CORRIGER: date manquante"],
        }
    )

    outputs = sheets_repository.write_grouped_df_to_sheet(
        "converted-source-id",
        df,
        source_sheet_ids={"source-id", "converted-source-id"},
    )

    client = writes[("client-output-id", sheets_repository.CLIENT_SHEET_NAME)]
    internal = writes[("internal-output-id", sheets_repository.INTERNAL_SHEET_NAME)]
    status_index = client[0].index("Statut")
    taxi_index = client[0].index("Groupe Taxi")
    reason_index = internal[0].index("UnassignedReason")
    assert client[1][taxi_index] == ""
    assert client[1][status_index] == "A CORRIGER: date manquante"
    assert internal[1][reason_index] == "MISSING_DATE"
    assert outputs.client_sheet_id == "client-output-id"
    assert outputs.internal_sheet_id == "internal-output-id"
    assert client[0] == sheets_repository.CLIENT_SHEET_COLUMNS
    assert set(sheet_id for sheet_id, _ in writes).isdisjoint({"source-id", "converted-source-id"})


def test_output_sheets_are_separate_with_their_own_tabs_and_columns(monkeypatch):
    created = iter(["client-output-id", "internal-output-id"])
    created_titles = []
    writes = {}
    tab_setup = []
    formatted = []
    monkeypatch.setattr(sheets_repository, "_get_file_metadata", lambda _sheet_id: {"name": "dispatch.xlsx"})

    def create(title, folder_id):
        created_titles.append((title, folder_id))
        return next(created), f"url:{title}:{folder_id}"

    monkeypatch.setattr(
        sheets_repository,
        "_create_google_sheet",
        create,
    )
    monkeypatch.setattr(
        sheets_repository,
        "_ensure_output_tab",
        lambda sheet_id, title, is_new: tab_setup.append((sheet_id, title, is_new)) or 1,
    )
    monkeypatch.setattr(
        sheets_repository,
        "_write_values_to_sheet",
        lambda sheet_id, title, values: writes.__setitem__((sheet_id, title), values),
    )
    monkeypatch.setattr(
        sheets_repository,
        "_apply_client_sheet_formatting",
        lambda sheet_id, *_args: formatted.append(sheet_id),
    )
    monkeypatch.setattr(sheets_repository, "OUTPUT_FOLDER_ID", "configured-folder-id")

    df = pd.DataFrame({"Groupe Taxi": [1], "Zone": ["Ariana"], "InternalOnly": ["secret"]})
    outputs = sheets_repository.write_grouped_df_to_sheet("source-id", df)

    assert outputs.client_sheet_id == "client-output-id"
    assert outputs.internal_sheet_id == "internal-output-id"
    assert outputs.client_sheet_id != outputs.internal_sheet_id
    assert set(writes) == {
        ("client-output-id", sheets_repository.CLIENT_SHEET_NAME),
        ("internal-output-id", sheets_repository.INTERNAL_SHEET_NAME),
    }
    assert writes[("client-output-id", sheets_repository.CLIENT_SHEET_NAME)][0] == sheets_repository.CLIENT_SHEET_COLUMNS
    assert "InternalOnly" not in writes[("client-output-id", sheets_repository.CLIENT_SHEET_NAME)][0]
    assert writes[("internal-output-id", sheets_repository.INTERNAL_SHEET_NAME)][0] == list(df.columns)
    assert [title for _, title, _ in tab_setup] == [
        sheets_repository.CLIENT_SHEET_NAME,
        sheets_repository.INTERNAL_SHEET_NAME,
    ]
    assert [sheet_id for sheet_id, _, _ in tab_setup] == ["client-output-id", "internal-output-id"]
    assert [folder_id for _, folder_id in created_titles] == ["configured-folder-id"] * 2
    assert "Client Output" in created_titles[0][0]
    assert "Internal Output" in created_titles[1][0]
    assert formatted == ["client-output-id"]


def test_explicit_output_ids_require_overwrite_flag(monkeypatch):
    create_calls = []
    monkeypatch.setattr(sheets_repository, "_create_google_sheet", lambda *_args: create_calls.append(True))
    df = pd.DataFrame({"Groupe Taxi": [1]})

    try:
        sheets_repository.write_grouped_df_to_sheet(
            "source-id",
            df,
            client_sheet_id="existing-client-id",
            internal_sheet_id="existing-internal-id",
        )
    except ValueError as exc:
        assert "overwrite" in str(exc).lower()
    else:
        raise AssertionError("Explicit output IDs without overwrite=True must be rejected")

    assert create_calls == []


def test_output_ids_and_overwrite_flag_are_both_required(monkeypatch):
    df = pd.DataFrame({"Groupe Taxi": [1]})

    try:
        sheets_repository.write_grouped_df_to_sheet("source-id", df, overwrite=True)
    except ValueError as exc:
        assert "output spreadsheet IDs" in str(exc)
    else:
        raise AssertionError("overwrite=True without output IDs must be rejected")


def test_explicit_overwrite_targets_only_the_supplied_output_spreadsheets(monkeypatch):
    writes = []
    monkeypatch.setattr(sheets_repository, "_get_file_metadata", lambda _sheet_id: {"name": "dispatch"})
    monkeypatch.setattr(
        sheets_repository,
        "_ensure_output_tab",
        lambda sheet_id, title, _new: 1,
    )
    monkeypatch.setattr(
        sheets_repository,
        "_write_values_to_sheet",
        lambda sheet_id, title, _values: writes.append((sheet_id, title)),
    )
    monkeypatch.setattr(sheets_repository, "_apply_client_sheet_formatting", lambda *_args: None)
    monkeypatch.setattr(
        sheets_repository,
        "_create_google_sheet",
        lambda *_args: (_ for _ in ()).throw(AssertionError("overwrite must not create new outputs")),
    )

    outputs = sheets_repository.write_grouped_df_to_sheet(
        "source-id",
        pd.DataFrame({"Groupe Taxi": [1]}),
        client_sheet_id="existing-client-id",
        internal_sheet_id="existing-internal-id",
        overwrite=True,
    )

    assert outputs.client_sheet_id == "existing-client-id"
    assert outputs.internal_sheet_id == "existing-internal-id"
    assert writes == [
        ("existing-client-id", sheets_repository.CLIENT_SHEET_NAME),
        ("existing-internal-id", sheets_repository.INTERNAL_SHEET_NAME),
    ]


def test_new_spreadsheet_is_created_in_configured_folder(monkeypatch):
    drive = Mock()
    drive.files.return_value.create.return_value.execute.return_value = {"id": "created-id"}
    monkeypatch.setattr(sheets_repository, "OUTPUT_FOLDER_ID", "configured-folder-id")
    monkeypatch.setattr(sheets_repository, "build_drive_service", lambda: drive)

    sheet_id, _ = sheets_repository._create_google_sheet("Client Output")

    assert sheet_id == "created-id"
    drive.files.return_value.create.assert_called_once_with(
        body={
            "name": "Client Output",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": ["configured-folder-id"],
        },
        fields="id",
        supportsAllDrives=True,
    )


def test_new_spreadsheet_requires_configured_output_folder(monkeypatch):
    monkeypatch.setattr(sheets_repository, "OUTPUT_FOLDER_ID", None)

    try:
        sheets_repository._create_google_sheet("Client Output")
    except RuntimeError as exc:
        assert "GOOGLE_OUTPUT_FOLDER_ID" in str(exc)
    else:
        raise AssertionError("Creating an output without a configured folder must fail")
