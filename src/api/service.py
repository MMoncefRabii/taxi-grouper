"""
FastAPI backend for Taxi Grouper - wraps existing grouping logic without modifications.

Run with: uvicorn src.api.service:app --reload
"""

import json
import os
import tempfile
import threading
import urllib.parse
from pathlib import Path
import logging

# Ensure INFO-level logs are emitted for our modules during debugging
logging.basicConfig(level=logging.INFO)

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, UploadFile, Query, HTTPException, Body
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.core.preprocessing import load_dispatch_excel, detect_columns, filter_dataframe
from src.core.grouper import group_agents, validate_dispatch
from src.api.authentication import ApiKeyAuthMiddleware
from src.api.launcher import get_api_host
from src.adapters.exporter import export_excel
from src.config import TAXI_COLUMN, MAX_TAXI_CAPACITY, UNKNOWN_ZONE, get_settings
from src.data.sheets_repository import (
    get_auth_url,
    get_frontend_redirect_url,
    get_oauth_access_token,
    exchange_code_for_token,
    revoke_google_tokens,
    save_google_tokens,
    is_google_signed_in,
    read_sheet_to_dataframe,
    write_grouped_df_to_sheet,
    get_file_metadata,
    ensure_google_sheet,
    create_google_sheet_from_dataframe,
    CLIENT_SHEET_NAME,
)
from src.data.training_data_manager import (
    store_pre_correction_state,
    extract_training_examples_from_corrections,
    write_training_examples_to_file,
    append_corrections_to_training_file,
    get_pre_correction_cache_size,
    count_training_corrections,
    load_retrain_state,
    should_trigger_retrain,
    run_retraining_pipeline,
    _get_training_corrections_path,
)

class GroupUploadRequestTooLarge(Exception):
    pass


class GroupUploadSizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/group":
            await self.app(scope, receive, send)
            return

        max_upload_size = get_settings().max_upload_size_bytes
        max_request_size = max_upload_size + UPLOAD_MULTIPART_OVERHEAD_BYTES
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                request_size = int(content_length)
            except ValueError:
                response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
                await response(scope, receive, send)
                return
            if request_size < 0:
                response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
                await response(scope, receive, send)
                return
            if request_size > max_request_size:
                await self._too_large_response(scope, receive, send, max_upload_size)
                return

        received_size = 0
        request_too_large = False

        async def limited_receive():
            nonlocal received_size, request_too_large
            message = await receive()
            if message["type"] == "http.request":
                received_size += len(message.get("body", b""))
                if received_size > max_request_size:
                    request_too_large = True
                    raise GroupUploadRequestTooLarge
            return message

        async def limited_send(message):
            if not request_too_large:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except GroupUploadRequestTooLarge:
            pass
        if request_too_large:
            await self._too_large_response(scope, receive, send, max_upload_size)

    @staticmethod
    async def _too_large_response(scope, receive, send, max_upload_size):
        response = JSONResponse(
            status_code=413,
            content={
                "detail": (
                    "Uploaded request exceeds the maximum allowed file size of "
                    f"{max_upload_size} bytes."
                )
            },
        )
        await response(scope, receive, send)


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_retrain_lock = threading.Lock()
_retrain_task_scheduled = False
UPLOAD_CHUNK_SIZE = 64 * 1024
UPLOAD_MULTIPART_OVERHEAD_BYTES = 64 * 1024
_UPLOAD_SIGNATURES = {
    ".xlsx": b"PK",
    ".ods": b"PK",
    ".xls": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
}

class SheetInfoRequest(BaseModel):
    sheet_id: str


class SaveToDriveRequest(BaseModel):
    grouped_data: list[dict]
    sheet_name: str | None = None

settings = get_settings()

DEBUG_POST_CORRECTION_DIR = Path("data/debug_post_correction_cache")

class DebugSetCorrectionRequest(BaseModel):
    sheet_id: str
    pre_correction: list[dict]
    post_correction: list[dict]


