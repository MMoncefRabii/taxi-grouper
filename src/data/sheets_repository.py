from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, NamedTuple, Optional

import logging
import pandas as pd
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from ..config import get_settings
from ..core.preprocessing import add_dispatch_block_metadata, is_repeated_header_row, load_dispatch_excel
from ..schemas import UNASSIGNED_STATUS_BY_REASON

SETTINGS = get_settings()
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TOKEN_FILE = DATA_DIR / "google_oauth_tokens.json"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
SCOPES = SETTINGS.google_scopes
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
CLIENT_ID = SETTINGS.google_client_id
CLIENT_SECRET = SETTINGS.google_client_secret
REDIRECT_URI = SETTINGS.google_oauth_redirect_uri
FRONTEND_ORIGIN = SETTINGS.frontend_origin
OUTPUT_FOLDER_ID = SETTINGS.google_output_folder_id
CLIENT_SHEET_NAME = "Taxi Grouper Client Output"

_TOKEN_FILE_LOCK = threading.Lock()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=str(path.parent), suffix=".tmp", mode="w", encoding="utf-8") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
INTERNAL_SHEET_NAME = "Taxi Grouper Internal"
CLIENT_SHEET_COLUMNS = [
    "Date",
    "Matricule",
    "Nom - Prénom",
    "Opération",
    "Site",
    "Numéro",
    "Adresse",
    "Heure d'arrivée",
    "Groupe Taxi",
    "PRIX",
    "Statut",
]
CLIENT_HEADER_FILL = "#000000"
CLIENT_HEADER_TEXT_COLOR = "#FFA500"
CLIENT_GROUP_BAND_FILL = "#FFA500"
CLIENT_GROUP_ALT_FILL = "#FFFFFF"
CLIENT_DATA_TEXT_COLOR = "#000000"
CLIENT_TAXI_TEXT_COLOR = "#FF0000"
CLIENT_TAXI_ALIGNMENT = "RIGHT"
CLIENT_HEADER_ALIGNMENT = "CENTER"


class GroupedSheetOutputs(NamedTuple):
    client_sheet_id: str
    client_sheet_url: str
    internal_sheet_id: str
    internal_sheet_url: str
CLIENT_HEADER_VERTICAL_ALIGNMENT = "MIDDLE"
CLIENT_BORDER_COLOR = "#000000"
CLIENT_BORDER_STYLE = "SOLID_MEDIUM"


def _ensure_client_settings() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Google OAuth client settings are missing. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your environment."
        )


def _load_storage() -> dict[str, Any]:
    if not TOKEN_FILE.exists():
        return {"current_user": "default", "users": {}}
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"current_user": "default", "users": {}}


def _save_storage(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _TOKEN_FILE_LOCK:
        _atomic_write_text(TOKEN_FILE, json.dumps(data, indent=2, ensure_ascii=False))


def _user_id() -> str:
    return "default"


def _save_user_info(info: dict[str, Any]) -> None:
    storage = _load_storage()
    users = storage.setdefault("users", {})
    users[_user_id()] = info
    storage["current_user"] = _user_id()
    _save_storage(storage)


def _load_user_info() -> dict[str, Any] | None:
    storage = _load_storage()
    return storage.get("users", {}).get(_user_id())


def _clear_user_info() -> None:
    storage = _load_storage()
    users = storage.setdefault("users", {})
    users.pop(_user_id(), None)
    storage["current_user"] = "default"
    _save_storage(storage)


def revoke_google_tokens() -> None:
    creds = get_credentials()
    if creds and creds.token:
        data = urllib.parse.urlencode({"token": creds.token}).encode("utf-8")
        request = urllib.request.Request(
            "https://oauth2.googleapis.com/revoke",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            urllib.request.urlopen(request, timeout=30)
        except Exception:
            pass
    _clear_user_info()


def get_auth_url() -> str:
    _ensure_client_settings()
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str) -> dict[str, Any]:
    _ensure_client_settings()
    body = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    data = urllib.parse.urlencode(body).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URI,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        token_data = json.load(response)
    if "error" in token_data:
        raise RuntimeError(token_data.get("error_description") or token_data["error"])
    token_data["token_uri"] = TOKEN_URI
    token_data["client_id"] = CLIENT_ID
    token_data["client_secret"] = CLIENT_SECRET
    token_data["scopes"] = SCOPES
    if "expires_in" in token_data:
        token_data["expiry"] = (datetime.utcnow() + pd.to_timedelta(token_data["expires_in"], unit="s")).isoformat()
    return token_data


def save_google_tokens(token_data: dict[str, Any]) -> None:
    token_data = {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_data.get("token_uri", TOKEN_URI),
        "client_id": token_data.get("client_id", CLIENT_ID),
        "scopes": token_data.get("scopes", SCOPES),
        "expiry": token_data.get("expiry"),
        "token_type": token_data.get("token_type", "Bearer"),
    }
    _save_user_info(token_data)


def _build_credentials(user_info: dict[str, Any]) -> Credentials:
    expiry = None
    if user_info.get("expiry"):
        try:
            expiry = datetime.fromisoformat(user_info["expiry"])
        except ValueError:
            expiry = None
    return Credentials(
        token=user_info.get("access_token"),
        refresh_token=user_info.get("refresh_token"),
        token_uri=user_info.get("token_uri", TOKEN_URI),
        client_id=user_info.get("client_id", CLIENT_ID),
        client_secret=user_info.get("client_secret", CLIENT_SECRET),
        scopes=user_info.get("scopes", SCOPES),
        expiry=expiry,
    )


def _store_credentials(creds: Credentials) -> None:
    user_info = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "token_type": getattr(creds, "token_type", None),
    }
    _save_user_info(user_info)


