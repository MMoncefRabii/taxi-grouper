"""Excel loading and flexible column detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd

from .zones import normalize_text
from ..schemas import HISTORIQUE_COLUMNS, HISTORIQUE_COLUMNS_WITH_NUMERO


ADDRESS_ALIASES = ["adresse", "address", "lieu", "localisation", "adresse ramassage", "ramassage", "retour"]
TIME_ALIASES = ["heure", "heure arrivee", "heure d arrivee", "heure depart", "heure de depart", "heure ramassage", "heure retour"]
NAME_ALIASES = ["nom", "nom prenom", "nom agent", "agent", "nom - prenom"]
TAXI_ALIASES = ["taxi", "groupe", "groupe taxi", "taxi id", "taxi_group", "taxi group"]
OPERATION_ALIASES = ["operation", "opération", "client"]
SITE_ALIASES = ["site"]
TYPE_COURSE_ALIASES = ["type de course", "ramassage retour", "ramassage / retour"]
DISPATCH_ID_ALIASES = {
    "dispatchid",
    "sourcedispatchid",
    "iddispatch",
    "dispatchnumber",
    "dispatchno",
}


@dataclass(frozen=True)
class ColumnMap:
    address: str
    time: str | None = None
    name: str | None = None
    taxi: str | None = None
    operation: str | None = None
    site: str | None = None
    type_course: str | None = None
    client: str | None = None


def load_excel(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    return pd.read_excel(path)


def is_repeated_header_row(values: list[object]) -> bool:
    return _matching_header(values) is not None


def _matching_header(values: list[object]) -> list[str] | None:
    normalized_values = [normalize_text(value) for value in values]
    for header in [HISTORIQUE_COLUMNS_WITH_NUMERO, HISTORIQUE_COLUMNS]:
        expected = [normalize_text(value) for value in header]
        if normalized_values[: len(expected)] == expected:
            extra_headers = [
                str(value).strip() if not pd.isna(value) else ""
                for value in values[len(expected) :]
            ]
            while extra_headers and not extra_headers[-1]:
                extra_headers.pop()
            return list(header) + extra_headers
        if all(column in normalized_values for column in expected) and any(
            _normalized_dispatch_id(value) in DISPATCH_ID_ALIASES for value in values
        ):
            headers = [str(value).strip() if not pd.isna(value) else "" for value in values]
            while headers and not headers[-1]:
                headers.pop()
            return headers
    return None


def _normalized_dispatch_id(value: object) -> str:
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _find_dispatch_id_column(columns: list[str]) -> str | None:
    return next(
        (
            column
            for column in columns
            if _normalized_dispatch_id(column) in DISPATCH_ID_ALIASES
        ),
        None,
    )


def _clean_dispatch_id(value: object) -> str | None:
    if pd.isna(value):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _add_dispatch_block_metadata(
    df: pd.DataFrame,
    source_id: str,
    sheet_name: str,
    block_ordinals: list[int],
) -> pd.DataFrame:
    result = df.copy()
    dispatch_id_column = _find_dispatch_id_column(list(result.columns))
    if dispatch_id_column is not None:
        result["SourceDispatchID"] = result[dispatch_id_column].map(_clean_dispatch_id)
        result["block_id_origin"] = "provided"
        return result

    source = str(source_id).strip()
    sheet = str(sheet_name).strip()
    generated_ids = [
        f"{source} | {sheet} | {ordinal}" if source and sheet and ordinal > 0 else None
        for ordinal in block_ordinals
    ]
    result["SourceDispatchID"] = generated_ids
    result["block_id_origin"] = [
        "synthesized" if dispatch_id is not None else ""
        for dispatch_id in generated_ids
    ]
    return result


def add_dispatch_block_metadata(
    df: pd.DataFrame,
    source_id: str,
    sheet_name: str,
    block_ordinal: int = 1,
    block_ordinals: list[int] | None = None,
) -> pd.DataFrame:
    """Attach a provided or source-namespaced synthesized dispatch id."""
    ordinals = block_ordinals if block_ordinals is not None else [block_ordinal] * len(df)
    if len(ordinals) != len(df):
        raise ValueError("block_ordinals must contain one ordinal for each dataframe row.")
    return _add_dispatch_block_metadata(
        df,
        source_id=source_id,
        sheet_name=sheet_name,
        block_ordinals=ordinals,
    )


def load_dispatch_excel(
    path: str | Path,
    read_all_sheets: bool = True,
    source_id: str | None = None,
) -> pd.DataFrame:
    """Load a dispatch workbook, removing repeated Historique-style header rows safely."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if path.suffix.lower() == ".ods":
        raw_sheets = _read_ods_raw_sheets(path)
        if not read_all_sheets:
            first_name = next(iter(raw_sheets))
            raw_sheets = {first_name: raw_sheets[first_name]}
    else:
        try:
            raw_sheets = pd.read_excel(path, sheet_name=None if read_all_sheets else 0, header=None)
        except ImportError as exc:
            raise ImportError("This Excel format requires an optional dependency. Install xlrd for .xls files.") from exc

    if isinstance(raw_sheets, pd.DataFrame):
        raw_sheets = {"Sheet1": raw_sheets}

    frames: list[pd.DataFrame] = []
    source_id = source_id or path.name
    for sheet_name, raw in raw_sheets.items():
        current_block = -1
        current_headers: list[str] | None = None
        rows: list[dict[str, object]] = []
        block_ordinals: list[int] = []
        saw_repeated_header = False
        for raw_index, raw_row in raw.iterrows():
            values = raw_row.tolist()
            matched_header = _matching_header(values)
            if matched_header:
                saw_repeated_header = True
                current_headers = matched_header
                current_block += 1
                continue
            if saw_repeated_header:
                headers = current_headers or HISTORIQUE_COLUMNS
                values = raw_row.iloc[: len(headers)].tolist()
                if current_block < 0 or all(pd.isna(value) or str(value).strip() == "" for value in values):
                    continue
                record = dict(zip(headers, values))
                record["SourceSheet"] = sheet_name
                record["BlockID"] = f"{sheet_name}_{current_block}"
                rows.append(record)
                block_ordinals.append(current_block + 1)

        if saw_repeated_header:
            if rows:
                sheet_frame = pd.DataFrame(rows)
                frames.append(
                    _add_dispatch_block_metadata(
                        sheet_frame,
                        source_id=source_id,
                        sheet_name=sheet_name,
                        block_ordinals=block_ordinals,
                    )
                )
        else:
            if path.suffix.lower() == ".ods":
                normal = _raw_sheet_to_table(raw)
            else:
                normal = pd.read_excel(path, sheet_name=sheet_name)
            normal["SourceSheet"] = sheet_name
            normal["BlockID"] = f"{sheet_name}_0"
            frames.append(
                _add_dispatch_block_metadata(
                    normal,
                    source_id=source_id,
                    sheet_name=sheet_name,
                    block_ordinals=[1] * len(normal),
                )
            )

    if not frames:
        raise ValueError("No agent rows found in the Excel file.")
    result = pd.concat(frames, ignore_index=True)
    result = result[~result.apply(lambda row: is_repeated_header_row(row.tolist()), axis=1)].reset_index(drop=True)
    return result


