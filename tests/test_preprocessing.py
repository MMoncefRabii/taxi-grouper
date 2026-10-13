import pandas as pd

from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe


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