def get_credentials() -> Credentials | None:
    user_info = _load_user_info()
    if not user_info or not user_info.get("refresh_token"):
        return None

    creds = _build_credentials(user_info)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                _clear_user_info()
                return None
            _store_credentials(creds)
        else:
            return None
    return creds


def is_google_signed_in() -> bool:
    return get_credentials() is not None


def get_oauth_access_token() -> dict[str, Any] | None:
    creds = get_credentials()
    if not creds:
        return None
    return {
        "access_token": creds.token,
        "expires_at": creds.expiry.isoformat() if creds.expiry else None,
    }


def build_sheets_service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google OAuth is not configured or the user is not signed in.")
    return build("sheets", "v4", credentials=creds)


def _get_service():
    """Compatibility alias for build_sheets_service used by legacy test scripts."""
    return build_sheets_service()


def _read_google_sheet_to_dataframe(sheet_id: str, sheet_title: str | None = None) -> pd.DataFrame:
    """Read a Google Sheet (not an Office file) via the Sheets API.
    
    NOTE: Callers should ensure sheet_id is a native Google Sheet ID before calling this.
    Use _check_and_convert_to_native_sheet() first to auto-convert Office files.
    """
    logger.info("_read_google_sheet_to_dataframe called for sheet_id=%s sheet_title=%s", sheet_id, sheet_title)
    sheets = build_sheets_service()
    spreadsheet = sheets.spreadsheets().get(
        spreadsheetId=sheet_id,
        fields="sheets(properties(sheetId,title))",
    ).execute()
    sheets_list = spreadsheet.get("sheets", [])
    if not sheets_list:
        raise RuntimeError("Spreadsheet does not contain any sheets.")
    title_to_gid = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in sheets_list}
    if sheet_title is None:
        sheet_title = sheets_list[0]["properties"]["title"]
    elif sheet_title not in title_to_gid:
        raise RuntimeError(f"Spreadsheet does not contain a sheet named '{sheet_title}'.")

    result = sheets.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"'{_normalize_sheet_title(sheet_title)}'").execute()
    values = result.get("values", [])
    if not values or len(values) < 2:
        raise RuntimeError("Spreadsheet must contain a header row and at least one data row.")

    headers = [str(value) for value in values[0]]
    rows: list[list[str]] = []
    block_ordinals: list[int] = []
    block_ordinal = 1
    for row in values[1:]:
        if is_repeated_header_row(row):
            block_ordinal += 1
            continue
        padded_row = row + [""] * (len(headers) - len(row))
        if not any(str(value).strip() for value in padded_row):
            continue
        rows.append(padded_row)
        block_ordinals.append(block_ordinal)

    result = pd.DataFrame(rows, columns=headers)
    sheet_gid = title_to_gid[sheet_title]
    result["SourceSheet"] = str(sheet_gid)
    result["BlockID"] = [f"{sheet_gid}_{ordinal - 1}" for ordinal in block_ordinals]
    return add_dispatch_block_metadata(
        result,
        source_id=sheet_id,
        sheet_name=str(sheet_gid),
        block_ordinals=block_ordinals,
    )