def _read_ods_raw_sheets(path: Path) -> dict[str, pd.DataFrame]:
    """Read ODS sheets with stdlib XML parsing, returning headerless dataframes."""
    namespaces = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    }
    with zipfile.ZipFile(path) as archive:
        content = archive.read("content.xml")
    root = ET.fromstring(content)
    sheets: dict[str, pd.DataFrame] = {}
    for table in root.findall(".//table:table", namespaces):
        sheet_name = table.attrib.get(f"{{{namespaces['table']}}}name", "Sheet1")
        rows: list[list[object]] = []
        for row_node in table.findall("table:table-row", namespaces):
            repeat_rows = int(row_node.attrib.get(f"{{{namespaces['table']}}}number-rows-repeated", "1"))
            parsed_row: list[object] = []
            for cell in row_node.findall("table:table-cell", namespaces):
                repeat_cols = int(cell.attrib.get(f"{{{namespaces['table']}}}number-columns-repeated", "1"))
                value = _ods_cell_value(cell, namespaces)
                parsed_row.extend([value] * min(repeat_cols, 50))
            if any(value not in (None, "") for value in parsed_row):
                for _ in range(min(repeat_rows, 2000)):
                    rows.append(parsed_row)
        max_len = max((len(row) for row in rows), default=0)
        normalized_rows = [row + [None] * (max_len - len(row)) for row in rows]
        sheets[sheet_name] = pd.DataFrame(normalized_rows)
    return sheets


