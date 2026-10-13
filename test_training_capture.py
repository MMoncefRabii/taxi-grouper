#!/usr/bin/env python3
"""Test training data capture pipeline end-to-end"""

import requests
import json
from pathlib import Path

sheet_id = "1O5K9a7d5l4KI11ntGzypTqD5cji6ny3RwThPM0S9wvI"
base_url = "http://127.0.0.1:8002"

print("\n" + "="*70)
print("STEP 1: Get initial cache state")
print("="*70)

cache_resp = requests.get(f"{base_url}/api/debug/training-cache")
cache_before = cache_resp.json()['pre_correction_cache_size']
print(f"Cache size before validation: {cache_before}")

print("\n" + "="*70)
print("STEP 2: Call validate-sheet endpoint")
print("="*70)

val_resp = requests.post(
    f"{base_url}/api/validate-sheet",
    json={"sheet_id": sheet_id}
)

if val_resp.status_code == 200:
    val_data = val_resp.json()
    print(f"✓ Validation succeeded (200)")
    print(f"\nValidation result:")
    print(f"  - Valid: {val_data['validation']['valid']}")
    print(f"  - Errors: {val_data['validation']['errors']}")
    print(f"  - Warnings: {val_data['validation']['warnings']}")
    
    print(f"\nTraining capture result:")
    print(f"  - Success: {val_data['training']['success']}")
    print(f"  - Rows changed: {val_data['training']['rows_changed']}")
    print(f"  - Error: {val_data['training'].get('error', 'None')}")
    print(f"  - Stats: {val_data['training'].get('stats', {})}")
else:
    print(f"✗ Validation failed ({val_resp.status_code})")
    print(f"Response: {val_resp.text}")

print("\n" + "="*70)
print("STEP 3: Check for stored training files")
print("="*70)

# Check for training files
training_dir = Path("data/training_files")
if training_dir.exists():
    files = list(training_dir.glob("*"))
    print(f"Training files directory exists: {training_dir}")
    print(f"Files in training directory: {len(files)}")
    for f in sorted(files)[-5:]:  # Show last 5 files
        size = f.stat().st_size
        print(f"  - {f.name} ({size} bytes)")
        
        # If it's recent and contains corrections, show a sample
        if f.suffix in ['.jsonl', '.xlsx']:
            if f.suffix == '.jsonl':
                try:
                    with open(f) as fp:
                        lines = fp.readlines()
                        print(f"    - {len(lines)} lines")
                        if lines:
                            first_line = json.loads(lines[0])
                            print(f"    - Sample: {list(first_line.keys())}")
                except:
                    pass
else:
    print(f"Training files directory not found: {training_dir}")

print("\n" + "="*70)
print("STEP 4: Check cache state after validation")
print("="*70)

cache_resp2 = requests.get(f"{base_url}/api/debug/training-cache")
cache_after = cache_resp2.json()['pre_correction_cache_size']
print(f"Cache size after validation: {cache_after}")
print(f"Cache state: {'✓ Still populated' if cache_after > 0 else '✗ Was cleared'}")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"1. Pre-correction cache was populated: {cache_before > 0}")
print(f"2. Validation endpoint returned: {'success' if val_resp.status_code == 200 else 'error'}")
if val_resp.status_code == 200:
    print(f"3. Training data extraction: {'✓ successful' if val_data['training']['success'] else '✗ failed'}")
    print(f"   Error message: {val_data['training'].get('error', 'None')}")
    print(f"4. Corrections extracted: {val_data['training']['rows_changed']} rows changed")