def read_sheet_to_dataframe(sheet_id: str, sheet_title: str | None = None) -> pd.DataFrame:
    """
    Read a spreadsheet or file from Google Drive.
    
    Automatically detects if it's a Google Sheet or an Office file
    and handles conversion appropriately.
    """
    df = read_from_drive_file(sheet_id, sheet_title=sheet_title)
    return _forward_fill_grouped_taxi_column(df)


def _forward_fill_grouped_taxi_column(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill collapsed/merged taxi group values after reading from Google Sheets."""
    taxi_columns = ["Groupe Taxi", "Taxi", "Groupe", "Group"]
    for taxi_column in taxi_columns:
        if taxi_column in df.columns:
            df[taxi_column] = (
                df[taxi_column]
                .astype(str)
                .replace(r"^\s*$", pd.NA, regex=True)
                .ffill()
            )
            break
    return df


def write_grouped_df_to_sheet(
    grouped_df: pd.DataFrame,
    *,
    source_name: str = "Taxi Grouper",
    client_sheet_id: str | None = None,
    internal_sheet_id: str | None = None,
    overwrite: bool = False,
) -> GroupedSheetOutputs:
    """Write client-safe and internal results to distinct output spreadsheets."""
    output_ids_provided = client_sheet_id is not None or internal_sheet_id is not None
    if output_ids_provided and (not client_sheet_id or not internal_sheet_id):
        raise ValueError("Both client and internal output spreadsheet IDs are required.")
    if output_ids_provided != overwrite:
        raise ValueError("Explicit output spreadsheet IDs and overwrite=True must be provided together.")

    if client_sheet_id and internal_sheet_id:
        if client_sheet_id == internal_sheet_id:
            raise ValueError("Client and internal outputs must use different spreadsheets.")
    output_folder_id = OUTPUT_FOLDER_ID
    run_id = uuid.uuid4().hex[:12]

    if overwrite:
        if client_sheet_id is None or internal_sheet_id is None:
            raise ValueError("Explicit client and internal output IDs are required for overwrite.")
        client_id = client_sheet_id
        internal_id = internal_sheet_id
    else:
        client_title = f"{Path(source_name).stem} - Client Output - {run_id}"
        internal_title = f"{Path(source_name).stem} - Internal Output - {run_id}"
        client_id, _ = _create_google_sheet(client_title, output_folder_id)
        internal_id, _ = _create_google_sheet(internal_title, output_folder_id)

    if client_id == internal_id:
        raise RuntimeError("Client and internal outputs must use different spreadsheets.")

    client_gid = _ensure_output_tab(client_id, CLIENT_SHEET_NAME, newly_created=not overwrite)
    internal_gid = _ensure_output_tab(internal_id, INTERNAL_SHEET_NAME, newly_created=not overwrite)

    client_values = [CLIENT_SHEET_COLUMNS]
    for _, row in grouped_df.iterrows():
        client_values.append(_build_client_row(row))

    internal_columns = list(grouped_df.columns)
    internal_values = [internal_columns]
    for row in grouped_df.fillna("").astype(str).values.tolist():
        internal_values.append(row)

    group_ranges = _compute_group_ranges(client_values)
    _collapse_grouped_taxi_values(client_values)
    _write_values_to_sheet(client_id, CLIENT_SHEET_NAME, client_values)
    # Apply client-facing formatting with a single consistent group band and merged taxi cells.
    try:
        _apply_client_sheet_formatting(client_id, client_gid, client_values, group_ranges)
    except Exception:
        logger.warning("Could not apply client spreadsheet formatting", exc_info=True)

    _write_values_to_sheet(internal_id, INTERNAL_SHEET_NAME, internal_values)

    return GroupedSheetOutputs(
        client_sheet_id=client_id,
        client_sheet_url=f"https://docs.google.com/spreadsheets/d/{client_id}/edit#gid={client_gid}",
        internal_sheet_id=internal_id,
        internal_sheet_url=f"https://docs.google.com/spreadsheets/d/{internal_id}/edit#gid={internal_gid}",
    )


def build_drive_service():
    """Build an authenticated Google Drive API service."""
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google OAuth is not configured or the user is not signed in.")
    return build("drive", "v3", credentials=creds)


def _get_sheet_metadata(file_id: str) -> dict[str, Any]:
    """Fetch Google Sheet metadata via the Sheets API."""
    logger.info("_get_sheet_metadata called for file_id=%s", file_id)
    sheets = build_sheets_service()
    spreadsheet = sheets.spreadsheets().get(
        spreadsheetId=file_id,
        fields="spreadsheetId,properties(title)"
    ).execute()
    metadata = {
        "id": spreadsheet.get("spreadsheetId"),
        "name": spreadsheet.get("properties", {}).get("title"),
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "size": None,
    }
    logger.info("_get_sheet_metadata result for file_id=%s: %s", file_id, metadata)
    return metadata


def _get_file_metadata(file_id: str) -> dict[str, Any]:
    """Fetch file metadata (name, MIME type, etc.) from Google Drive.
    
    This tries Drive API first. If that fails with 404, falls back to Sheets API.
    Callers should use _check_and_convert_to_native_sheet() for automatic Office file conversion.
    """
    logger.info("_get_file_metadata called for file_id=%s", file_id)
    drive = build_drive_service()
    try:
        file_metadata = drive.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size",
            supportsAllDrives=True,
        ).execute()
        logger.info("_get_file_metadata result for file_id=%s: %s", file_id, file_metadata)
        return file_metadata
    except Exception as exc:
        error_text = str(exc)
        logger.info("_get_file_metadata error for file_id=%s: %s", file_id, error_text)
        if "File not found" in error_text or "notFound" in error_text:
            # Fallback to Sheets API for accessible Google Sheets files
            return _get_sheet_metadata(file_id)
        raise


def _check_and_convert_to_native_sheet(file_id: str) -> tuple[str, bool]:
    """Check if a Drive file is a native Google Sheet, and auto-convert Office files.
    
    Returns:
        (native_sheet_id, was_converted)
        
    Strategy:
    1. Try Drive API first (most reliable for mimeType)
    2. If Drive returns 404, fall back to Sheets API (user may have access via Sheets even if Drive blocked)
    3. When Sheets API detects an Office file (400 error), convert it then try Sheets API again
    """
    print(f"DEBUG: _check_and_convert_to_native_sheet called for file_id={file_id}")
    drive = build_drive_service()
    sheets = build_sheets_service()
    
    # Step 1: Try Drive API to get mimeType
    try:
        print(f"DEBUG: Step 1 - Fetching metadata from Drive API for {file_id}")
        file_metadata = drive.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size",
            supportsAllDrives=True,
        ).execute()
        mime_type = file_metadata.get("mimeType", "")
        file_name = file_metadata.get("name", file_id)
        print(f"DEBUG: Step 1 SUCCESS - Drive API returned mimeType={mime_type} for {file_name}")
        
        # Route based on mimeType
        if mime_type == "application/vnd.google-apps.spreadsheet":
            return file_id, False
        else:
            # Convert Office file
            new_id, _ = _convert_to_google_sheet(file_id, file_name)
            return new_id, True
            
    except Exception as drive_exc:
        error_text = str(drive_exc)
        print(f"DEBUG: Step 1 FAILED - Drive API error: {error_text}")
        
        # Only proceed with fallback if it's a 404
        if "notFound" not in error_text and "File not found" not in error_text:
            # For non-404 errors, re-raise
            print(f"DEBUG: Non-404 error from Drive, raising immediately")
            raise
    
    # Step 2: Drive API failed with 404. Fall back to Sheets API.
    print(f"DEBUG: Step 2 - Drive API returned 404, falling back to Sheets API")
    try:
        print(f"DEBUG: Step 2 - Attempting Sheets API call for {file_id}")
        spreadsheet = sheets.spreadsheets().get(
            spreadsheetId=file_id,
            fields="spreadsheetId,properties(title)"
        ).execute()
        # If we got here, it's a native Google Sheet
        print(f"DEBUG: Step 2 SUCCESS - Sheets API confirmed native Sheet")
        return file_id, False
    except Exception as sheets_exc:
        error_text = str(sheets_exc)
        print(f"DEBUG: Step 2 FAILED - Sheets API error: {error_text}")
        
        # Check if the error is specifically "Office file"
        if "Office file" in error_text or "must not be an Office file" in error_text:
            print(f"DEBUG: Step 2 detected Office file. Converting...")
            # Get file name (try Drive first, but use fallback if that fails)
            file_name = "Converted Spreadsheet"
            try:
                print(f"DEBUG: Attempting to fetch file name from Drive for conversion metadata...")
                metadata_resp = drive.files().get(
                    fileId=file_id,
                    fields="name",
                    supportsAllDrives=True,
                ).execute()
                file_name = metadata_resp.get("name", file_name)
                print(f"DEBUG: Got file name from Drive: {file_name}")
            except Exception as name_exc:
                print(f"DEBUG: Could not fetch file name from Drive ({str(name_exc)}), using fallback: {file_name}")
            
            # Convert the Office file
            try:
                new_id, _ = _convert_to_google_sheet(file_id, file_name)
                print(f"DEBUG: Conversion complete. Original: {file_id}, Converted: {new_id}")
                return new_id, True
            except Exception as convert_exc:
                print(f"DEBUG: Conversion failed: {str(convert_exc)}")
                raise
        
        # For other errors, re-raise
        print(f"DEBUG: Non-Office-file error from Sheets API, raising")
        raise



def get_file_metadata(file_id: str) -> dict[str, Any]:
    """Fetch file metadata from Google Drive using the repository's public API."""
    return _get_file_metadata(file_id)


def _create_google_sheet(title: str, folder_id: str | None = None) -> tuple[str, str]:
    """Create a new Google Sheet in the configured output folder."""
    folder_id = folder_id or OUTPUT_FOLDER_ID
    if not folder_id:
        raise RuntimeError(
            "Google output folder is not configured. Set GOOGLE_OUTPUT_FOLDER_ID."
        )
    drive = build_drive_service()
    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [folder_id],
    }
    created = drive.files().create(
        body=file_metadata,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    spreadsheet_id = created["id"]
    return spreadsheet_id, f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _get_spreadsheet_sheets(spreadsheet_id: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
    sheets = build_sheets_service()
    spreadsheet = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))").execute()
    sheets_list = spreadsheet.get("sheets", [])
    title_to_gid = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in sheets_list}
    return title_to_gid, sheets_list


