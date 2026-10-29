# Taxi Grouper API Usage

This document describes the backend API contract for the Taxi Grouper application.
It is intended for service-to-service callers such as Fleet Tracker and for local test/debug scripts.

The React/Vite frontend in `frontend/` is unsupported and will receive HTTP
401 on protected routes. Do not relaunch it; the folder remains only as a
reference for the later Fleet Tracker Sheets/Picker port.

## Authentication

All application routes require the API key except `GET /health`, `GET /ready`,
and `GET /auth/callback`. CORS `OPTIONS` preflight
requests also pass without authentication; they do not invoke protected route
handlers. OAuth status, token, and logout routes are protected too. Send the
key as a bearer credential:

```http
Authorization: Bearer <TAXI_GROUPER_API_KEY>
```

Configure `TAXI_GROUPER_API_KEY` only in the API process environment. Use a
random value of at least 32 characters; for example, generate one with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Never include
the key in code, browser bundles, URLs, or logs. When the server key is missing
or too short, protected routes fail closed with HTTP 503. Missing or invalid
caller credentials receive a generic HTTP 401 response.

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
- `POST /api/debug/set-correction` (only when `DEBUG=1`, and still requires the API key)
- `GET /api/debug/training-cache` (only when `DEBUG=1`, and still requires the API key)

## Authentication and Google OAuth

### `GET /api/auth/login-url`

Returns a Google OAuth login URL for the current backend instance.

Requires the API key. Make this request from a trusted operator or service
caller; do not put the API key in browser code or a URL.

```http
GET /api/auth/login-url
Authorization: Bearer <key>
```

Response:

```json
{ "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..." }
```

### `GET /api/auth/status`

Returns whether the current user is signed in with Google OAuth.
Requires the API key.

Request: none

Response:

```json
{ "signed_in": true }
```

### `GET /api/auth/token`

Returns a fresh access token for the signed-in user.
Requires the API key. The React frontend is unsupported; only a trusted service
caller should use this endpoint while the legacy Picker flow remains.

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
Requires the API key.

Request: none

Response:

```json
{ "success": true }
```

### `GET /auth/callback`

OAuth redirect callback URL.

Used by Google during the OAuth flow. This temporary handshake endpoint is
unauthenticated and redirects back to the configured frontend URL with
`auth=success` or `auth=error`. It accepts only a valid, unexpired, unused
OAuth state issued by the authenticated login-url endpoint.

Query params:
- `code` for successful OAuth exchange
- `error` for failed OAuth

Response: redirect to frontend URL.

## Google Sheet Integration

All business routes in this section require the bearer API key.

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

Reads and groups the selected source spreadsheet, then writes client-facing and
internal results to two separate spreadsheets in the configured output folder.
Neither the source nor an Office-converted input copy is used as an output.
Set `GOOGLE_OUTPUT_FOLDER_ID` to a writable folder ID; there is no default to
the source's parent. The app does not automatically share either output.

Request body:

```json
{
  "sheet_id": "<google-sheet-id>",
  "time_filter": "07:00",
  "type_course_filter": "Ramassage",
  "operation_filter": "Client A",
  "use_ml": true,
  "client_sheet_id": null,
  "internal_sheet_id": null,
  "overwrite_output": false
}
```

Each run creates new output spreadsheets by default. To overwrite, provide both
existing output IDs and set `overwrite_output` to `true`; the IDs must be
distinct, must not match the source or converted input, and each target must
contain only its expected output tab. Files are never matched or reused by
title.

Response:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/<client-id>/edit#gid=...",
  "sheet_id": "<client-output-id>",
  "client_sheet_url": "https://docs.google.com/spreadsheets/d/<client-id>/edit#gid=...",
  "internal_sheet_url": "https://docs.google.com/spreadsheets/d/<internal-id>/edit#gid=...",
  "client_sheet_id": "<client-output-id>",
  "internal_sheet_id": "<internal-output-id>",
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

`sheet_url` and `sheet_id` remain compatibility aliases for the client output.
Use `sheet_id` from the grouping request as the source for future grouping runs.
Use `client_sheet_id` as the `sheet_id` when validating manual corrections;
the internal spreadsheet is not the correction-validation input.

The client spreadsheet contains one `Taxi Grouper Client Output` tab with only
the approved client columns. The separate internal spreadsheet contains one
`Taxi Grouper Internal` tab with all grouped-data columns.

### `POST /api/validate-sheet`

Validates the client output spreadsheet after manual corrections. Pass
`client_sheet_id` from `/api/group-sheet` as `sheet_id`; the original source ID
is not the correction-validation target.
It also extracts correction training examples and may schedule candidate
retraining. Automatic retraining does not replace the active model; promoting a
candidate requires the separately documented human-approved promotion command.

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

Saves grouped JSON results as distinct client and internal spreadsheets in the
configured output folder. It follows the same no-overwrite-by-default policy as
`/api/group-sheet`; explicit overwrite requires both output IDs and
`overwrite_output: true`.

Request body:

```json
{
  "grouped_data": [ ... ],
  "sheet_name": "Taxi Grouper Results",
  "client_sheet_id": null,
  "internal_sheet_id": null,
  "overwrite_output": false
}
```

Response:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/<client-id>/edit#gid=...",
  "sheet_id": "<client-output-id>",
  "client_sheet_url": "https://docs.google.com/spreadsheets/d/<client-id>/edit#gid=...",
  "internal_sheet_url": "https://docs.google.com/spreadsheets/d/<internal-id>/edit#gid=...",
  "client_sheet_id": "<client-output-id>",
  "internal_sheet_id": "<internal-output-id>"
}
```

## Local Excel Upload

### `POST /api/group`

Groups agents from a locally uploaded Excel file.

Request:
- multipart form data
- `file`: Excel file upload
- optional query params: `time_filter`, `type_course_filter`, `operation_filter`, `use_ml`
- `.xlsx`, `.xls`, and `.ods` files are supported and checked for a matching file signature.
- Maximum workbook size: 10 MiB by default. Configure `MAX_UPLOAD_SIZE_BYTES` to change it.
- Oversized uploads return HTTP 413; unsupported extensions return HTTP 415.

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
- Do not embed the service API key in browser code. Fleet Tracker must call protected routes server-to-server.

## Minimal integration flow

1. `GET /api/auth/login-url` with the bearer API key → open OAuth URL
2. complete Google OAuth via `/auth/callback`
3. `GET /api/auth/token` → get active access token (send API key; temporary Picker support)
4. `POST /api/sheet-info` → load sheet metadata (send API key)
5. `POST /api/group-sheet` → group into sheet (send API key)
6. `POST /api/validate-sheet` → validate corrected results (send API key)
7. `POST /api/export` → download Excel export (send API key)
8. `POST /api/save-drive` → save to a new Drive sheet (send API key)
