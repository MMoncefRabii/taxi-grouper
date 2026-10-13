import pandas as pd

from src.core.grouper import group_agents
from src.core.preprocessing import add_dispatch_block_metadata, load_dispatch_excel, detect_columns, filter_dataframe


def test_load_dispatch_excel_removes_repeated_headers(tmp_path):
    path = tmp_path / "dispatch.xlsx"
    rows = [
        ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Adresse", "Heure d'arrivée", "Taxi"],
        ["2026-05-28", 1, "Agent A", "OP", "Site 1", "Ariana", "07:00", None],
        ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Adresse", "Heure d'arrivée", "Taxi"],
        ["2026-05-28", 2, "Agent B", "OP", "Site 1", "Marsa", "17:30", None],
    ]
    pd.DataFrame(rows).to_excel(path, index=False, header=False)

    loaded = load_dispatch_excel(path)

    assert len(loaded) == 2
    assert loaded["Nom - Prénom"].tolist() == ["Agent A", "Agent B"]
    assert "BlockID" in loaded.columns
    assert loaded["SourceDispatchID"].tolist() == [
        "dispatch.xlsx | Sheet1 | 1",
        "dispatch.xlsx | Sheet1 | 2",
    ]
    assert loaded["block_id_origin"].eq("synthesized").all()


def test_load_dispatch_excel_supports_numero_prix_header(tmp_path):
    path = tmp_path / "dispatch_numero.xlsx"
    rows = [
        ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Numéro", "Adresse", "Heure d'arrivée", "Taxi", "PRIX"],
        ["2026-05-29", 1, "Agent A", "OP", "Site 1", "555", "Oued Lil Manouba", "07:00", None, 12],
    ]
    pd.DataFrame(rows).to_excel(path, index=False, header=False)

    loaded = load_dispatch_excel(path)

    assert len(loaded) == 1
    assert loaded["Numero"].tolist() == ["555"]
    assert loaded["PRIX"].tolist() == [12]


def test_provided_dispatch_id_takes_precedence_over_synthesized_id(tmp_path):
    path = tmp_path / "dispatch.xlsx"
    rows = [
        ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Adresse", "Heure d'arrivée", "Taxi", "Dispatch ID"],
        ["2026-05-28", 1, "Agent A", "OP", "Site 1", "Ariana", "07:00", None, "source-42"],
    ]
    pd.DataFrame(rows).to_excel(path, index=False, header=False)

    loaded = load_dispatch_excel(path)

    assert loaded["SourceDispatchID"].tolist() == ["source-42"]
    assert loaded["block_id_origin"].tolist() == ["provided"]


def test_same_block_ordinal_in_different_files_does_not_merge(tmp_path):
    rows = [
        ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Adresse", "Heure d'arrivée", "Taxi"],
        ["2026-05-28", 1, "Agent A", "OP", "Site 1", "Ariana", "07:00", None],
        ["2026-05-28", 2, "Agent B", "OP", "Site 1", "Ariana", "07:00", None],
    ]
    paths = [tmp_path / "first.xlsx", tmp_path / "second.xlsx"]
    for path in paths:
        pd.DataFrame(rows).to_excel(path, index=False, header=False)
    loaded = pd.concat([load_dispatch_excel(path) for path in paths], ignore_index=True)

    assert loaded["SourceDispatchID"].nunique() == 2
    grouped, _warnings = group_agents(loaded, detect_columns(loaded), use_ml=False)
    taxis_by_source = grouped.groupby("SourceDispatchID")["Groupe Taxi"].apply(set)
    assert taxis_by_source["first.xlsx | Sheet1 | 1"].isdisjoint(taxis_by_source["second.xlsx | Sheet1 | 1"])


def test_same_block_ordinal_in_different_sheets_does_not_merge(tmp_path):
    path = tmp_path / "dispatch.xlsx"
    rows = [
        ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Adresse", "Heure d'arrivée", "Taxi"],
        ["2026-05-28", 1, "Agent A", "OP", "Site 1", "Ariana", "07:00", None],
        ["2026-05-28", 2, "Agent B", "OP", "Site 1", "Ariana", "07:00", None],
    ]
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="First", index=False, header=False)
        pd.DataFrame(rows).to_excel(writer, sheet_name="Second", index=False, header=False)

    loaded = load_dispatch_excel(path)

    assert loaded["SourceDispatchID"].nunique() == 2
    grouped, _warnings = group_agents(loaded, detect_columns(loaded), use_ml=False)
    taxis_by_source = grouped.groupby("SourceDispatchID")["Groupe Taxi"].apply(set)
    assert taxis_by_source["dispatch.xlsx | First | 1"].isdisjoint(taxis_by_source["dispatch.xlsx | Second | 1"])


def test_legacy_workbook_without_repeated_headers_uses_block_one(tmp_path):
    path = tmp_path / "legacy.xlsx"
    pd.DataFrame(
        {
            "Date": ["2026-05-28", "2026-05-28"],
            "Nom - Prénom": ["Agent A", "Agent B"],
            "Adresse": ["Ariana", "Ariana"],
            "Heure d'arrivée": ["07:00", "07:00"],
        }
    ).to_excel(path, index=False)

    loaded = load_dispatch_excel(path)

    assert loaded["SourceDispatchID"].eq("legacy.xlsx | Sheet1 | 1").all()
    assert loaded["block_id_origin"].eq("synthesized").all()
    grouped, _warnings = group_agents(loaded, detect_columns(loaded), use_ml=False)
    assert grouped["Groupe Taxi"].nunique() == 1


def test_google_sheet_metadata_uses_the_tab_gid():
    df = add_dispatch_block_metadata(
        pd.DataFrame({"Date": ["2026-05-28", "2026-05-29"]}),
        source_id="spreadsheet-123",
        sheet_name="987654",
        block_ordinals=[1, 2],
    )

    assert df["SourceDispatchID"].tolist() == [
        "spreadsheet-123 | 987654 | 1",
        "spreadsheet-123 | 987654 | 2",
    ]
    assert df["block_id_origin"].eq("synthesized").all()


def test_filter_dataframe_accepts_regex_special_characters():
    df = pd.DataFrame(
        {
            "Adresse": ["Ariana", "Oued Lil", "Ghazela"],
            "Heure d'arrivée": ["07:00", "08:00", "09:00"],
            "Opération": ["Ramassage", "Retour", "Ramassage"],
        }
    )
    columns = detect_columns(df)
    filtered = filter_dataframe(df, columns, time_value="08:00", type_course="Ramassage", operation="Oued Lil")

    assert len(filtered) == 0

    regex_df = pd.DataFrame(
        {"Adresse": ["Ariana", "Oued Lil"], "Type de course": [".*", "Ramassage"]}
    )
    regex_columns = detect_columns(regex_df)
    safe_filtered = filter_dataframe(regex_df, regex_columns, type_course=".*")

    assert len(safe_filtered) == 1
    assert safe_filtered.iloc[0]["Type de course"] == ".*"
    assert safe_filtered.iloc[0]["Adresse"] == "Ariana"
