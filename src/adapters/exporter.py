"""Professional Excel exporter for grouped taxi plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..config import TAXI_COLUMN, UNKNOWN_ZONE
from ..core.grouper import validate_dispatch
from ..schemas import HISTORIQUE_COLUMNS, UNASSIGNED_STATUS_BY_REASON

NAVY = "102A43"
GOLD = "F0B429"
RED = "C00000"
GROUP_A = "FFFFFF"
GROUP_B = "E8F4F8"
UNKNOWN_FILL = "FCE8E6"
BORDER = "B7C4CF"
HIST_HEADER_FILL = "000000"
HIST_HEADER_ORANGE = "FF7E00"
HIST_HEADER_YELLOW = "FFFF00"
HIST_TAXI_RED = "FF0000"
HIST_GROUP_COLORS = ["FF9900", "FFFFFF"]
DISPATCH_EXPORT_COLUMNS = ["Date", "Matricule", "Nom - Prénom", "Opération", "Site", "Numéro", "Adresse", "Heure d'arrivée", "Taxi", "PRIX", "Statut"]


def export_excel(df: pd.DataFrame, output_path: str | Path, taxi_column: str = TAXI_COLUMN) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    work = df.copy()
    if taxi_column not in work.columns:
        raise ValueError(f"Missing taxi column: {taxi_column}")
    work = validate_dispatch(work, taxi_column=taxi_column)["dataframe"]
    work["_export_taxi_sort_key"] = pd.to_numeric(work[taxi_column], errors="coerce")
    work = (
        work.sort_values("_export_taxi_sort_key", kind="stable", na_position="last")
        .drop(columns=["_export_taxi_sort_key"])
        .reset_index(drop=True)
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Grouped Agents"
    _write_table(ws, work, taxi_column)
    _write_summary(wb, work, taxi_column)
    wb.save(output_path)
    return output_path


def _write_table(ws, df: pd.DataFrame, taxi_column: str) -> None:
    columns = list(df.columns)
    taxi_col_idx = columns.index(taxi_column) + 1
    thin = Side(style="thin", color=BORDER)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, col in enumerate(columns, start=1):
        cell = ws.cell(1, col_idx, col)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(color=GOLD, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    taxi_blocks: list[tuple[object, int, int]] = []
    current_taxi = None
    start_row = 2
    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        taxi = row[taxi_column]
        is_assigned = pd.notna(taxi) and str(taxi).strip() != ""
        if not is_assigned and current_taxi is not None:
            taxi_blocks.append((current_taxi, start_row, row_idx - 1))
            current_taxi = None
        elif is_assigned and taxi != current_taxi:
            if current_taxi is not None:
                taxi_blocks.append((current_taxi, start_row, row_idx - 1))
            current_taxi = taxi
            start_row = row_idx
        fill_color = (GROUP_A if int(taxi) % 2 == 0 else GROUP_B) if is_assigned else UNKNOWN_FILL
        if str(row.get("Zone", "")) == UNKNOWN_ZONE:
            fill_color = UNKNOWN_FILL
        for col_idx, col in enumerate(columns, start=1):
            value = "" if col == taxi_column else row[col]
            cell = ws.cell(row_idx, col_idx, value)
            cell.fill = PatternFill("solid", fgColor=fill_color)
            cell.border = border
            cell.alignment = Alignment(horizontal="center" if col in {taxi_column, "Zone", "Confidence"} else "left", vertical="center")
    if current_taxi is not None:
        taxi_blocks.append((current_taxi, start_row, len(df) + 1))

    for taxi, first_row, last_row in taxi_blocks:
        if last_row > first_row:
            ws.merge_cells(start_row=first_row, start_column=taxi_col_idx, end_row=last_row, end_column=taxi_col_idx)
        cell = ws.cell(first_row, taxi_col_idx, taxi)
        cell.fill = PatternFill("solid", fgColor=RED)
        cell.font = Font(color="FFFFFF", bold=True, size=13)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(left=Side(style="medium", color=RED), right=Side(style="medium", color=RED), top=Side(style="medium", color=RED), bottom=Side(style="medium", color=RED))

    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        max_len = max((len(str(cell.value)) for cell in col_cells if cell.value is not None), default=8)
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 45)
    ws.row_dimensions[1].height = 24


def _write_summary(wb: Workbook, df: pd.DataFrame, taxi_column: str) -> None:
    ws = wb.create_sheet("Summary")
    total_agents = len(df)
    assigned = df[taxi_column].notna() & df[taxi_column].astype(str).str.strip().ne("")
    total_taxis = int(df.loc[assigned, taxi_column].nunique()) if assigned.any() else 0
    assigned_agents = int(assigned.sum())
    unknown_count = int((df.get("Zone", pd.Series(dtype=str)) == UNKNOWN_ZONE).sum())
    zones_used = sorted(str(z) for z in df.get("Zone", pd.Series(dtype=str)).dropna().unique())
    summary = [
        ("Total agents", total_agents),
        ("Total taxis", total_taxis),
        ("Average agents per taxi", round(assigned_agents / total_taxis, 2) if total_taxis else 0),
        ("Unknown addresses", unknown_count),
        ("Number of zones used", len(zones_used)),
        ("Zones used", ", ".join(zones_used)),
    ]
    for row_idx, (label, value) in enumerate(summary, start=1):
        ws.cell(row_idx, 1, label).font = Font(bold=True)
        ws.cell(row_idx, 2, value)

    start = len(summary) + 3
    headers = ["Taxi", "Agents", "Zones"]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(start, col_idx, header)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(color=GOLD, bold=True)
    assigned_rows = df.loc[assigned]
    for row_idx, (taxi, group) in enumerate(assigned_rows.groupby(taxi_column), start=start + 1):
        ws.cell(row_idx, 1, taxi)
        ws.cell(row_idx, 2, len(group))
        ws.cell(row_idx, 3, ", ".join(sorted(str(z) for z in group["Zone"].dropna().unique())))

    for col_idx in range(1, 4):
        ws.column_dimensions[get_column_letter(col_idx)].width = 26


def export_like_historique(grouped_df, output_path: str, sheet_name: str = "Dispatch", validation_report_path: str | None = None) -> str:
    """
    Export grouped taxi dispatch results using the same structure and colors
    as the historical Historique.xlsx file.

    Visible columns:
    Date, Matricule, Nom - Prénom, Opération, Site, Adresse, Heure d'arrivée, Taxi, Statut

    Repeated headers must be inserted for each dispatch time block.
    Taxi cells must be grouped/merged vertically.
    Group colors must alternate.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    df = _drop_empty_export_rows(grouped_df.copy())
    if TAXI_COLUMN not in df.columns and "Taxi" not in df.columns:
        raise ValueError("Grouped dataframe must contain Groupe Taxi or Taxi column.")

    taxi_col = TAXI_COLUMN if TAXI_COLUMN in df.columns else "Taxi"
    from ..core.grouper import validate_dispatch

    validation = validate_dispatch(df, taxi_column=taxi_col)
    if validation_report_path:
        export_validation_report(validation, validation_report_path)
    if validation["errors"]:
        raise ValueError("Dispatch validation failed. Final Excel was not exported:\n" + "\n".join(validation["errors"]))
    df = validation["dataframe"]

    time_col = _find_col(df, ["Heure d'arrivée", "Heure", "Heure arrivée", "Heure d arrivee"])
    date_col = _find_col(df, ["Date"])
    df[taxi_col] = df[taxi_col].fillna("")
    df["_export_taxi_sort"] = pd.to_numeric(df[taxi_col], errors="coerce")
    df["_export_time"] = df[time_col].astype(str) if time_col else ""
    df["_export_date"] = df[date_col].astype(str) if date_col else ""
    df = (
        df.sort_values(["_export_time", "_export_taxi_sort", "_export_date"], kind="stable", na_position="last")
        .drop(columns=["_export_taxi_sort"])
        .reset_index(drop=True)
    )

    wb = Workbook()
    ws = wb.active
    ws.title = str(sheet_name)[:31] or "Dispatch"

    row_cursor = 1
    group_keys = ["_export_time"]
    grouped_blocks = df.groupby(group_keys, sort=False, dropna=False)

    for _, block in grouped_blocks:
        _write_historique_header(ws, row_cursor)
        row_cursor += 1
        taxi_color_index = 0
        taxi_visible_col = DISPATCH_EXPORT_COLUMNS.index("Taxi") + 1
        for taxi, taxi_group in block.groupby(taxi_col, sort=False):
            color = HIST_GROUP_COLORS[taxi_color_index % len(HIST_GROUP_COLORS)]
            first_row = row_cursor
            for _, record in taxi_group.iterrows():
                visible = _historique_visible_row(record, taxi_col, taxi)
                for col_idx, value in enumerate(visible, start=1):
                    cell = ws.cell(row_cursor, col_idx, value if col_idx != taxi_visible_col or row_cursor == first_row else "")
                    cell.fill = PatternFill("solid", fgColor=color)
                    cell.font = Font(name="Arial", size=11, color=HIST_TAXI_RED if col_idx == taxi_visible_col else "000000", bold=col_idx == taxi_visible_col)
                    cell.alignment = Alignment(horizontal="center" if col_idx in {1, 2, 6, 8, 9, 10} else "left", vertical="center", wrap_text=True)
                    cell.border = _medium_black_border()
                row_cursor += 1
            last_row = row_cursor - 1
            if last_row > first_row:
                ws.merge_cells(start_row=first_row, start_column=taxi_visible_col, end_row=last_row, end_column=taxi_visible_col)
            taxi_cell = ws.cell(first_row, taxi_visible_col)
            taxi_cell.value = taxi
            taxi_cell.font = Font(name="Arial", size=11, color=HIST_TAXI_RED, bold=True)
            taxi_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            taxi_cell.border = _medium_black_border()
            taxi_color_index += 1
        row_cursor += 1

    _format_historique_widths(ws)
    wb.save(output)
    return str(output)


