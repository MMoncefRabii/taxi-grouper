import pandas as pd
from openpyxl import load_workbook

from src.adapters.exporter import export_excel, export_like_historique


def test_exporter_creates_summary(tmp_path):
    df = pd.DataFrame(
        {
            "Nom": ["A", "B"],
            "Adresse": ["Ariana", "Ariana"],
            "Zone": ["H", "H"],
            "Zone Name": ["Ariana", "Ariana"],
            "Confidence": [1.0, 1.0],
            "Matched Alias": ["Ariana", "Ariana"],
            "Normalized Address": ["ariana", "ariana"],
            "Groupe Taxi": [1, 1],
        }
    )
    output = export_excel(df, tmp_path / "out.xlsx")
    wb = load_workbook(output)
    assert "Grouped Agents" in wb.sheetnames
    assert "Summary" in wb.sheetnames


def test_historique_export_uses_numero_prix_header(tmp_path):
    df = pd.DataFrame(
        {
            "Date": ["2026-05-29"],
            "Matricule": [1],
            "Nom - Prénom": ["Agent A"],
            "Opération": ["OP"],
            "Site": ["Site 1"],
            "Numero": ["555"],
            "Adresse": ["Oued Lil Manouba"],
            "Heure d'arrivée": ["07:00"],
            "PRIX": [12],
            "Zone": ["G"],
            "DetectedDestination": ["Oued Lil"],
            "GroupReason": ["Same destination"],
            "Groupe Taxi": [1],
        }
    )
    output = export_like_historique(df, str(tmp_path / "dispatch.xlsx"))
    wb = load_workbook(output)
    ws = wb.active
    headers = [ws.cell(1, col).value for col in range(1, 12)]
    assert headers == ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Numéro", "Adresse", "Heure d'arrivée", "Taxi", "PRIX", "Statut"]
    assert ws.cell(2, 6).value == "555"
    assert ws.cell(2, 10).value == 12


def test_excel_export_shows_unassigned_status_without_taxi(tmp_path):
    df = pd.DataFrame(
        {
            "Date": [None, "2026-05-29"],
            "Nom": ["Missing date", "Valid agent"],
            "Adresse": ["Ariana", "Ariana"],
            "Zone": ["H", "H"],
            "Groupe Taxi": ["", 1],
            "UnassignedReason": ["MISSING_DATE", ""],
            "AssignmentStatus": ["A CORRIGER: date manquante", ""],
        }
    )

    output = export_excel(df, tmp_path / "unassigned.xlsx")
    ws = load_workbook(output)["Grouped Agents"]
    headers = [cell.value for cell in ws[1]]
    taxi_col = headers.index("Groupe Taxi") + 1
    status_col = headers.index("AssignmentStatus") + 1

    status_rows = [
        row
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, status_col).value == "A CORRIGER: date manquante"
    ]
    assert len(status_rows) == 1
    assert ws.cell(status_rows[0], taxi_col).value in ("", None)
    assert any(ws.cell(row, taxi_col).value == 1 for row in range(2, ws.max_row + 1))
    summary = load_workbook(output)["Summary"]
    assert summary["B2"].value == 1


def test_historique_export_shows_unassigned_status_without_taxi(tmp_path):
    df = pd.DataFrame(
        {
            "Date": [None, "2026-05-29"],
            "Matricule": [1, 2],
            "Nom - Prénom": ["Missing date", "Valid agent"],
            "Opération": ["OP", "OP"],
            "Site": ["Site 1", "Site 1"],
            "Adresse": ["Ariana", "Ariana"],
            "Heure d'arrivée": ["07:00", "07:00"],
            "Groupe Taxi": ["", 1],
            "SourceDispatchID": ["dispatch-A", "dispatch-A"],
            "UnassignedReason": ["MISSING_DATE", ""],
            "AssignmentStatus": ["A CORRIGER: date manquante", ""],
            "Zone": ["H", "H"],
        }
    )

    output = export_like_historique(df, str(tmp_path / "unassigned_historique.xlsx"))
    ws = load_workbook(output).active
    status_col = [cell.value for cell in ws[1]].index("Statut") + 1

    status_rows = [
        row
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, status_col).value == "A CORRIGER: date manquante"
    ]
    assert len(status_rows) == 1
    assert ws.cell(status_rows[0], 9).value in ("", None)
