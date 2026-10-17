#!/usr/bin/env python3
"""Test training capture with detailed step tracking"""

import sys
import requests
import json
from api_test_support import api_auth_headers

sheet_id = "1O5K9a7d5l4KI11ntGzypTqD5cji6ny3RwThPM0S9wvI"
base_url = "http://127.0.0.1:8002"
api_headers = api_auth_headers()

def print_header(text):
    print("\n" + "="*70)
    print(text)
    print("="*70)

try:
    # Check cache before grouping
    print_header("STEP 1: Check cache BEFORE grouping")
    cache_r = requests.get(f"{base_url}/api/debug/training-cache", headers=api_headers)
    cache_before = cache_r.json()['pre_correction_cache_size']
    print(f"Cache size: {cache_before}")
    
    # Call group-sheet
    print_header("STEP 2: Call /api/group-sheet")
    group_r = requests.post(
        f"{base_url}/api/group-sheet",
        json={
            "sheet_id": sheet_id,
            "time_filter": None,
            "type_course_filter": None,
            "operation_filter": None,
            "use_ml": True
        },
        headers=api_headers,
        timeout=60
    )
    
    print(f"Status: {group_r.status_code}")
    if group_r.status_code == 200:
        group_data = group_r.json()
        print(f"OK - Grouped {len(group_data.get('grouped_data', []))} agents")
    else:
        print(f"ERROR: {group_r.text[:200]}")
        sys.exit(1)
    
    # Check cache after grouping
    print_header("STEP 3: Check cache AFTER grouping")
    cache_r2 = requests.get(f"{base_url}/api/debug/training-cache", headers=api_headers)
    cache_after_group = cache_r2.json()['pre_correction_cache_size']
    print(f"Cache size: {cache_after_group}")
    print(f"Result: {'SUCCESS - cache populated' if cache_after_group > 0 else 'FAIL - cache empty'}")
    
    # Call validate-sheet
    print_header("STEP 4: Call /api/validate-sheet")
    val_r = requests.post(
        f"{base_url}/api/validate-sheet",
        json={"sheet_id": sheet_id},
        headers=api_headers,
        timeout=60
    )
    
    print(f"Status: {val_r.status_code}")
    if val_r.status_code == 200:
        val_data = val_r.json()
        training = val_data.get('training', {})
        print(f"Validation valid: {val_data['validation']['valid']}")
        print(f"Training success: {training.get('success')}")
        print(f"Training rows_changed: {training.get('rows_changed')}")
        print(f"Training error: {training.get('error', 'None')}")
    else:
        print(f"ERROR: {val_r.text[:200]}")
        sys.exit(1)
    
    # Check cache after validation
    print_header("STEP 5: Check cache AFTER validation")
    cache_r3 = requests.get(f"{base_url}/api/debug/training-cache", headers=api_headers)
    cache_after_val = cache_r3.json()['pre_correction_cache_size']
    print(f"Cache size: {cache_after_val}")
    
    print_header("FINAL SUMMARY")
    print(f"Cache before grouping: {cache_before}")
    print(f"Cache after grouping:  {cache_after_group}")
    print(f"Cache after validation: {cache_after_val}")
    print(f"\nTraining extraction success: {training.get('success')}")
    if not training.get('success'):
        print(f"Training extraction error: {training.get('error')}")
    else:
        print(f"Training rows changed: {training.get('rows_changed')}")
        
except Exception as e:
    print(f"\nEXCEPTION: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