def _drop_empty_export_rows(df: pd.DataFrame) -> pd.DataFrame:
    main_cols = [
        col
        for col in [
            "Date",
            "Matricule",
            "Nom - Prénom",
            "Nom - Prenom",
            "Nom - PrÃ©nom",
            "Opération",
            "Operation",
            "Site",
            "Adresse",
            "Heure d'arrivée",
            "Heure d'arrivee",
            "Heure d'arrivÃ©e",
        ]
        if col in df.columns
    ]
    if not main_cols:
        return df.copy().reset_index(drop=True)
    keep = ~df[main_cols].apply(lambda row: all(pd.isna(value) or str(value).strip() == "" for value in row), axis=1)
    return df.loc[keep].copy().reset_index(drop=True)


def export_validation_report(validation: dict[str, Any], output_path: str | Path) -> str:
    """Export one validation summary row per taxi."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = validation.get("taxi_reports", [])
    df = pd.DataFrame(
        rows,
        columns=[
            "Taxi",
            "Agents count",
            "Zones inside taxi",
            "Destinations inside taxi",
            "Times inside taxi",
            "Validation status",
            "Error message",
            "Group reason",
        ],
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Validation Report"
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, header in enumerate(df.columns, start=1):
        cell = ws.cell(1, col_idx, header)
        cell.fill = PatternFill("solid", fgColor=HIST_HEADER_FILL)
        cell.font = Font(name="Arial", size=11, bold=True, color=HIST_HEADER_YELLOW if header == "Validation status" else HIST_HEADER_ORANGE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    status_fills = {
        "VALID": "C6EFCE",
        "WARNING": "FFEB9C",
        "INVALID": "FFC7CE",
    }
    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        fill = PatternFill("solid", fgColor=status_fills.get(str(row.get("Validation status", "")), "FFFFFF"))
        for col_idx, value in enumerate(row.tolist(), start=1):
            cell = ws.cell(row_idx, col_idx, value)
            cell.fill = fill
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(horizontal="center" if col_idx in {1, 2, 6} else "left", vertical="center", wrap_text=True)
            cell.border = border

    ws.freeze_panes = "A2"
    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        max_len = max((len(str(cell.value)) for cell in col_cells if cell.value is not None), default=8)
        ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 55)
    wb.save(output)
    return str(output)


def _write_historique_header(ws, row_idx: int) -> None:
    taxi_visible_col = DISPATCH_EXPORT_COLUMNS.index("Taxi") + 1
    for col_idx, header in enumerate(DISPATCH_EXPORT_COLUMNS, start=1):
        cell = ws.cell(row_idx, col_idx, header)
        cell.fill = PatternFill("solid", fgColor=HIST_HEADER_FILL)
        cell.font = Font(
            name="Arial",
            size=11,
            bold=True,
            color=HIST_HEADER_YELLOW if col_idx == taxi_visible_col else HIST_HEADER_ORANGE,
        )
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _medium_black_border()
    ws.row_dimensions[row_idx].height = 28


def _historique_visible_row(record: pd.Series, taxi_col: str, taxi) -> list:
    reason = str(record.get("UnassignedReason", "") or "")
    status = record.get("AssignmentStatus")
    if pd.isna(status) or not str(status).strip():
        status = UNASSIGNED_STATUS_BY_REASON.get(reason, "")
    return [
        _record_value(record, ["Date"]),
        _record_value(record, ["Matricule"]),
        _record_value(record, ["Nom - Prénom", "Nom - Prenom", "Nom"]),
        _record_value(record, ["Opération", "Operation", "Client"]),
        _record_value(record, ["Site"]),
        _record_value(record, ["Numéro", "Numero", "NumÃ©ro", "Number"]),
        _record_value(record, ["Adresse", "Address", "Lieu", "Localisation"]),
        _record_value(record, ["Heure d'arrivée", "Heure", "Heure de départ"]),
        taxi,
        _record_value(record, ["PRIX", "Prix", "Price"]),
        status,
    ]


def _record_value(record: pd.Series, candidates: list[str]):
    for candidate in candidates:
        if candidate in record and pd.notna(record[candidate]):
            return record[candidate]
    return ""


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {str(col).lower().replace("é", "e").replace("è", "e").strip(): str(col) for col in df.columns}
    for candidate in candidates:
        key = candidate.lower().replace("é", "e").replace("è", "e").strip()
        if key in normalized:
            return normalized[key]
    return None


def _medium_black_border() -> Border:
    side = Side(style="medium", color="000000")
    return Border(left=side, right=side, top=side, bottom=side)


def _format_historique_widths(ws) -> None:
    widths = {
        "A": 13,
        "B": 12,
        "C": 25,
        "D": 20,
        "E": 13,
        "F": 12,
        "G": 42,
        "H": 15,
        "I": 12,
        "J": 12,
    }
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"
