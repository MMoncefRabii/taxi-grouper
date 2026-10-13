import pandas as pd

from src.data import sheets_repository


def test_client_sheet_exposes_unassigned_status_and_internal_reason(monkeypatch):
    writes = {}
    monkeypatch.setattr(
        sheets_repository,
        "_get_file_metadata",
        lambda _sheet_id: {"name": "dispatch"},
    )
    monkeypatch.setattr(
        sheets_repository,
        "_ensure_destination_spreadsheet",
        lambda *_args: ("sheet-id", "sheet-url", False),
    )
    monkeypatch.setattr(sheets_repository, "_ensure_sheet", lambda _sheet_id, title, _new: 1 if title == sheets_repository.CLIENT_SHEET_NAME else 2)
    monkeypatch.setattr(sheets_repository, "_set_sheet_hidden", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sheets_repository, "_apply_client_sheet_formatting", lambda *_args: None)
    monkeypatch.setattr(
        sheets_repository,
        "_write_values_to_sheet",
        lambda _sheet_id, title, values: writes.__setitem__(title, values),
    )

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

    sheets_repository.write_grouped_df_to_sheet("source-id", df)

    client = writes[sheets_repository.CLIENT_SHEET_NAME]
    internal = writes[sheets_repository.INTERNAL_SHEET_NAME]
    status_index = client[0].index("Statut")
    taxi_index = client[0].index("Groupe Taxi")
    reason_index = internal[0].index("UnassignedReason")
    assert client[1][taxi_index] == ""
    assert client[1][status_index] == "A CORRIGER: date manquante"
    assert internal[1][reason_index] == "MISSING_DATE"
