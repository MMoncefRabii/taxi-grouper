# Google Picker Debugging Guide

> **Legacy reference only:** The React/Vite frontend is unsupported, is not to
> be relaunched, and receives HTTP 401 on protected API routes. This guide
> describes its retired Picker flow; the `frontend/` folder is retained only
> as a reference for the later Fleet Tracker port. Do not follow the frontend
> debugging instructions below.

## Overview
This guide helps diagnose issues with the Google Picker integration in Taxi Grouper's frontend. The Picker is used to select and upload Google Sheets.

## Architecture Flow

```
Frontend (React)
    ↓
handleOpenPicker() [App.jsx:201]
    ↓
Fetch /api/auth/token (Backend)
    ↓
Backend → get_oauth_access_token() [sheets_repository.py:245]
    ↓
Returns: {"access_token": "...", "expires_at": "..."}
    ↓
Frontend setOAuthToken(tokenData.access_token) [App.jsx:217]
    ↓
Google Picker opens
```

## Current Picker Code Location

**File:** [frontend/src/App.jsx](frontend/src/App.jsx#L201-L245)

Key parts:
- **Token fetch:** Line 208 - `fetch(`${BACKEND_URL}/api/auth/token`)`
- **Token setter:** Line 217 - `.setOAuthToken(tokenData.access_token)`
- **Developer key:** Line 218 - `.setDeveloperKey(GOOGLE_API_KEY)`

## Debugging Steps

### Step 1: Verify Backend Configuration
Check that Google OAuth credentials are properly configured:

```bash
# Check if OAuth tokens are stored
python -c "from src.data.sheets_repository import get_credentials; creds = get_credentials(); print('Credentials valid:', creds is not None and creds.valid)"
```

### Step 2: Test Token Endpoint Manually

```bash
# Terminal 1: Start backend
python api.py

# Terminal 2: Test the token endpoint
curl http://localhost:8000/api/auth/token
```

Expected response:
```json
{
  "access_token": "ya29.a0AfH6SMBx...",
  "expires_at": "2024-01-15T14:30:00"
}
```

Possible errors:
- **401 Unauthorized:** User is not signed in. Need to authenticate first.
- **500 Error:** Check backend logs for OAuth configuration issues.

### Step 3: Enable Frontend Debugging

Add this code temporarily to [frontend/src/App.jsx](frontend/src/App.jsx#L201) in the `handleOpenPicker()` function to log token data:

```javascript
const handleOpenPicker = async () => {
  setError('');
  setPickerLoading(true);
  try {
    if (!GOOGLE_API_KEY) {
      throw new Error('Please configure VITE_GOOGLE_API_KEY in your frontend environment.');
    }
    
    // TOKEN DEBUGGING - ADD THESE LOGS
    const tokenResponse = await fetch(`${BACKEND_URL}/api/auth/token`);
    console.log('Token response status:', tokenResponse.status);
    
    if (!tokenResponse.ok) {
      const text = await tokenResponse.text();
      console.error('Token response error body:', text);
      throw new Error('Google OAuth session is not available. Please sign in with Google first.');
    }
    
    const tokenData = await tokenResponse.json();
    console.log('Token data received:', {
      has_access_token: !!tokenData.access_token,
      access_token_length: tokenData.access_token?.length || 0,
      access_token_preview: tokenData.access_token?.substring(0, 20) + '...',
      expires_at: tokenData.expires_at,
      full_token_data_keys: Object.keys(tokenData)
    });
    console.log('API Key status:', {
      has_api_key: !!GOOGLE_API_KEY,
      api_key_length: GOOGLE_API_KEY?.length || 0,
      api_key_preview: GOOGLE_API_KEY?.substring(0, 20) + '...'
    });
    
    // ... rest of the function
```

### Step 4: Check Browser Console

Open Browser DevTools (F12) and go to the **Console** tab. Look for:

1. **Token data logs** - Should show:
   - `has_access_token: true`
   - `access_token_length: > 100` (typically 200+ characters)
   - `expires_at: valid timestamp`

2. **API Key logs** - Should show:
   - `has_api_key: true`
   - `api_key_length: > 30` (typically 40+ characters)

3. **Network tab** - Check the `/api/auth/token` request:
   - Status: 200
   - Response body shows `access_token` and `expires_at`

### Step 5: Check Network Requests

In Browser DevTools → **Network** tab:

1. Find the `/api/auth/token` request
2. Check:
   - **Status:** Should be 200
   - **Response Preview:** Should show valid JSON with `access_token`
   - **Headers:** Check cookies are being sent if using session-based auth

### Step 6: Verify Google API Configuration

Check [frontend/.env.local](frontend/.env.local) or environment variables:

```bash
# Should be set
echo $VITE_GOOGLE_API_KEY
echo $VITE_BACKEND_URL
```

The keys should be:
- `VITE_GOOGLE_API_KEY` - Your Google API key with Picker API enabled
- `VITE_BACKEND_URL` - Backend URL (e.g., `http://localhost:8000`)

### Step 7: Test Picker Script Loading

Check in Browser Console if the Picker script loads properly:

```javascript
// Run in browser console
console.log('google.picker available:', !!window.google?.picker);
console.log('gapi available:', !!window.gapi);
```

Should both be `true` after picker loads.

### Step 8: Check Google Cloud Console

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. Verify:
   - **APIs enabled:** Google Picker API, Google Drive API, Google Sheets API
   - **OAuth credentials:** Web application with correct Authorized JS origins and redirect URIs
   - **Key restrictions:** API key has no IP/domain restrictions (or matches your environment)

## Common Issues & Solutions

### Issue 1: "Google OAuth session is not available"
**Cause:** User session is not authenticated or token expired.
**Solution:**
1. Sign out and sign back in
2. Check if cookies are being stored: `document.cookie`
3. Verify session persistence in backend

### Issue 2: Picker doesn't open but no error shown
**Cause:** Token is null or invalid format.
**Solution:**
1. Add logs from Step 3
2. Check if `setOAuthToken()` is receiving valid token
3. Verify `VITE_GOOGLE_API_KEY` is set correctly

### Issue 3: "setOAuthToken is not a function"
**Cause:** Google Picker script didn't load.
**Solution:**
1. Verify `VITE_GOOGLE_API_KEY` is set
2. Check for CORS issues in Network tab
3. Retry script loading logic

### Issue 4: Picker shows but can't select sheets
**Cause:** OAuth token lacks Google Drive/Sheets permissions.
**Solution:**
1. Delete OAuth token from backend storage
2. Sign in again to re-authorize with full scopes
3. Check [src/data/sheets_repository.py](src/data/sheets_repository.py) for required scopes

### Issue 5: "Invalid grant" error in backend logs
**Cause:** Refresh token expired or revoked.
**Solution:**
1. Delete stored credentials: `rm src/data/google_oauth_tokens.json` (if using file storage)
2. Sign out and sign back in
3. Check backend logs for detailed error

## Key Files Reference

| File | Purpose |
|------|---------|
| [frontend/src/App.jsx](frontend/src/App.jsx#L201) | Picker UI and token handling |
| [src/api/service.py](src/api/service.py#L135) | Backend `/api/auth/token` endpoint |
| [src/data/sheets_repository.py](src/data/sheets_repository.py#L245) | `get_oauth_access_token()` function |
| [frontend/.env.local](frontend/.env.local) | Frontend environment config |

## Advanced Debugging

### Enable Backend Logging

Add to backend code temporarily:

```python
@app.get("/api/auth/token")
async def auth_token():
    """Return a fresh OAuth access token for the current signed-in user."""
    token_info = get_oauth_access_token()
    print(f"[DEBUG] Token info: {token_info}")
    if not token_info:
        raise HTTPException(status_code=401, detail="Google OAuth is not configured or the user is not signed in.")
    return token_info
```

### Picker Callback Debugging

Add logging to picker callback in [frontend/src/App.jsx](frontend/src/App.jsx#L220):

```javascript
.setCallback((data) => {
  console.log('Picker callback data:', data);
  const action = data.action;
  console.log('Picker action:', action);
  // ... rest of callback
})
```

## Troubleshooting Checklist

- [ ] Backend running and accessible (`http://localhost:8000`)
- [ ] User is signed in (check `/api/auth/status` returns `{signed_in: true}`)
- [ ] `VITE_GOOGLE_API_KEY` is set in frontend env
- [ ] `VITE_BACKEND_URL` matches backend URL
- [ ] Google Picker API enabled in Cloud Console
- [ ] OAuth scopes include `drive` and `sheets`
- [ ] Browser console shows no errors
- [ ] Token endpoint returns 200 with valid access_token
- [ ] Network tab shows successful script loading
- [ ] `window.google.picker` is available in console

## Next Steps

Once you've identified the issue using these steps, provide:

1. **Error message** from browser or backend logs
2. **Token endpoint response** (with sensitive data redacted)
3. **Network tab screenshots** showing request/response
4. **Browser console logs** with the debugging additions

This will help quickly identify the root cause and implement a fix.
