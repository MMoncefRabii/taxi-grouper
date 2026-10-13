# Taxi Grouper API Usage

This document describes the backend API contract for the Taxi Grouper application.
It is intended for frontend builders, automation scripts, or any integration that needs to interact with the backend directly.

## Overview

The backend exposes the following API routes:

- `GET /health`
- `GET /api/auth/login-url`
- `GET /api/auth/status`
- `GET /api/auth/token`
- `POST /api/auth/logout`
- `GET /auth/callback`
- `POST /api/sheet-info`
- `POST /api/group-sheet`
- `POST /api/validate-sheet`
- `POST /api/save-drive`
- `POST /api/group`
- `POST /api/export`

## Authentication and Google OAuth

### `GET /api/auth/login-url`

Returns a Google OAuth login URL for the current backend instance.

Request: none

Response:

```json
{ "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..." }
```

### `GET /api/auth/status`

Returns whether the current user is signed in with Google OAuth.

Request: none

Response:

```json
{ "signed_in": true }
```

### `GET /api/auth/token`

Returns a fresh access token for the signed-in user.

Request: none

Response:

```json
{
  "access_token": "ya29...",
  "expires_at": "2026-07-12T12:34:56..."
}
```

### `POST /api/auth/logout`

Clears the stored Google OAuth session.

Request: none

Response:

```json
{ "success": true }
```

### `GET /auth/callback`

OAuth redirect callback URL.

Used by Google during the OAuth flow. The endpoint redirects back to the frontend with `auth=success` or `auth=error`.

Query params:
- `code` for successful OAuth exchange
- `error` for failed OAuth

Response: redirect to frontend URL.

## Google Sheet Integration

### `POST /api/sheet-info`

Loads sheet metadata and available filter values for a connected Google Sheet.

If the selected Drive file is an Office file (e.g. `.xlsx`) rather than a native Google Sheet, the backend will automatically convert it to a native Google Sheet copy and return the converted sheet ID and URL.

Request body:

```json
{ "sheet_id": "<google-sheet-id>" }
```

Response:

```json
{
  "sheet_id": "<google-sheet-id>",
  "sheet_title": "My Sheet",
  "sheet_url": "https://docs.google.com/spreadsheets/d/.../edit",
  "available_times": ["07:00", "08:00"],
  "available_operations": ["Client A", "Client B"],
  "converted_from_office_file": false,
  "converted_sheet_url": null
}
```

### `POST /api/group-sheet`

Groups agents from an existing Google Sheet and writes results back to that sheet.

Request body:

```json
{
  "sheet_id": "<google-sheet-id>",
  "time_filter": "07:00",
  "type_course_filter": "Ramassage",
  "operation_filter": "Client A",
  "use_ml": true
}
```

Response:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/.../edit",
  "grouped_data": [ ... ],
  "stats": { "total_agents": 25, "total_taxis": 7, "unknown_count": 0 },
  "warnings": [],
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": [],
    "taxi_reports": []
  },
  "converted_from_office_file": false,
  "converted_sheet_url": null
}
```

### `POST /api/validate-sheet`

Validates the current client-facing results sheet after manual corrections.
It also extracts correction training examples and may schedule retraining.

Request body:

```json
{ "sheet_id": "<google-sheet-id>" }
```

Response:

```json
{
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": [],
    "taxi_reports": []
  },
  "training": {
    "success": true,
    "rows_changed": 3,
    "stats": { ... },
    "error": null,
    "retrain_scheduled": false
  },
  "converted_from_office_file": false,
  "converted_sheet_url": null
}
```

### `POST /api/save-drive`

Saves grouped JSON results as a new Google Sheet in Drive.

Request body:

```json
{
  "grouped_data": [ ... ],
  "sheet_name": "Taxi Grouper Results"
}
```

Response:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/.../edit",
  "sheet_id": "<new-sheet-id>"
}
```

## Local Excel Upload

### `POST /api/group`

Groups agents from a locally uploaded Excel file.

Request:
- multipart form data
- `file`: Excel file upload
- optional query params: `time_filter`, `type_course_filter`, `operation_filter`, `use_ml`

Response:

```json
{
  "grouped_data": [ ... ],
  "stats": { ... },
  "warnings": [],
  "validation": { ... }
}
```

## Exporting Results

### `POST /api/export`

Exports grouped data to a formatted Excel file.

Request body:

```json
{ "grouped_data": [ ... ] }
```

Response:
- binary Excel file attachment
- content type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

## Notes for integrators

- `sheet_id` is the key identifier for Google Sheet workflows.
- If the selected Drive file is an Office document, the backend will automatically convert it to a native Google Sheet and return the converted sheet URL.
- `grouped_data` must be the array returned by `/api/group-sheet` or `/api/group`.
- The backend performs grouping, validation, and export formatting.
- The frontend only implements the UI and Google Picker/orchestration logic.

## Minimal integration flow

1. `GET /api/auth/login-url` → open OAuth URL
2. complete Google OAuth via `/auth/callback`
3. `GET /api/auth/token` → get active access token
4. `POST /api/sheet-info` → load sheet metadata
5. `POST /api/group-sheet` → group into sheet
6. `POST /api/validate-sheet` → validate corrected results
7. `POST /api/export` → download Excel export
8. `POST /api/save-drive` → save to a new Drive sheet
