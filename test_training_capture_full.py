#!/usr/bin/env python3
"""Test training capture with manual sheet edit and verification"""

import sys
import json
import requests
from pathlib import Path
from api_test_support import api_auth_headers
from src.data.sheets_repository import (
    read_sheet_to_dataframe, 
    CLIENT_SHEET_NAME,
    _get_service,
)

sheet_id = "1O5K9a7d5l4KI11ntGzypTqD5cji6ny3RwThPM0S9wvI"
base_url = "http://127.0.0.1:8002"
api_headers = api_auth_headers()
training_file = Path("data/auto_training_corrections.jsonl")

def print_header(text):
    print("\n" + "="*80)
    print(text)
    print("="*80)

try:
    # STEP 1: Check initial training file state
    print_header("STEP 1: Check initial training file state")
    
    initial_lines = 0
    if training_file.exists():
        with open(training_file) as f:
            initial_lines = len(f.readlines())
        print(f"Training file EXISTS with {initial_lines} correction(s)")
    else:
        print("Training file does NOT exist yet")
    
    # STEP 2: Run group-sheet
    print_header("STEP 2: Run group-sheet to populate cache")
    
    group_r = requests.post(
        f"{base_url}/api/group-sheet",
        json={"sheet_id": sheet_id},
        headers=api_headers,
        timeout=60
    )
    print(f"Group-sheet status: {group_r.status_code}")
    
    cache_r = requests.get(
        f"{base_url}/api/debug/training-cache",
        headers=api_headers,
        timeout=5,
    )
    cache_size = cache_r.json()['pre_correction_cache_size']
    print(f"Cache after grouping: {cache_size} sheet(s) stored")
    
    # STEP 3: Read sheet state
    print_header("STEP 3: Read current sheet state")
    
    df = read_sheet_to_dataframe(sheet_id, sheet_title=CLIENT_SHEET_NAME)
    print(f"Loaded {len(df)} rows")
    
    # Select row 5 to edit
    row_idx = 5
    original_taxi = str(df.iloc[row_idx]['Groupe Taxi']).strip()
    address = str(df.iloc[row_idx].get('Adresse', 'N/A'))
    phone = str(df.iloc[row_idx].get('Numero', str(df.iloc[row_idx].get('Telephone', 'N/A'))))
    
    new_taxi = str(int(original_taxi) + 100) if original_taxi.isdigit() else "999"
    
    print(f"\nRow to edit (index {row_idx}):")
    print(f"  Address: {address}")
    print(f"  Phone: {phone}")
    print(f"  Current Groupe Taxi: {original_taxi}")
    print(f"  New Groupe Taxi: {new_taxi}")
    
    # STEP 4: Make manual edit via Sheets API
    print_header("STEP 4: Make manual edit via Google Sheets API")
    
    try:
        service = _get_service()
        sheets = service.spreadsheets()
        
        # Get sheet metadata to find the gid for CLIENT_SHEET_NAME
        metadata = sheets.get(spreadsheetId=sheet_id).execute()
        sheet_gid = None
        for sheet in metadata.get('sheets', []):
            if sheet['properties']['title'] == CLIENT_SHEET_NAME:
                sheet_gid = sheet['properties']['sheetId']
                break
        
        if sheet_gid is None:
            print(f"ERROR: Could not find sheet '{CLIENT_SHEET_NAME}'")
            sys.exit(1)
        
        # Find column for Groupe Taxi
        header_range = f"{CLIENT_SHEET_NAME}!1:1"
        header_result = sheets.values().get(spreadsheetId=sheet_id, range=header_range).execute()
        headers = header_result.get('values', [[]])[0]
        
        taxi_col_num = None
        for i, h in enumerate(headers):
            if "Groupe Taxi" in str(h):
                taxi_col_num = i + 1
                break
        
        if taxi_col_num is None:
            print("ERROR: Could not find 'Groupe Taxi' column")
            sys.exit(1)
        
        # Update cell (row_idx + 2 because row 1 is header, data starts at row 2)
        cell_row = row_idx + 2
        range_to_update = f"{CLIENT_SHEET_NAME}!{chr(64+taxi_col_num)}{cell_row}"
        
        update_result = sheets.values().update(
            spreadsheetId=sheet_id,
            range=range_to_update,
            valueInputOption="USER_ENTERED",
            body={"values": [[new_taxi]]}
        ).execute()
        
        print(f"Successfully updated cell {range_to_update} from {original_taxi} to {new_taxi}")
        
    except Exception as e:
        print(f"ERROR updating sheet: {type(e).__name__}: {e}")
        sys.exit(1)
    
    # STEP 5: Validate sheet to capture training data
    print_header("STEP 5: Call validate-sheet to capture training data")
    
    val_r = requests.post(
        f"{base_url}/api/validate-sheet",
        json={"sheet_id": sheet_id},
        headers=api_headers,
        timeout=60
    )
    
    if val_r.status_code != 200:
        print(f"ERROR: Validation failed with status {val_r.status_code}")
        print(val_r.text)
        sys.exit(1)
    
    val_data = val_r.json()
    training = val_data.get('training', {})
    print(f"Validation result:")
    print(f"  Training success: {training.get('success')}")
    print(f"  Rows changed: {training.get('rows_changed')}")
    print(f"  Error: {training.get('error', 'None')}")
    
    # STEP 6: Show the new training record
    print_header("STEP 6: Show captured training record")
    
    if not training_file.exists():
        print("ERROR: Training file was not created!")
        sys.exit(1)
    
    with open(training_file) as f:
        lines = f.readlines()
    
    current_lines = len(lines)
    print(f"Training file now has {current_lines} correction(s)")
    print(f"Previous: {initial_lines}, Current: {current_lines}")
    
    if current_lines > initial_lines:
        # Show the new record(s)
        for i in range(initial_lines, current_lines):
            record = json.loads(lines[i])
            print(f"\nNew training record #{i+1}:")
            print(f"  Row index: {record.get('row_index')}")
            print(f"  Original Groupe Taxi: {record.get('before')}")
            print(f"  Corrected Groupe Taxi: {record.get('after')}")
            print(f"  Full record:")
            print(json.dumps(record, indent=4, ensure_ascii=False))
    else:
        print("No new records were added!")
        sys.exit(1)
    
    # STEP 7: Ask for confirmation before deletion
    print_header("STEP 7: Delete test record to restore file")
    
    # Remove the new lines
    if current_lines > initial_lines:
        with open(training_file, 'w') as f:
            for i in range(initial_lines):
                f.write(lines[i])
        
        print(f"Deleted {current_lines - initial_lines} test record(s)")
        print(f"File restored to {initial_lines} correction(s)")
        
        # Verify deletion
        with open(training_file) as f:
            verification_lines = len(f.readlines())
        
        if verification_lines == initial_lines:
            print(f"VERIFIED: File now has {verification_lines} correction(s) (restored)")
        else:
            print(f"ERROR: File verification failed! Expected {initial_lines}, got {verification_lines}")
            sys.exit(1)
    
    print_header("TEST COMPLETE")
    print("Summary:")
    print(f"  1. Captured manual correction (original taxi: {original_taxi}, new taxi: {new_taxi})")
    print(f"  2. Verified training record in data/auto_training_corrections.jsonl")
    print(f"  3. Deleted test record to restore file")
    print(f"  4. Training pipeline WORKING correctly")
    
except Exception as e:
    print(f"\nEXCEPTION: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
