# Taxi Grouper - Grand Tunis

Taxi Grouper is a Python application for grouping company agents into taxis for Tunis transport planning.
It supports Excel dispatch input, address normalization, zone compatibility, optional ML-assisted ordering, and both Streamlit and FastAPI interfaces.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Install](#install)
- [Run the CLI](#run-the-cli)
- [Run the Streamlit app](#run-the-streamlit-app)
- [Run the FastAPI backend](#run-the-fastapi-backend)
- [Training the ML model](#training-the-ml-model)
- [Input data expectations](#input-data-expectations)
- [Output files](#output-files)
- [Run the tests](#run-the-tests)
- [Project structure](#project-structure)
- [Architecture](#architecture)

---

## Prerequisites

1. Windows, macOS, or Linux.
2. Python 3.10+ installed and available as `python`.
3. `pip` available in the selected Python environment.
4. The React/Vite code under `frontend/` is retained only as a reference and is unsupported; do not run it.

---

## Install

Open a terminal at the repository root (`c:\Users\MSI\Desktop\taxi_grouper`) and run:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you want the UI-specific package set instead of the full API stack, use:

```bash
pip install -r requirements-ui.txt
```

> On macOS/Linux use `source .venv/bin/activate` instead of the Windows activate command.


---

## Run the CLI

The main grouping entrypoint is `main.py`.

```bash
python main.py --input <input.xlsx> --output <output.xlsx>
```

Example:

```bash
python main.py --input data/raw/sample_agents.xlsx --output outputs/grouped_output.xlsx --time 07:00
```

Optional arguments:

- `--time <HH:MM>` — filter rows by arrival/departure time
- `--type-course <Ramassage|Retour>` — filter by course type
- `--operation <name>` — filter by client or operation
- `--no-ml` — disable ML-assisted ordering and use rule-based grouping only

The CLI validates grouped output and writes a formatted Excel file plus a validation report.

---

## Run the Streamlit app

The Streamlit user interface is available in `app.py`.

```bash
streamlit run app.py
```

Features:

- upload Excel files (`.xlsx` or `.xls`)
- filter by time, course type, and operation
- run automatic grouping
- preview grouped results interactively
- download grouped Excel output
- save corrected results to `data/corrected/`

The Streamlit app uses shared core grouping logic from `src.core`.

---

## Run the FastAPI backend

The API backend is defined in `src/api/service.py`.

```bash
python api.py
```

The root launcher binds to `127.0.0.1` by default. Set `API_HOST` to an
explicit interface address to bind elsewhere, for example in PowerShell:

```powershell
$env:API_HOST = "192.0.2.10"
python api.py
```

Business, debug, API documentation, and OAuth-management routes require the
<<<<<<< HEAD
`TAXI_GROUPER_API_KEY` server environment variable and an
`Authorization: Bearer <key>` header. `/health`, `/api/auth/login-url`, and
`/auth/callback`; `/ready` is also unauthenticated (CORS
`OPTIONS` preflight requests also pass without authentication). If the server key is
=======
`TAXI_GROUPER_API_KEY` server environment variable and a bearer authorization
header. `/health` and `/auth/callback` are the only unauthenticated application
endpoints (CORS `OPTIONS` preflight requests also pass without authentication). If the server key is
>>>>>>> df20fed (fix(auth): require API key on OAuth login-url)
missing or shorter than 32 characters, protected requests fail closed with
HTTP 503; missing or incorrect caller credentials receive HTTP 401.

Generate a strong key and configure it in the API process environment; do not
put it in source control, the React bundle, or a URL:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:TAXI_GROUPER_API_KEY = "<generated-key>"
python api.py
```

Google sign-in starts at `GET /api/auth/login-url`, which requires the API key.
For example, a trusted operator can request the URL from PowerShell without
putting the key in a URL or browser bundle:

```powershell
Invoke-RestMethod -Headers @{ Authorization = "Bearer $env:TAXI_GROUPER_API_KEY" } `
  -Uri "http://127.0.0.1:8000/api/auth/login-url"
```

Open the returned `auth_url` in a browser. Google redirects to the unauthenticated
`/auth/callback`; that endpoint validates the one-time OAuth state before saving
tokens. The React/Vite frontend is unsupported and will receive HTTP 401 on
protected routes. Do not relaunch it.

Available endpoints include:

- `GET /health` — health check
<<<<<<< HEAD
- `GET /ready` — readiness check; unauthenticated and returns no check details
- `GET /api/auth/login-url` — Google OAuth login URL
=======
- `GET /api/auth/login-url` — Google OAuth login URL (requires the API key)
>>>>>>> df20fed (fix(auth): require API key on OAuth login-url)
- `GET /api/auth/status` — OAuth sign-in status
- `POST /api/group-sheet` — group agents from a Google Sheet and write results back

For service-to-service API callers, see [`docs/api_usage.md`](docs/api_usage.md).

The backend uses shared services from `src.api`, `src.core`, and `src.data`.

> Google Sheet integration requires proper Google OAuth setup. Token state is stored in `src/data/google_oauth_tokens.json`, and the system no longer persists `client_secret` there.

On Windows, restrict access to the token file and its containing directory
(default `src\data`) to the account that runs the API, `SYSTEM`, and
Administrators. The service does not manage Windows ACLs; apply restrictions
manually to both the file and parent directory after confirming the service
account. Keep Modify access for that account so token refresh and atomic writes
continue to work.

### State storage and readiness

By default, state remains in the project directories (`data/`, `models/`,
`outputs/` and `src/data/google_oauth_tokens.json`). Configure paths in the API
process environment before startup:

| Variable | Purpose |
| --- | --- |
| `TAXI_GROUPER_STATE_DIR` | Root for state; data, models and outputs are stored in its `data/`, `models/` and `outputs/` subdirectories, and the OAuth token file defaults to `data/google_oauth_tokens.json`. |
| `TAXI_GROUPER_DATA_DIR` | Optional override for the data directory. |
| `TAXI_GROUPER_MODELS_DIR` | Optional override for the models directory. |
| `TAXI_GROUPER_TOKEN_PATH` | Optional override for the OAuth token file. |

Relative override paths are resolved under `TAXI_GROUPER_STATE_DIR` (or the
project directory when it is unset). On POSIX, newly created state directories
are restricted to mode `0700` and the token file is set to `0600`; an existing
group/world-readable token file is warned about but must be corrected by the
operator. On Windows, token-file permissions must be set by the operator.
`GET /ready` returns `200` only when the state directory is writable, the API
key is at least 32 characters, and the default ML model exists.

The OAuth handshake state is held in memory, so run exactly one API worker.
Multiple workers or server instances do not share OAuth state and may fail the
login callback.

Note: The app requires both the Sheets scope and the Drive "file" scope (`https://www.googleapis.com/auth/drive.file`) so the Google Picker and backend Drive metadata/convert operations can access the user-selected file. Using Sheets-only caused 403s when the picker selected files.

---

## Training the ML model

Taxi Grouper can optionally use a trained ML model to improve ordering inside the grouping rules.

Training expects historical or corrected Excel data containing a valid address column and a grouping column such as `Taxi`, `Groupe`, `Groupe Taxi`, or `Taxi ID`.

Train a model with:

```bash
python train.py --data data/training_files/
```

Or train from corrected data:

```bash
python train.py --data data/corrected/
```

Training writes a candidate under `models/candidate/` by default and never
overwrites the active `models/taxi_grouping_model.pkl`. An explicit
`--output models/` is rejected for the same reason. Automatic retraining after
corrections also evaluates and stores a candidate only; it does not activate it.

Promotion is disabled by default. After reviewing the candidate metrics, enable
the promotion gate and explicitly approve the candidate:

```powershell
$env:MODEL_PROMOTION_ENABLED = "true"
python promote_model.py promote --approve --approved-by "Your Name"
```

The command records the approver, time, candidate version, and metrics in
`models/promotion_log.jsonl`, and saves the previous active model under
`models/rollback/`. To restore the most recently saved active model:

```powershell
python promote_model.py rollback --approve --approved-by "Your Name"
```

The Yellow Express desktop training workflow also saves to `models/candidate/`;
its subsequent dispatch actions continue to load the active model. If no active
trained model exists, the system falls back to rule-based grouping.

---

## Input data expectations

Supported input files are Excel files containing dispatch rows.

Recommended column names:

- `Date`
- `Matricule`
- `Nom - Prénom`
- `Opération`
- `Site`
- `Adresse`
- `Heure d'arrivée`
- `Heure de départ`
- `Taxi`
- `Groupe Taxi`
- `Client`
- `Type de course`

The code is flexible about column order. Address fields may appear with variant names such as:

- `Adresse`
- `Address`
- `Lieu`
- `Localisation`
- `Adresse Ramassage`

The grouping pipeline performs:

1. column detection via `src.core.preprocessing.detect_columns`
2. row filtering via `src.core.preprocessing.filter_dataframe`
3. address normalization and zone detection
4. taxi grouping with a maximum of 4 passengers per taxi

Unknown or unrecognized addresses are marked as `UNKNOWN` and handled separately.

---

## Output files

Grouped Excel files are written to the path you specify in the CLI or exported automatically by Streamlit.

Corrected UI output is saved to `data/corrected/`.

The CLI writes an additional validation report in the same output folder with a `_validation_report.xlsx` suffix.

---

## Run the tests

The repository uses `pytest` for automated tests.

From the project root:

```bash
pytest
```

To run a single file:

```bash
pytest tests/test_grouper.py
```

### Reproducible test environment (Windows)

With Python 3.13.5 registered with the Python launcher, create a fresh
environment and install the fully pinned test dependencies:

```powershell
py -3.13 -m venv .venv-test
.\.venv-test\Scripts\python.exe --version
.\.venv-test\Scripts\python.exe -m pip install -r requirements-test.lock
.\.venv-test\Scripts\python.exe -m pytest
```

The version check should report Python 3.13.5. `.venv-test` is ignored by Git.

---

## Architecture

The codebase now uses a layered `src/` architecture:

- `src/api/` — FastAPI service and endpoint routing
- `src/core/` — core domain logic, grouping, ML model loading, preprocessing, zone handling, and validation
- `src/data/` — Google Sheets and Drive integration, OAuth token flow, and file imports
- `src/adapters/` — export helpers for Excel output and historique-style Excel formatting
- `src/config/` — environment-driven settings, paths, and defaults
- `src/schemas/` — shared constants and schema-level definitions

Other key folders:

- `data/` — runtime data, corrected outputs, OAuth token storage
- `models/` — trained ML artifacts and metadata
- `outputs/` — generated Excel export outputs
- `frontend/` — unsupported React/Vite reference code; do not run
- `tests/` — unit and integration tests

---

## Project structure

```text
.
├── api.py
├── app.py
├── main.py
├── train.py
├── models/
├── data/
├── outputs/
├── src/
│   ├── adapters/
│   ├── api/
│   ├── config/
│   ├── core/
│   ├── data/
│   ├── logging_config.py
│   ├── schemas/
├── frontend/
├── tests/
├── requirements.txt
├── requirements-ui.txt
```

---

## Architecture notes

- `main.py`, `api.py`, and `app.py` now orchestrate the new `src/` packages.
- Model metadata is loaded from `models/config.json` or `models/training_report.json` and attached explicitly to ML models.
- OAuth token storage no longer persists sensitive `client_secret` values.
- Default Google scopes are now limited to `https://www.googleapis.com/auth/spreadsheets`.
- Compatibility rules and constants are in `src/config/__init__.py`.
- Grouping logic is implemented in `src/core/grouper.py`.
- Export formatting lives in `src/adapters/exporter.py`.
- Column detection and input filtering live in `src/core/preprocessing.py`.

### Important behaviors

- Maximum taxi capacity is enforced by the grouping logic.
- ML ordering is optional and cannot override hard zone rules.
- Unknown addresses are preserved and flagged separately.

### Retired React frontend

The `frontend/` folder is retained only as a reference for the later Fleet
Tracker Sheets/Picker port. It is unsupported, protected API routes reject it
with HTTP 401, and it must not be relaunched.

---

## Troubleshooting

- If `streamlit` is not found, confirm the virtual environment is active and that `streamlit` is installed.
- If Excel files fail to load, verify the file format is `.xlsx` or `.xls` and that the sheet contains recognized headers.
- If Google Sheet operations fail, ensure OAuth credentials are configured and `src/data/google_oauth_tokens.json` is writable.