def _ensure_native_sheet(sheet_id: str) -> tuple[str, str, bool]:
    """Ensure a Drive file is a native Google Sheet.
    
    Uses the new mimeType-first flow from _check_and_convert_to_native_sheet():
    1. Fetches file metadata from Drive
    2. Checks mimeType
    3. Converts Office files to native Sheets BEFORE any Sheets API call
    4. Returns the native sheet ID and whether conversion occurred

    Returns:
        tuple[native_sheet_id, native_sheet_url, converted_from_office_file]
    """
    print(f"DEBUG: _ensure_native_sheet called for sheet_id={sheet_id}")
    logger.info("_ensure_native_sheet called for sheet_id=%s", sheet_id)
    
    # Use new mimeType-first conversion flow
    from src.data.sheets_repository import _check_and_convert_to_native_sheet
    native_sheet_id, was_converted = _check_and_convert_to_native_sheet(sheet_id)
    
    native_sheet_url = f"https://docs.google.com/spreadsheets/d/{native_sheet_id}/edit"
    logger.info(
        "_ensure_native_sheet result: original=%s converted=%s native_id=%s native_url=%s",
        sheet_id,
        was_converted,
        native_sheet_id,
        native_sheet_url,
    )
    return native_sheet_id, native_sheet_url, was_converted

app = FastAPI(
    title="Taxi Grouper API",
    version="1.0.0",
    description="Backend API for taxi grouping optimization - Grand Tunis",
)