def _ensure_sheet(spreadsheet_id: str, sheet_title: str, newly_created_spreadsheet: bool = False) -> int:
    title_to_gid, sheets_list = _get_spreadsheet_sheets(spreadsheet_id)
    if sheet_title in title_to_gid:
        return title_to_gid[sheet_title]

    if newly_created_spreadsheet and len(sheets_list) == 1:
        first_sheet_id = sheets_list[0]["properties"]["sheetId"]
        request_body = {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": first_sheet_id, "title": sheet_title},
                        "fields": "title",
                    }
                }
            ]
        }
        sheets = build_sheets_service()
        sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request_body).execute()
        return first_sheet_id

    sheets = build_sheets_service()
    response = sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet_title}}}]},
    ).execute()
    return response["replies"][0]["addSheet"]["properties"]["sheetId"]


def _ensure_output_tab(spreadsheet_id: str, sheet_title: str, newly_created: bool) -> int:
    """Prepare the sole output tab, rejecting reused spreadsheets with extra tabs."""
    title_to_gid, sheets_list = _get_spreadsheet_sheets(spreadsheet_id)
    if newly_created:
        return _ensure_sheet(spreadsheet_id, sheet_title, newly_created_spreadsheet=True)
    if len(sheets_list) != 1 or sheet_title not in title_to_gid:
        raise ValueError(
            f"Overwrite target {spreadsheet_id} must contain only the '{sheet_title}' tab."
        )
    return title_to_gid[sheet_title]


