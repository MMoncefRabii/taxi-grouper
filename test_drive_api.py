#!/usr/bin/env python
"""
Test Drive API access with the current OAuth token.
This reproduces the exact issue: can we access a file via Drive API
after selecting it through the Picker?
"""
import json
import requests
from pathlib import Path

# Get the token from the backend
print("=" * 70)
print("DRIVE API ACCESS TEST")
print("=" * 70)

# Step 1: Get token from backend
print("\n[1] Fetching OAuth token from backend...")
try:
    token_response = requests.get('http://localhost:8000/api/auth/token', timeout=5)
    if token_response.status_code != 200:
        print(f"✗ Failed to get token: {token_response.status}")
        exit(1)
    
    token_data = token_response.json()
    access_token = token_data.get('access_token')
    print(f"✓ Got access token (length: {len(access_token)})")
    print(f"  Token preview: {access_token[:50]}...")
except Exception as e:
    print(f"✗ Error: {e}")
    exit(1)

# Step 2: Get list of files from Drive API
print("\n[2] Listing files from Google Drive...")
headers = {'Authorization': f'Bearer {access_token}'}

try:
    list_response = requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers=headers,
        params={
            'pageSize': 10,
            'spaces': 'drive',
            'fields': 'files(id, name, mimeType, webViewLink, trashed)',
            'orderBy': 'modifiedTime desc'
        },
        timeout=10
    )
    
    if list_response.status_code != 200:
        print(f"✗ Failed to list files: {list_response.status_code}")
        print(f"  Response: {list_response.text}")
        exit(1)
    
    files_data = list_response.json()
    files = files_data.get('files', [])
    print(f"✓ Listed {len(files)} files from Drive")
    
    if not files:
        print("✗ No files found in Drive")
        exit(1)
    
    print("\nAvailable files:")
    for i, file in enumerate(files[:5]):
        mime = file.get('mimeType', 'unknown')
        is_office = 'office' in mime.lower() or 'ms-word' in mime or 'ms-excel' in mime or 'spreadsheet' in mime.lower()
        office_marker = " [OFFICE FILE]" if is_office else ""
        print(f"  {i+1}. {file['name'][:40]:40} | ID: {file['id'][:20]}... | MIME: {mime:30} {office_marker}")
    
except Exception as e:
    print(f"✗ Error listing files: {e}")
    exit(1)

# Step 3: Test files.get() on several files
print("\n[3] Testing files.get() on each file...")
print("-" * 70)

for i, file in enumerate(files[:3]):
    file_id = file['id']
    file_name = file['name']
    mime_type = file.get('mimeType', 'unknown')
    
    try:
        get_response = requests.get(
            f'https://www.googleapis.com/drive/v3/files/{file_id}',
            headers=headers,
            params={
                'fields': 'id, name, mimeType, webViewLink, trashed, capabilities(canEdit)'
            },
            timeout=10
        )
        
        if get_response.status_code == 200:
            file_info = get_response.json()
            print(f"\n✓ SUCCESS - File {i+1}: '{file_name}'")
            print(f"  ID: {file_id}")
            print(f"  MIME: {mime_type}")
            print(f"  Web link: {file_info.get('webViewLink', 'N/A')}")
            print(f"  Can edit: {file_info.get('capabilities', {}).get('canEdit', 'N/A')}")
        elif get_response.status_code == 404:
            print(f"\n✗ 404 NOT FOUND - File {i+1}: '{file_name}'")
            print(f"  ID: {file_id}")
            print(f"  MIME: {mime_type}")
            print(f"  Response: {get_response.text}")
        else:
            print(f"\n✗ ERROR {get_response.status_code} - File {i+1}: '{file_name}'")
            print(f"  ID: {file_id}")
            print(f"  Response: {get_response.text}")
    
    except Exception as e:
        print(f"\n✗ EXCEPTION - File {i+1}: '{file_name}'")
        print(f"  Error: {e}")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)

# Step 4: Now test with a specific Office file (if the problematic sheet ID is known)
print("\n[4] Testing specific problematic file (1FAuCPcnKgSKo_45efeeLko9oDE4uV-5H)...")
print("-" * 70)

problematic_file_id = '1FAuCPcnKgSKo_45efeeLko9oDE4uV-5H'
try:
    get_response = requests.get(
        f'https://www.googleapis.com/drive/v3/files/{problematic_file_id}',
        headers=headers,
        params={
            'fields': 'id, name, mimeType, webViewLink, trashed'
        },
        timeout=10
    )
    
    print(f"Status code: {get_response.status_code}")
    if get_response.status_code == 200:
        file_info = get_response.json()
        print(f"✓ File is accessible!")
        print(f"  Name: {file_info.get('name')}")
        print(f"  MIME: {file_info.get('mimeType')}")
        print(f"  Trashed: {file_info.get('trashed', False)}")
    else:
        print(f"✗ Status: {get_response.status_code}")
        print(f"Response: {get_response.text[:200]}")
except Exception as e:
    print(f"✗ Error: {e}")

print("\n" + "=" * 70)