app.add_middleware(GroupUploadSizeLimitMiddleware)
app.add_middleware(ApiKeyAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/auth/login-url")
async def auth_login_url():
    """Return the Google OAuth login URL for the single-user web app."""
    try:
        return {"auth_url": get_auth_url()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not build Google auth URL: {str(exc)}")


@app.get("/api/auth/status")
async def auth_status():
    """Return whether the current user has a stored Google OAuth session."""
    return {"signed_in": is_google_signed_in()}


@app.get("/api/auth/token")
async def auth_token():
    """Return a fresh OAuth access token for the current signed-in user."""
    token_info = get_oauth_access_token()
    if not token_info:
        raise HTTPException(status_code=401, detail="Google OAuth is not configured or the user is not signed in.")
    return token_info


@app.post("/api/auth/logout")
async def auth_logout():
    """Clear the stored Google OAuth session for the current user."""
    try:
        revoke_google_tokens()
        return {"success": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not disconnect Google OAuth: {str(exc)}")


@app.get("/auth/callback")
async def auth_callback(code: str | None = None, error: str | None = None):
    """Exchange Google OAuth code for tokens and redirect back to the frontend."""
    if error:
        return RedirectResponse(get_frontend_redirect_url(False, error))
    if not code:
        return RedirectResponse(get_frontend_redirect_url(False, "Missing authorization code"))
    try:
        token_info = exchange_code_for_token(code)
        save_google_tokens(token_info)
        return RedirectResponse(get_frontend_redirect_url(True))
    except Exception as exc:
        return RedirectResponse(get_frontend_redirect_url(False, str(exc)))


@app.post("/api/group-sheet")
async def group_sheet_endpoint(
    sheet_id: str = Body(..., description="Google Spreadsheet ID selected by the user"),
    time_filter: str | None = Body(None, description="Optional time filter (e.g., '07:00')"),
    type_course_filter: str | None = Body(None, description="Optional course type ('Ramassage' or 'Retour')"),
    operation_filter: str | None = Body(None, description="Optional client/operation filter"),
    use_ml: bool = Body(True, description="Use ML-assisted ordering (default True)"),
):
    """Group agents from a Google Sheet and write results into a results worksheet."""
    if not sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id is required")

    converted_from_office_file = False
    converted_sheet_url = None
    try:
        sheet_id, converted_sheet_url, converted_from_office_file = _ensure_native_sheet(sheet_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not convert selected file to Google Sheet: {str(exc)}")

    try:
        df = read_sheet_to_dataframe(sheet_id)
        if df.empty:
            raise HTTPException(status_code=400, detail="Selected file is empty or has no valid rows")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"File error: {str(exc)}")
    except Exception as exc:
        error_msg = str(exc)
        if "Office file" in error_msg or "not be an Office file" in error_msg:
            raise HTTPException(
                status_code=400,
                detail="Selected file is an Excel/Office file. Please use a Google Sheet instead. To convert: Right-click the file in Google Drive > Open with > Google Sheets"
            )
        raise HTTPException(status_code=400, detail=f"Failed to load file: {error_msg}")

    try:
        columns = detect_columns(df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Could not detect required columns in sheet: {str(exc)}")

    df_filtered = filter_dataframe(
        df,
        columns,
        time_value=time_filter or None,
        type_course=type_course_filter or None,
        operation=operation_filter or None,
    )
    if df_filtered.empty:
        raise HTTPException(status_code=400, detail=f"No rows match filters: time={time_filter}, course={type_course_filter}, operation={operation_filter}")

    grouped, warnings = group_agents(df_filtered, columns=columns, use_ml=use_ml)
    validation = validate_dispatch(grouped, taxi_column=TAXI_COLUMN, capacity=MAX_TAXI_CAPACITY)

    try:
        sheet_url = write_grouped_df_to_sheet(sheet_id, grouped)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write grouped results to Google Sheet: {str(exc)}")

    # Store pre-correction state so we can diff corrections later
    store_pre_correction_state(sheet_id, grouped)

    grouped_json = json.loads(grouped.to_json(orient="records", date_format="iso"))
    stats = {
        "total_agents": len(grouped),
        "total_taxis": int(grouped[TAXI_COLUMN].max()) if TAXI_COLUMN in grouped.columns else 0,
        "unknown_count": int((grouped.get("Zone", pd.Series()) == UNKNOWN_ZONE).sum()),
    }

    response = {
        "sheet_url": sheet_url,
        "grouped_data": grouped_json,
        "stats": stats,
        "warnings": warnings,
        "validation": {
            "valid": validation["valid"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
            "taxi_reports": validation["taxi_reports"],
        },
    }
    if converted_from_office_file:
        response["converted_from_office_file"] = True
        response["converted_sheet_url"] = converted_sheet_url

    return response


@app.post("/api/sheet-info")
async def sheet_info_endpoint(
    request: SheetInfoRequest,
):
    """Load sheet metadata and available filter values for a connected Google Sheet.
    
    Uses the new mimeType-first flow: checks file type, converts Office files to 
    native Sheets BEFORE any Sheets API call.
    """
    sheet_id = request.sheet_id
    if not sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id is required")

    converted_from_office_file = False
    converted_sheet_url = None
    try:
        sheet_id, converted_sheet_url, converted_from_office_file = _ensure_native_sheet(sheet_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not load or convert file. "
                "Please ensure the file is accessible and is a valid spreadsheet. "
                f"({str(exc)})"
            ),
        )

    try:
        metadata = get_file_metadata(sheet_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to fetch converted file metadata: {str(exc)}")

    sheet_url = converted_sheet_url or f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    try:
        df = read_sheet_to_dataframe(sheet_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"File error: {str(exc)}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load sheet metadata: {str(exc)}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Selected sheet is empty or has no valid rows")

    try:
        columns = detect_columns(df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Could not detect required columns in sheet: {str(exc)}")

    time_values = []
    operation_values = []

    if columns.time and columns.time in df.columns:
        time_values = (
            df[columns.time]
            .astype(str)
            .str.strip()
            .replace({'': pd.NA})
            .dropna()
            .unique()
            .tolist()
        )
    if columns.operation and columns.operation in df.columns:
        operation_values = (
            df[columns.operation]
            .astype(str)
            .str.strip()
            .replace({'': pd.NA})
            .dropna()
            .unique()
            .tolist()
        )

    return {
        "sheet_id": sheet_id,
        "sheet_title": metadata.get("name", "Google Sheet"),
        "sheet_url": sheet_url,
        "available_times": sorted(str(val) for val in time_values),
        "available_operations": sorted(str(val) for val in operation_values),
        "converted_from_office_file": converted_from_office_file,
        "converted_sheet_url": converted_sheet_url,
    }


@app.post("/api/validate-sheet")
async def validate_sheet_endpoint(request: SheetInfoRequest, background_tasks: BackgroundTasks):
    """Validate the current client-facing results sheet after manual corrections."""
    sheet_id = request.sheet_id
    if not sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id is required")

    converted_from_office_file = False
    converted_sheet_url = None
    try:
        debug_df = _load_debug_post_correction_state(sheet_id)
        if debug_df is not None:
            df = debug_df
        else:
            sheet_id, converted_sheet_url, converted_from_office_file = _ensure_native_sheet(sheet_id)
            df = read_sheet_to_dataframe(sheet_id)
            if df.empty:
                raise HTTPException(status_code=400, detail="Selected sheet is empty or has no valid rows")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"File error: {str(exc)}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load sheet for validation: {str(exc)}")

    try:
        validation = validate_dispatch(df, taxi_column=TAXI_COLUMN, capacity=MAX_TAXI_CAPACITY)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(exc)}")

    # Extract training data from corrected results
    extraction = extract_training_examples_from_corrections(sheet_id, df, taxi_column=TAXI_COLUMN)
    if extraction["success"] and extraction["corrections"]:
        # Write canonical JSONL training file (one JSON object per line)
        # Uses separate debug file when DEBUG=1 to prevent test data contamination
        try:
            training_file_path = _get_training_corrections_path()
            write_training_examples_to_file(extraction["corrections"], output_path=training_file_path)
        except Exception as exc:
            logger.exception("Failed to write JSONL training file, falling back to Excel: %s", exc)
            # Fall back to Excel append for backward compatibility
            append_corrections_to_training_file(extraction["corrections"])

    if _load_debug_post_correction_state(sheet_id) is not None:
        _clear_debug_post_correction_state(sheet_id)

    retrain_scheduled = False
    if extraction["success"] and extraction["corrections"]:
        retrain_scheduled = _schedule_background_retrain(background_tasks)

    response = {
        "validation": {
            "valid": validation["valid"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
            "taxi_reports": validation["taxi_reports"],
        },
        "training": {
            "success": extraction["success"],
            "rows_changed": len(extraction["corrections"]),
            "stats": extraction["stats"],
            "error": extraction.get("error"),
            "retrain_scheduled": retrain_scheduled,
        }
    }
    if converted_from_office_file:
        response["converted_from_office_file"] = True
        response["converted_sheet_url"] = converted_sheet_url

    return response


def _schedule_background_retrain(background_tasks: BackgroundTasks) -> bool:
    global _retrain_task_scheduled
    if _retrain_task_scheduled:
        logger.info("Retrain already scheduled, skipping duplicate scheduling")
        return False

    total_count = count_training_corrections()
    state = load_retrain_state()
    if not should_trigger_retrain(total_count, settings.retrain_threshold, state):
        logger.debug(
            "Retrain threshold not reached: %s/%s",
            total_count - state.get("last_processed_count", 0),
            settings.retrain_threshold,
        )
        return False

    _retrain_task_scheduled = True
    background_tasks.add_task(_background_retrain, settings.retrain_threshold)
    logger.info("Scheduled background retraining: total_count=%s threshold=%s", total_count, settings.retrain_threshold)
    return True


def _background_retrain(threshold: int) -> None:
    global _retrain_task_scheduled
    if not _retrain_lock.acquire(blocking=False):
        logger.info("Retraining already in progress, skipping this background task")
        _retrain_task_scheduled = False
        return
    try:
        result = run_retraining_pipeline(threshold)
        logger.info("Background retrain finished: %s", result)
    except Exception as exc:
        logger.exception("Background retrain failed: %s", exc)
    finally:
        _retrain_task_scheduled = False
        _retrain_lock.release()

def _debug_post_correction_state_path(sheet_id: str) -> Path:
    safe_id = urllib.parse.quote_plus(sheet_id)
    return DEBUG_POST_CORRECTION_DIR / f"{safe_id}.json"


def _ensure_debug_post_correction_dir() -> None:
    DEBUG_POST_CORRECTION_DIR.mkdir(parents=True, exist_ok=True)


def _save_debug_post_correction_state(sheet_id: str, df: pd.DataFrame) -> None:
    _ensure_debug_post_correction_dir()
    path = _debug_post_correction_state_path(sheet_id)
    df.to_json(path, orient="split", force_ascii=False)


def _load_debug_post_correction_state(sheet_id: str) -> pd.DataFrame | None:
    path = _debug_post_correction_state_path(sheet_id)
    if not path.exists():
        return None
    try:
        return pd.read_json(path, orient="split")
    except Exception:
        return None


def _clear_debug_post_correction_state(sheet_id: str) -> None:
    path = _debug_post_correction_state_path(sheet_id)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass


@app.post("/api/debug/set-correction")
async def debug_set_correction(request: DebugSetCorrectionRequest):
    """Debug-only endpoint to seed pre- and post-correction state for validation tests.
    
    Production guard: Only available when DEBUG=1 environment variable is explicitly set.
    This endpoint is test-only and allows artificially injecting test data.
    """
    if os.getenv("DEBUG") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    
    if not request.sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id is required")

    try:
        pre_df = pd.DataFrame(request.pre_correction)
        post_df = pd.DataFrame(request.post_correction)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid debug correction payload: {exc}")

    if pre_df.empty or post_df.empty:
        raise HTTPException(status_code=400, detail="pre_correction and post_correction must contain at least one row")
    if len(pre_df) != len(post_df):
        raise HTTPException(status_code=400, detail="pre_correction and post_correction must have the same number of rows")
    if TAXI_COLUMN not in pre_df.columns or TAXI_COLUMN not in post_df.columns:
        raise HTTPException(status_code=400, detail=f"Both pre_correction and post_correction data must include the taxi column '{TAXI_COLUMN}'")

    store_pre_correction_state(request.sheet_id, pre_df)
    _save_debug_post_correction_state(request.sheet_id, post_df)
    return {
        "success": True,
        "sheet_id": request.sheet_id,
        "rows": len(post_df),
    }


@app.get("/api/debug/training-cache")
async def debug_training_cache():
    """Debug-only endpoint to inspect pre-correction cache size.
    
    Production guard: Only available when DEBUG=1 environment variable is explicitly set.
    This endpoint is for monitoring the training data capture pipeline during testing.
    """
    if os.getenv("DEBUG") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    
    cache_size = get_pre_correction_cache_size()
    return {"pre_correction_cache_size": cache_size}


@app.post("/api/save-drive")
async def save_drive_endpoint(request: SaveToDriveRequest):
    """Save grouped results directly to Google Drive as a new Google Sheet."""
    if not request.grouped_data:
        raise HTTPException(status_code=400, detail="grouped_data must not be empty")

    try:
        df = pd.DataFrame(request.grouped_data)
        if df.empty:
            raise ValueError("grouped_data could not be converted into a DataFrame")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid grouped_data: {str(exc)}")

    try:
        sheet_name = request.sheet_name or "Taxi Grouper Export"
        sheet_id, sheet_url = create_google_sheet_from_dataframe(df, title=sheet_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save grouped results to Drive: {str(exc)}")

    return {"sheet_url": sheet_url, "sheet_id": sheet_id}


@app.post("/api/group")
async def group_agents_endpoint(
    file: UploadFile = File(..., description="Excel file with agent data"),
    time_filter: str | None = Query(None, description="Optional time filter (e.g., '07:00')"),
    type_course_filter: str | None = Query(None, description="Optional course type ('Ramassage' or 'Retour')"),
    operation_filter: str | None = Query(None, description="Optional client/operation filter"),
    use_ml: bool = Query(True, description="Use ML-assisted ordering (default True)"),
):
    """
    Group agents into taxis from an uploaded Excel file.

    **Workflow:**
    1. Load and parse Excel → preprocessing.load_dispatch_excel()
    2. Auto-detect columns (address, taxi, time, etc.) → preprocessing.detect_columns()
    3. Apply filters (time, course type, operation) → preprocessing.filter_dataframe()
    4. Enrich with clean destinations → destination_cleaner.add_clean_destination_columns()
    5. Run grouping algorithm → grouper.group_agents() (uses ml_model if use_ml=True)
    6. Validate output → grouper.validate_dispatch()
    7. Return JSON with grouped data, stats, warnings, and validation results

    **Returns:**
    - grouped_data: array of agent records with assigned taxi, zone, destination
    - stats: total agents, taxis formed, unknown addresses
    - warnings: list of issues (e.g., low-confidence destinations)
    - validation: status and per-taxi validation reports
    """
    temp_file: Path | None = None
    try:
        filename = file.filename or ""
        extension = Path(filename).suffix.lower()
        expected_signature = _UPLOAD_SIGNATURES.get(extension)
        if expected_signature is None:
            raise HTTPException(
                status_code=415,
                detail="Unsupported upload type. Use an .xlsx, .xls, or .ods workbook.",
            )

        max_upload_size = get_settings().max_upload_size_bytes
        total_size = 0
        signature = b""
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_handle:
            temp_file = Path(temp_handle.name)
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > max_upload_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds the maximum allowed size of {max_upload_size} bytes.",
                    )
                if len(signature) < len(expected_signature):
                    signature += chunk[: len(expected_signature) - len(signature)]
                if len(signature) == len(expected_signature) and not signature.startswith(expected_signature):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Uploaded file does not have a valid {extension} file signature.",
                    )
                temp_handle.write(chunk)

        if len(signature) < len(expected_signature) or not signature.startswith(expected_signature):
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file does not have a valid {extension} file signature.",
            )

        # Load and parse Excel
        try:
            df = load_dispatch_excel(str(temp_file), source_id=file.filename or temp_file.name)
            if df.empty:
                raise HTTPException(status_code=400, detail="Uploaded file is empty or has no valid rows")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to load Excel: {str(e)}")

        # Auto-detect columns (address, time, taxi, operation, site, type_course)
        try:
            columns = detect_columns(df)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Could not detect required columns: {str(e)}")

        # Apply optional filters
        df_filtered = filter_dataframe(
            df,
            columns,
            time_value=time_filter or None,
            type_course=type_course_filter or None,
            operation=operation_filter or None,
        )

        if df_filtered.empty:
            raise HTTPException(status_code=400, detail=f"No rows match filters: time={time_filter}, course={type_course_filter}, operation={operation_filter}")

        # Run grouping algorithm (optionally with ML)
        grouped, warnings = group_agents(df_filtered, columns=columns, use_ml=use_ml)

        # Validate the final groups
        validation = validate_dispatch(grouped, taxi_column=TAXI_COLUMN, capacity=MAX_TAXI_CAPACITY)

        # Calculate summary statistics
        stats = {
            "total_agents": len(grouped),
            "total_taxis": int(grouped[TAXI_COLUMN].max()) if TAXI_COLUMN in grouped.columns else 0,
            "unknown_count": int((grouped.get("Zone", pd.Series()) == UNKNOWN_ZONE).sum()),
        }

        # Convert DataFrame to JSON (pandas NaT → None)
        grouped_json = json.loads(grouped.to_json(orient="records", date_format="iso"))

        return {
            "grouped_data": grouped_json,
            "stats": stats,
            "warnings": warnings,
            "validation": {
                "valid": validation["valid"],
                "errors": validation["errors"],
                "warnings": validation["warnings"],
                "taxi_reports": validation["taxi_reports"],
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    finally:
        # Clean up temporary file
        if temp_file and temp_file.exists():
            temp_file.unlink()


@app.post("/api/export")
async def export_grouped_data(
    grouped_data: list[dict],
):
    """
    Export grouped data to a formatted Excel file.

    **Workflow:**
    1. Reconstruct DataFrame from JSON request body
    2. Pass to exporter.export_excel() which handles:
       - Sorting by taxi and original order
       - Color coding taxis and unknown addresses
       - Merging taxi numbers vertically
       - Adding validation summary sheet
    3. Return as binary Excel file attachment

    **Accepts:**
    - grouped_data: array of records (the 'grouped_data' field from /api/group response)

    **Returns:**
    - Binary Excel file with professional formatting
    """
    temp_file = None
    try:
        if not grouped_data:
            raise HTTPException(status_code=400, detail="grouped_data array is empty")

        # Reconstruct DataFrame from JSON
        df = pd.DataFrame(grouped_data)

        if df.empty:
            raise HTTPException(status_code=400, detail="Could not construct DataFrame from grouped_data")

        # Generate Excel file in temporary location
        temp_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        temp_file = Path(temp_handle.name)
        temp_handle.close()

        export_excel(df, str(temp_file), taxi_column=TAXI_COLUMN)

        # Read file and return as streaming response with attachment header
        excel_bytes = temp_file.read_bytes()

        return StreamingResponse(
            iter([excel_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=grouped_output.xlsx"},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export error: {str(e)}")

    finally:
        # Clean up temporary file
        if temp_file and temp_file.exists():
            temp_file.unlink()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=get_api_host(), port=8000)