def _build_client_row(row: pd.Series) -> list[str]:
    def pref(candidates: list[str]) -> str:
        for candidate in candidates:
            if candidate in row and pd.notna(row[candidate]):
                return str(row[candidate])
        return ""

    taxi_value = row.get("Groupe Taxi") if "Groupe Taxi" in row else row.get("Taxi")
    if pd.isna(taxi_value):
        taxi_value = ""
    status = row.get("AssignmentStatus")
    if pd.isna(status) or not str(status).strip():
        reason = str(row.get("UnassignedReason", "") or "")
        status = UNASSIGNED_STATUS_BY_REASON.get(reason, "")

    return [
        pref(["Date"]),
        pref(["Matricule"]),
        pref(["Nom - Prénom", "Nom - Prenom", "Nom"]),
        pref(["Opération", "Operation", "Client"]),
        pref(["Site"]),
        pref(["Numéro", "Numero", "Number"]),
        pref(["Adresse", "Address", "Lieu", "Localisation", "Destination"]),
        pref(["Heure d'arrivée", "Heure", "Heure de départ", "Heure d'arrivee"]),
        str(taxi_value),
        pref(["PRIX", "Prix", "Price"]),
        str(status),
    ]


def _write_values_to_sheet(spreadsheet_id: str, sheet_title: str, values: list[list[str]]) -> None:
    sheets = build_sheets_service()
    sheets.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{_normalize_sheet_title(sheet_title)}'").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{_normalize_sheet_title(sheet_title)}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def _load_color_palette() -> List[str]:
    """Load the color palette from the repository-level /config/colors.json file.

    Returns a list of hex color strings (e.g. "#RRGGBB"). If the file is missing or
    invalid, returns a sensible default palette.
    """
    root = Path(__file__).resolve().parents[2]
    palette_path = root / "config" / "colors.json"
    default = [
        "#FF0000",  # Red
        "#00CC00",  # Green
        "#0066FF",  # Blue
        "#FFFF00",  # Yellow
        "#00FFFF",  # Cyan
        "#FF00FF",  # Magenta
        "#FF6600",  # Orange
        "#9933FF",  # Purple
        "#FF3366",  # Pink
        "#00FF99",  # Lime
    ]
    try:
        if palette_path.exists():
            data = json.loads(palette_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [str(x) for x in data]
    except Exception:
        pass
    return default


def _hex_to_rgb_float(hex_color: str) -> dict:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return {"red": 1.0, "green": 1.0, "blue": 1.0}
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return {"red": r, "green": g, "blue": b}


def _compute_group_ranges(client_values: list[list[str]]) -> list[tuple[int, int, str]]:
    """Return contiguous taxi group ranges before collapsed values are removed."""
    if not client_values or len(client_values) < 2:
        return []

    header = client_values[0]
    try:
        taxi_index = header.index("Groupe Taxi")
    except ValueError:
        for alt in ("Taxi", "Groupe", "Group"):
            if alt in header:
                taxi_index = header.index(alt)
                break
        else:
            return []

    group_ranges: list[tuple[int, int, str]] = []
    current_group = None
    group_start = 1
    for row_index, row in enumerate(client_values[1:], start=1):
        group_value = str(row[taxi_index]).strip() if len(row) > taxi_index else ""
        if group_value != current_group:
            if current_group is not None:
                group_ranges.append((group_start, row_index - 1, current_group))
            current_group = group_value
            group_start = row_index
    if current_group is not None:
        group_ranges.append((group_start, len(client_values) - 1, current_group))
    return group_ranges


def _collapse_grouped_taxi_values(client_values: list[list[str]]) -> None:
    """Collapse contiguous taxi group values so the taxi number appears once per group."""
    if not client_values or len(client_values) < 2:
        return

    header = client_values[0]
    try:
        taxi_index = header.index("Groupe Taxi")
    except ValueError:
        for alt in ("Taxi", "Groupe", "Group"):
            if alt in header:
                taxi_index = header.index(alt)
                break
        else:
            return

    current_group = None
    for row in client_values[1:]:
        if len(row) <= taxi_index:
            continue
        group_value = str(row[taxi_index]).strip()
        if group_value == current_group:
            row[taxi_index] = ""
        else:
            current_group = group_value


def _apply_client_sheet_formatting(
    spreadsheet_id: str,
    sheet_id: int,
    client_values: list[list[str]],
    group_ranges: list[tuple[int, int, str]],
) -> None:
    """Apply the reference client sheet style using alternating group band colors, header formatting, and merged taxi groups."""
    if not client_values or len(client_values) < 2:
        return

    header = client_values[0]
    num_columns = len(header)
    try:
        taxi_col_index = header.index("Groupe Taxi")
    except ValueError:
        for alt in ("Taxi", "Groupe", "Group"):
            if alt in header:
                taxi_col_index = header.index(alt)
                break
        else:
            return

    header_color = _hex_to_rgb_float(CLIENT_HEADER_FILL)
    band_color = _hex_to_rgb_float(CLIENT_GROUP_BAND_FILL)
    alt_band_color = _hex_to_rgb_float(CLIENT_GROUP_ALT_FILL)
    data_text_color = _hex_to_rgb_float(CLIENT_DATA_TEXT_COLOR)
    taxi_color = _hex_to_rgb_float(CLIENT_TAXI_TEXT_COLOR)
    border_color = _hex_to_rgb_float(CLIENT_BORDER_COLOR)

    requests: list[dict[str, Any]] = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_columns,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": header_color,
                        "textFormat": {"bold": True, "foregroundColor": _hex_to_rgb_float(CLIENT_HEADER_TEXT_COLOR)},
                        "horizontalAlignment": CLIENT_HEADER_ALIGNMENT,
                        "verticalAlignment": CLIENT_HEADER_VERTICAL_ALIGNMENT,
                        "borders": {
                            "bottom": {
                                "style": CLIENT_BORDER_STYLE,
                                "color": border_color,
                            }
                        },
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,borders)",
            }
        }
    ]

    # Default all data rows to white, then color alternate groups.
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": len(client_values),
                    "startColumnIndex": 0,
                    "endColumnIndex": num_columns,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": alt_band_color,
                        "textFormat": {"foregroundColor": data_text_color},
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
            }
        }
    )

    for group_index, (start, end, group_value) in enumerate(group_ranges):
        # Alternate group background colors: first group orange, second group white.
        if group_value != "":
            if group_index % 2 == 0:
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start,
                                "endRowIndex": end + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": num_columns,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": band_color,
                                    "textFormat": {"foregroundColor": data_text_color},
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
                        }
                    }
                )
        if group_value != "" and end > start:
            requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start,
                            "endRowIndex": end + 1,
                            "startColumnIndex": taxi_col_index,
                            "endColumnIndex": taxi_col_index + 1,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            )
        requests.append(
            {
                "updateBorders": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": start,
                        "endRowIndex": end + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
                    },
                    "top": {
                        "style": CLIENT_BORDER_STYLE,
                        "color": border_color,
                    },
                    "bottom": {
                        "style": CLIENT_BORDER_STYLE,
                        "color": border_color,
                    },
                    "left": {
                        "style": CLIENT_BORDER_STYLE,
                        "color": border_color,
                    },
                    "right": {
                        "style": CLIENT_BORDER_STYLE,
                        "color": border_color,
                    },
                }
            }
        )

    # Apply taxi cell formatting to the taxi column for all data rows.
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": len(client_values),
                    "startColumnIndex": taxi_col_index,
                    "endColumnIndex": taxi_col_index + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": CLIENT_TAXI_ALIGNMENT,
                        "textFormat": {"bold": True, "foregroundColor": taxi_color},
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,textFormat)",
            }
        }
    )

    sheets = build_sheets_service()
    body = {"requests": requests}
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()


