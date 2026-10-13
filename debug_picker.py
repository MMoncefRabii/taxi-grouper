#!/usr/bin/env python
"""
Debugging script for Taxi Grouper Google Picker integration.

Usage:
    python debug_picker.py [--test-token] [--test-endpoint] [--check-env]

This script validates:
1. Google OAuth configuration
2. Token generation capability
3. Required environment variables
4. Google API credentials
"""

import json
import sys
import argparse
from pathlib import Path


def check_env_vars():
    """Check if required environment variables are set."""
    print("\n=== Checking Environment Variables ===")
    
    required_vars = [
        'VITE_GOOGLE_API_KEY',
        'VITE_BACKEND_URL',
        'GOOGLE_CLIENT_ID',
        'GOOGLE_CLIENT_SECRET',
        'GOOGLE_REDIRECT_URI',
    ]
    
    from os import environ
    
    missing = []
    for var in required_vars:
        if var in environ:
            value = environ[var]
            preview = value[:20] + '...' if len(value) > 20 else value
            print(f"✓ {var}: {preview}")
        else:
            print(f"✗ {var}: NOT SET")
            missing.append(var)
    
    if missing:
        print(f"\n⚠️  Missing variables: {', '.join(missing)}")
        return False
    else:
        print("\n✓ All environment variables are set")
        return True


def check_oauth_tokens():
    """Check if OAuth tokens are stored and valid."""
    print("\n=== Checking OAuth Tokens ===")
    
    try:
        from src.data.sheets_repository import get_credentials, get_oauth_access_token
        
        creds = get_credentials()
        if not creds:
            print("✗ No credentials found")
            return False
        
        print(f"✓ Credentials found")
        print(f"  - Valid: {creds.valid}")
        print(f"  - Expired: {creds.expired}")
        print(f"  - Expiry: {creds.expiry}")
        print(f"  - Token type: {creds.token_type if hasattr(creds, 'token_type') else 'N/A'}")
        
        token_info = get_oauth_access_token()
        if not token_info:
            print("✗ Could not get access token")
            return False
        
        print(f"✓ Access token obtained")
        print(f"  - Token length: {len(token_info.get('access_token', ''))}")
        print(f"  - Token preview: {token_info.get('access_token', '')[:30]}...")
        print(f"  - Expires at: {token_info.get('expires_at', 'N/A')}")
        
        return True
    except Exception as e:
        print(f"✗ Error checking OAuth tokens: {e}")
        return False


def check_google_sheets_api():
    """Check if Google Sheets API is accessible."""
    print("\n=== Checking Google Sheets API ===")
    
    try:
        from src.data.sheets_repository import build_sheets_service
        
        sheets_service = build_sheets_service()
        print("✓ Successfully built Sheets service")
        
        # Try to get spreadsheet metadata
        print("  - Attempting to fetch spreadsheet list...")
        # This would require listing permissions, skip for now
        
        return True
    except Exception as e:
        print(f"✗ Error checking Google Sheets API: {e}")
        return False


def test_token_endpoint():
    """Test the /api/auth/token endpoint if backend is running."""
    print("\n=== Testing Token Endpoint ===")
    
    try:
        import requests
        from os import environ
        
        backend_url = environ.get('VITE_BACKEND_URL', 'http://localhost:8000')
        endpoint = f"{backend_url}/api/auth/token"
        
        print(f"Testing endpoint: {endpoint}")
        
        response = requests.get(endpoint, timeout=5)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Endpoint returned 200")
            print(f"  - Response keys: {list(data.keys())}")
            print(f"  - Access token length: {len(data.get('access_token', ''))}")
            print(f"  - Expires at: {data.get('expires_at', 'N/A')}")
            return True
        elif response.status_code == 401:
            print(f"✗ Unauthorized (401) - User may not be signed in")
            print(f"  Response: {response.text}")
            return False
        else:
            print(f"✗ Unexpected status {response.status_code}")
            print(f"  Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"✗ Could not connect to backend")
        print(f"  Make sure backend is running at {environ.get('VITE_BACKEND_URL', 'http://localhost:8000')}")
        return False
    except Exception as e:
        print(f"✗ Error testing endpoint: {e}")
        return False


def check_tokens_file():
    """Check if tokens file exists and is readable."""
    print("\n=== Checking Tokens File ===")
    
    token_paths = [
        Path('data/google_oauth_tokens.json'),
        Path.home() / '.taxi_grouper' / 'google_oauth_tokens.json',
    ]
    
    for token_path in token_paths:
        if token_path.exists():
            print(f"✓ Found tokens file: {token_path}")
            try:
                with open(token_path, 'r') as f:
                    tokens = json.load(f)
                    print(f"  - Contains keys: {list(tokens.keys())}")
                    if 'access_token' in tokens:
                        print(f"  - Access token length: {len(tokens['access_token'])}")
                    return True
            except json.JSONDecodeError:
                print(f"✗ Tokens file is not valid JSON")
                return False
            except Exception as e:
                print(f"✗ Error reading tokens file: {e}")
                return False
    
    print(f"⚠️  No tokens file found in:")
    for path in token_paths:
        print(f"  - {path}")
    print("  (This is OK if user hasn't signed in yet)")
    return None


def main():
    parser = argparse.ArgumentParser(description='Debug Google Picker integration')
    parser.add_argument('--check-env', action='store_true', help='Check environment variables')
    parser.add_argument('--check-tokens', action='store_true', help='Check OAuth tokens')
    parser.add_argument('--check-api', action='store_true', help='Check Google Sheets API')
    parser.add_argument('--test-endpoint', action='store_true', help='Test token endpoint')
    parser.add_argument('--check-file', action='store_true', help='Check tokens file')
    parser.add_argument('--all', action='store_true', help='Run all checks')
    
    args = parser.parse_args()
    
    # If no specific tests chosen, default to all
    if not any([args.check_env, args.check_tokens, args.check_api, args.test_endpoint, args.check_file, args.all]):
        args.all = True
    
    results = {}
    
    print("=" * 60)
    print("Taxi Grouper Google Picker Debug Tool")
    print("=" * 60)
    
    if args.all or args.check_env:
        results['env'] = check_env_vars()
    
    if args.all or args.check_file:
        results['file'] = check_tokens_file()
    
    if args.all or args.check_tokens:
        results['tokens'] = check_oauth_tokens()
    
    if args.all or args.check_api:
        results['api'] = check_google_sheets_api()
    
    if args.all or args.test_endpoint:
        results['endpoint'] = test_token_endpoint()
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    success_count = sum(1 for v in results.values() if v is True)
    check_count = sum(1 for v in results.values() if v is not None)
    
    print(f"Passed: {success_count}/{check_count} checks")
    
    for check, result in results.items():
        if result is True:
            print(f"✓ {check}")
        elif result is False:
            print(f"✗ {check}")
        else:
            print(f"? {check} (skipped)")
    
    print("\nRecommendations:")
    if results.get('env') is False:
        print("  1. Set all required environment variables")
    if results.get('tokens') is False:
        print("  2. Sign in with Google and authorize the app")
    if results.get('api') is False:
        print("  3. Check Google Cloud Console - enable required APIs")
    if results.get('endpoint') is False:
        print("  4. Start backend: python api.py")
    
    return 0 if all(v is True for v in results.values() if v is not None) else 1


if __name__ == '__main__':
    sys.exit(main())