def _raw_sheet_to_table(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    header_index = None
    for idx, row in raw.iterrows():
        values = [str(value).strip() if value is not None and not pd.isna(value) else "" for value in row.tolist()]
        if any(values):
            header_index = idx
            break
    if header_index is None:
        return pd.DataFrame()
    headers = [str(value).strip() if value is not None and not pd.isna(value) else f"Column{pos + 1}" for pos, value in enumerate(raw.iloc[header_index].tolist())]
    data = raw.iloc[header_index + 1 :].copy()
    data.columns = headers
    data = data.dropna(how="all").reset_index(drop=True)
    return data


def _ods_cell_value(cell: ET.Element, namespaces: dict[str, str]) -> object:
    office_ns = namespaces["office"]
    value_type = cell.attrib.get(f"{{{office_ns}}}value-type", "")
    if value_type == "float":
        raw = cell.attrib.get(f"{{{office_ns}}}value")
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return raw
    if value_type == "date":
        return cell.attrib.get(f"{{{office_ns}}}date-value")
    if value_type == "time":
        return cell.attrib.get(f"{{{office_ns}}}time-value")
    paragraphs = []
    for paragraph in cell.findall(".//text:p", namespaces):
        text = "".join(paragraph.itertext()).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs).strip() if paragraphs else None


def _best_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized_columns = {col: normalize_text(col) for col in columns}
    normalized_aliases = [normalize_text(alias) for alias in aliases]
    for alias in normalized_aliases:
        for col, norm_col in normalized_columns.items():
            if norm_col == alias:
                return col
    for alias in normalized_aliases:
        for col, norm_col in normalized_columns.items():
            if alias in norm_col or norm_col in alias:
                return col
    return None


def detect_columns(df: pd.DataFrame, require_taxi: bool = False) -> ColumnMap:
    columns = list(df.columns)
    address = _best_column(columns, ADDRESS_ALIASES)
    if not address:
        raise ValueError("Missing required address column. Expected one of: Adresse, Address, Lieu, Localisation, Adresse Ramassage.")

    taxi = _best_column(columns, TAXI_ALIASES)
    if require_taxi and not taxi:
        raise ValueError("Training file must contain a Taxi / Groupe Taxi column with validated groups.")

    return ColumnMap(
        address=address,
        time=_best_column(columns, TIME_ALIASES),
        name=_best_column(columns, NAME_ALIASES),
        taxi=taxi,
        operation=_best_column(columns, OPERATION_ALIASES),
        site=_best_column(columns, SITE_ALIASES),
        type_course=_best_column(columns, TYPE_COURSE_ALIASES),
        client=_best_column(columns, ["client"]),
    )


def filter_dataframe(df: pd.DataFrame, columns: ColumnMap, time_value: str | None = None, type_course: str | None = None, operation: str | None = None) -> pd.DataFrame:
    result = df.copy()
    if time_value and columns.time:
        result = result[result[columns.time].astype(str).str.strip().str.contains(str(time_value), case=False, na=False, regex=False)]
    if type_course and columns.type_course:
        result = result[result[columns.type_course].astype(str).str.contains(type_course, case=False, na=False, regex=False)]
    if operation and columns.operation:
        result = result[result[columns.operation].astype(str).str.contains(operation, case=False, na=False, regex=False)]
    return result.reset_index(drop=True)


def clean_destinations_for_dispatch(df: pd.DataFrame, columns: ColumnMap | None = None) -> pd.DataFrame:
    """Run destination cleaning before dispatch without modifying the original dataframe."""
    from .destination_cleaner import add_clean_destination_columns

    columns = columns or detect_columns(df)
    return add_clean_destination_columns(df, columns.address)