def _normalize_sheet_title(title: str) -> str:
    return title.replace("'", "''")


def _convert_to_google_sheet(file_id: str, target_title: str | None = None) -> tuple[str, str]:
    """Convert a Drive file into a native Google Sheet and return its new ID and URL.
    
    If target_title is provided, uses it directly without fetching metadata.
    Otherwise tries to fetch the original file name from Drive.
    """
    # If target_title wasn't provided, try to get it from metadata
    if not target_title:
        try:
            metadata = _get_file_metadata(file_id)
            target_title = metadata.get("name", "Converted Sheet")
        except Exception:
            # If metadata fetch fails, use a default name
            print(f"DEBUG: Could not fetch metadata for {file_id}, using default name")
            target_title = "Converted Sheet"
    
    logger.info("_convert_to_google_sheet called for file_id=%s target_title=%s", file_id, target_title)
    # Converting arbitrary Drive files to Google Sheets requires drive.file scope.
    if "https://www.googleapis.com/auth/drive.file" not in SCOPES:
        raise RuntimeError(
            "Google Drive file conversion is disabled because the application does not request the drive.file scope. "
            "Either convert the file manually in Google Drive or enable the drive.file scope."
        )
    drive = build_drive_service()
    copied = drive.files().copy(
        fileId=file_id,
        body={
            "name": target_title,
            "mimeType": "application/vnd.google-apps.spreadsheet",
        },
        supportsAllDrives=True,
        fields="id,name"
    ).execute()
    new_id = copied["id"]
    result = (new_id, f"https://docs.google.com/spreadsheets/d/{new_id}/edit")
    logger.info("_convert_to_google_sheet result for file_id=%s -> new_id=%s", file_id, new_id)
    return result


