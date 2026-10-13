"""Legacy compatibility wrapper for the Taxi Grouper API.

The real API implementation now lives in src/api/service.py.
"""

from src.api.service import app


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
    temp_file = None
    try:
        # Write uploaded file to temporary location (load_dispatch_excel requires a file path)
        temp_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        temp_file = Path(temp_handle.name)
        content = await file.read()
        temp_handle.write(content)
        temp_handle.close()

        # Load and parse Excel
        try:
            df = load_dispatch_excel(str(temp_file))
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

    uvicorn.run(app, host="0.0.0.0", port=8000)