def ensure_google_sheet(file_id: str) -> tuple[str, str]:
    """Ensure the provided Drive file is a native Google Sheet.

    If the file is already a Google Sheet, return the original ID and URL.
    Otherwise, convert it to Google Sheets format and return the new ID and URL.
    
    NOTE: This is deprecated in favor of _check_and_convert_to_native_sheet() which
    checks mimeType before making any Sheets API calls. Use that for new code.
    """
    metadata = _get_file_metadata(file_id)
    logger.info("ensure_google_sheet called for file_id=%s metadata=%s", file_id, metadata)
    if metadata.get("mimeType") == "application/vnd.google-apps.spreadsheet":
        return file_id, f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    return _convert_to_google_sheet(file_id, metadata.get("name"))


def create_google_sheet_from_dataframe(
    df: pd.DataFrame,
    title: str = "Taxi Grouper Export",
    *,
    client_sheet_id: str | None = None,
    internal_sheet_id: str | None = None,
    overwrite: bool = False,
) -> GroupedSheetOutputs:
    """Write a DataFrame to separate client and internal Google spreadsheets."""
    return write_grouped_df_to_sheet(
        df,
        source_name=title,
        client_sheet_id=client_sheet_id,
        internal_sheet_id=internal_sheet_id,
        overwrite=overwrite,
    )


def _download_file(file_id: str, dest_path: str) -> None:
    """Download a file from Google Drive to a local destination."""
    drive = build_drive_service()
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()


def _excel_to_dataframe(file_path: str, source_id: str | None = None) -> pd.DataFrame:
    """Convert an Excel file to a pandas DataFrame."""
    return load_dispatch_excel(
        file_path,
        read_all_sheets=False,
        source_id=source_id or Path(file_path).name,
    )


def read_from_drive_file(file_id: str, sheet_title: str | None = None) -> pd.DataFrame:
    """
    Read data from a Google Drive file (Google Sheet or Office file).
    
    - If it's a Google Sheet: fetch via Sheets API
    - If it's an Excel/Office file: download and convert to DataFrame
    
    Returns a pandas DataFrame with headers from the first row.
    """
    metadata = _get_file_metadata(file_id)
    mime_type = metadata.get("mimeType", "")
    filename = metadata.get("name", "file")
    
    # Google Sheets: fetch via Sheets API
    if mime_type == "application/vnd.google-apps.spreadsheet":
        return _read_google_sheet_to_dataframe(file_id, sheet_title=sheet_title)
    
    # Office/Excel files: download and convert
    if "spreadsheet" in mime_type.lower() or filename.lower().endswith((".xlsx", ".xls", ".csv")):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_file = Path(tmpdir) / filename
            _download_file(file_id, str(temp_file))
            return _excel_to_dataframe(str(temp_file), source_id=filename)
    
    raise ValueError(f"Unsupported file type: {mime_type}. Please use a Google Sheet or Excel file.")


def get_frontend_redirect_url(success: bool, message: str | None = None) -> str:
    query = {"auth": "success" if success else "error"}
    if message:
        query["message"] = message
    return f"{FRONTEND_ORIGIN}?{urllib.parse.urlencode(query)}"
